import os, uuid
from flask import Flask, request, jsonify
from pathlib import Path
from datetime import datetime
import time, json, threading

app = Flask(__name__)

CONFIG_PATH = Path(__file__).with_name("config.json")
cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

HOST = cfg.get("listen_host", "0.0.0.0")
PORT = int(cfg.get("listen_port", 8000))
CAM_IDS = list(cfg["cam_ids"])
CAPTURE_PERIOD_SEC = int(cfg["capture_period_sec"])
CAPTURE_LEAD_MS = int(cfg["capture_lead_ms"])
STORAGE_DIR = Path(cfg["storage_dir"])
API_TOKEN = cfg.get("api_token", "SecretCloudToken123")

# КОНФИГ ОЖИДАЕМЫХ КАДРОВ
EXPECTED_FRAMES = {
    "cam120": 1,
    "cam160": 1,
    "cam180_sky": 2  # Наша новая камера делает 2 снимка (burst)
}

LOCK = threading.Lock()
state = {
    "cycle_id": 0,
    "cycle_start": time.time(),
    "hello": set(),
    "received_counts": {cam: 0 for cam in CAM_IDS}, # Учет КОЛИЧЕСТВА кадров
    "cmd": None,
    "cmd_ts": None,
    "transfers": {} 
}

def now_ms() -> int:
    return int(time.time() * 1000)

def cycle_dir(camid: str) -> Path:
    d = STORAGE_DIR / camid
    d.mkdir(parents=True, exist_ok=True)
    return d

def new_cycle():
    state["cycle_id"] += 1
    state["cycle_start"] = time.time()
    state["hello"] = set()
    state["received_counts"] = {cam: 0 for cam in CAM_IDS}
    state["cmd"] = None
    state["cmd_ts"] = None
    state["transfers"].clear()

@app.before_request
def check_auth():
    if request.endpoint == "health": return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {API_TOKEN}":
        return jsonify(error="Unauthorized"), 401

@app.get("/health")
def health():
    with LOCK:
        return jsonify(status="ok", cycle_id=state["cycle_id"])

@app.post("/hello")
def hello():
    deviceid = request.json.get("deviceid")
    if deviceid not in CAM_IDS: return jsonify(error="unknown device"), 400

    with LOCK:
        state["hello"].add(deviceid)
        if state["cmd"] is None:
            tcap = now_ms() + CAPTURE_LEAD_MS
            state["cmd"] = {"type": "CAPTURE_AT", "cycle_id": state["cycle_id"], "capture_delay_ms": CAPTURE_LEAD_MS}
            state["cmd_ts"] = time.time()
        
        delay_ms = max(0, state["cmd"]["capture_delay_ms"])
        return jsonify(cycle_id=state["cycle_id"], capture_delay_ms=delay_ms)

@app.get("/waitcmd")
def waitcmd():
    cycle_id = int(request.args.get("cycle_id", "-1"))
    t0 = time.time()
    while time.time() - t0 < 25.0:
        with LOCK:
            if cycle_id != state["cycle_id"]:
                return jsonify(type="NEWCYCLE", cycle_id=state["cycle_id"])
            if state["cmd"] is not None:
                return jsonify(state["cmd"])
        time.sleep(0.05)
    return jsonify(type="WAIT", cycle_id=state["cycle_id"])

@app.post("/upload/init")
def upload_init():
    req = request.json
    cam_id = req.get("cam_id")
    cycle_id = req.get("cycle_id")
    
    tid = str(uuid.uuid4())
    temp_path = cycle_dir(cam_id) / f"temp_{tid}.jpg"
    
    with LOCK:
        state["transfers"][tid] = {
            "cam_id": cam_id,
            "cycle_id": cycle_id,
            "file_path": temp_path,
            "chunk_size": req.get("chunk_size", 2048),
            "meta": req
        }
    return jsonify(transfer_id=tid, resume_from_chunk=0)

@app.post("/upload/chunk")
def upload_chunk():
    tid = request.headers.get("X-Transfer-ID")
    idx = int(request.headers.get("X-Chunk-Index", 0))
    data = request.get_data()
    
    with LOCK:
        t = state["transfers"].get(tid)
        if not t: return jsonify(error="Invalid TID"), 400
        
        offset = idx * t["chunk_size"]
        mode = "r+b" if t["file_path"].exists() else "wb"
        with open(t["file_path"], mode) as f:
            f.seek(offset)
            f.write(data)
            
    return "OK"

@app.post("/upload/finalize")
def upload_finalize():
    tid = request.json.get("transfer_id")
    with LOCK:
        t = state["transfers"].get(tid)
        if not t: return jsonify(error="Invalid TID"), 400
        
        cam_id = t["cam_id"]
        # Добавили микросекунды, чтобы 2 кадра burst-съемки не перезаписали друг друга
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S_%f")
        base = f"{t['cycle_id']}_{ts}"
        
        final_jpg = cycle_dir(cam_id) / f"{base}.jpg"
        final_json = cycle_dir(cam_id) / f"{base}.json"
        
        os.rename(t["file_path"], final_jpg)
        final_json.write_text(json.dumps(t["meta"], indent=2), encoding="utf-8")
        
        # Увеличиваем счетчик полученных кадров для этой камеры
        state["received_counts"][cam_id] = state["received_counts"].get(cam_id, 0) + 1
        del state["transfers"][tid]
        
    return jsonify(status="ok")

@app.get("/waitack")
def waitack():
    cycle_id = int(request.args.get("cycle_id", "-1"))
    t0 = time.time()
    while time.time() - t0 < 25.0:
        with LOCK:
            if cycle_id != state["cycle_id"]:
                return jsonify(type="NEWCYCLE", cycle_id=state["cycle_id"], sleep=False)

            # Проверка: все ли камеры загрузили необходимое количество кадров?
            complete = True
            for cid in CAM_IDS:
                if state["received_counts"].get(cid, 0) < EXPECTED_FRAMES.get(cid, 1):
                    complete = False
                    break

            timed_out = (state["cmd_ts"] is not None and (time.time() - state["cmd_ts"] > 70.0))

            if complete or timed_out:
                ack = {"cycle_id": state["cycle_id"], "sleep": True}
                new_cycle()
                return jsonify(ack)
        time.sleep(0.05)
    return jsonify(type="WAIT", cycle_id=state["cycle_id"], sleep=False)

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)