from flask import Flask, request, jsonify, abort
from pathlib import Path
from datetime import datetime
import time, json, threading

app = Flask(__name__)

CONFIG_PATH = Path(__file__).with_name("config.json")
cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

HOST = cfg["listen_host"]
PORT = int(cfg["listen_port"])
CAM_IDS = list(cfg["cam_ids"])
CAPTURE_PERIOD_SEC = int(cfg["capture_period_sec"])
CAPTURE_LEAD_MS = int(cfg["capture_lead_ms"])
STORAGE_DIR = Path(cfg["storage_dir"])

LOCK = threading.Lock()
state = {
    "cycle_id": 0,
    "cycle_start": time.time(),
    "hello": set(),
    "received": set(),
    "cmd": None,
    "cmd_ts": None,
}

def now_ms() -> int:
    return int(time.time() * 1000)

def cycle_dir(camid: str) -> Path:
    d = STORAGE_DIR / camid
    d.mkdir(parents=True, exist_ok=True)
    return d

def results_dir() -> Path:
    d = STORAGE_DIR / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d

def new_cycle():
    state["cycle_id"] += 1
    state["cycle_start"] = time.time()
    state["hello"] = set()
    state["received"] = set()
    state["cmd"] = None
    state["cmd_ts"] = None

@app.get("/health")
def health():
    with LOCK:
        return jsonify(status="ok", cycle_id=state["cycle_id"], hello=sorted(list(state["hello"])),
                       received=sorted(list(state["received"])))

@app.post("/hello")
def hello():
    if not request.is_json:
        return jsonify(error="expected JSON"), 400
    deviceid = request.json.get("deviceid")
    if deviceid not in CAM_IDS:
        return jsonify(error=f"unknown deviceid {deviceid}"), 400

    with LOCK:
        state["hello"].add(deviceid)

        # если команды ещё нет и обе камеры (или хотя бы одна) объявились, планируем CAPTURE_AT
        if state["cmd"] is None:
            tcap = now_ms() + CAPTURE_LEAD_MS
            state["cmd"] = {"type": "CAPTURE_AT", "cycle_id": state["cycle_id"], "t_capture_ms": tcap, "server_ms": now_ms()}
            state["cmd_ts"] = time.time()

        return jsonify(cycle_id=state["cycle_id"], server_ms=now_ms())

@app.get("/waitcmd")
def waitcmd():
    deviceid = request.args.get("deviceid")
    cycle_id = int(request.args.get("cycle_id", "-1"))
    if deviceid not in CAM_IDS:
        return jsonify(error="unknown deviceid"), 400

    t0 = time.time()
    LONGPOLL_SEC = 25.0
    while time.time() - t0 < LONGPOLL_SEC:
        with LOCK:
            if cycle_id != state["cycle_id"]:
                return jsonify(type="NEWCYCLE", cycle_id=state["cycle_id"], server_ms=now_ms())
            if state["cmd"] is not None:
                # обновим server_ms на момент ответа (важно для CAPTURE_AT выравнивания)
                out = dict(state["cmd"])
                out["server_ms"] = now_ms()
                return jsonify(out)
        time.sleep(0.05)

    return jsonify(type="WAIT", cycle_id=state["cycle_id"], server_ms=now_ms())

@app.post("/upload")
def upload():
    camid = request.args.get("camid") or request.form.get("camid")
    cycle_id = request.args.get("cycle_id") or request.form.get("cycle_id")
    if camid not in CAM_IDS:
        return jsonify(error="unknown camid"), 400
    if "file" not in request.files:
        return jsonify(error="no file field"), 400

    f = request.files["file"]
    if not f or not f.filename:
        return jsonify(error="empty filename"), 400

    meta_raw = request.form.get("meta", "")
    meta = None
    if meta_raw:
        try:
            meta = json.loads(meta_raw)
        except Exception:
            meta = {"_parse_error": True, "raw": meta_raw}

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    base = f"{state['cycle_id']}_{ts}"

    out_jpg = cycle_dir(camid) / f"{base}.jpg"
    out_json = cycle_dir(camid) / f"{base}.json"

    f.save(out_jpg)

    meta_to_save = {
        "cycle_id_server": state["cycle_id"],
        "cycle_id_arg": cycle_id,
        "camid": camid,
        "rx_server_ms": now_ms(),
        "jpg_path": str(out_jpg),
        "meta": meta
    }
    out_json.write_text(json.dumps(meta_to_save, ensure_ascii=False, indent=2), encoding="utf-8")

    with LOCK:
        state["received"].add(camid)

    return jsonify(saved=str(out_jpg), meta=str(out_json), camid=camid, cycle_id=state["cycle_id"])

@app.get("/waitack")
def waitack():
    deviceid = request.args.get("deviceid")
    cycle_id = int(request.args.get("cycle_id", "-1"))
    if deviceid not in CAM_IDS:
        return jsonify(error="unknown deviceid"), 400

    t0 = time.time()
    LONGPOLL_SEC = 25.0
    UPLOAD_WAIT_SEC = 70.0  # окно ожидания, чтобы обе камеры успели загрузить при плохом Wi‑Fi

    while time.time() - t0 < LONGPOLL_SEC:
        with LOCK:
            if cycle_id != state["cycle_id"]:
                return jsonify(type="NEWCYCLE", cycle_id=state["cycle_id"], sleep=False, server_ms=now_ms())

            complete = (state["received"] == set(CAM_IDS))
            timed_out = (state["cmd_ts"] is not None and (time.time() - state["cmd_ts"] > UPLOAD_WAIT_SEC))

            if complete or timed_out:
                ack = {
                    "cycle_id": state["cycle_id"],
                    "complete": complete,
                    "received": sorted(list(state["received"])),
                    "sleep": True,
                    "next_wake_sec": CAPTURE_PERIOD_SEC,
                    "server_ms": now_ms(),
                }
                new_cycle()
                return jsonify(ack)

        time.sleep(0.05)

    return jsonify(type="WAIT", cycle_id=state["cycle_id"], sleep=False, server_ms=now_ms())

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)
