# /opt/cloudcam/processing/cbh_compute.py
import cv2 as cv
import numpy as np
from pathlib import Path
import yaml, json, csv, time
from datetime import datetime

CFG = json.loads(Path("/opt/cloudcam/processing/config.json").read_text(encoding="utf-8"))

STORAGE_DIR = Path(CFG["storage_dir"])
CAM_L = CFG["cam_left"]
CAM_R = CFG["cam_right"]
CALIB_YAML = Path(CFG["calib_dir"]) / "stereo_fisheye.yml"
MIN_H = float(CFG["min_height_m"])
MAX_H = float(CFG["max_height_m"])
ROI_CENTER_FRAC = float(CFG["roi_center_frac"])
CSV_PATH = Path(CFG["result_csv"])
JSONL_PATH = Path(CFG["result_jsonl"])

def load_calib():
    data = yaml.safe_load(CALIB_YAML.read_text(encoding="utf-8"))
    K1 = np.array(data["K1"], dtype=np.float64)
    D1 = np.array(data["D1"], dtype=np.float64)
    K2 = np.array(data["K2"], dtype=np.float64)
    D2 = np.array(data["D2"], dtype=np.float64)
    R1 = np.array(data["R1"], dtype=np.float64)
    R2 = np.array(data["R2"], dtype=np.float64)
    P1 = np.array(data["P1"], dtype=np.float64)
    P2 = np.array(data["P2"], dtype=np.float64)
    Q = np.array(data["Q"], dtype=np.float64)
    return (K1, D1, K2, D2, R1, R2, P1, P2, Q, data)

def last_pairs():
    dL = STORAGE_DIR / CAM_L
    dR = STORAGE_DIR / CAM_R
    filesL = sorted(dL.glob("*.jpg"))
    filesR = sorted(dR.glob("*.jpg"))
    by_cycle_L = {}
    for p in filesL:
        stem = p.stem  # <cycle>_<ts>
        cyc = stem.split("_")[0]
        by_cycle_L[cyc] = p
    pairs = []
    for p in filesR:
        cyc = p.stem.split("_")[0]
        if cyc in by_cycle_L:
            pairs.append((int(cyc), by_cycle_L[cyc], p))
    pairs.sort(key=lambda x: x[0])
    return pairs

def compute_cbh_for_pair(cycle_id, imgL_path, imgR_path, calib):
    K1, D1, K2, D2, R1, R2, P1, P2, Q, meta = calib
    imgL = cv.imread(str(imgL_path), cv.IMREAD_GRAYSCALE)
    imgR = cv.imread(str(imgR_path), cv.IMREAD_GRAYSCALE)
    if imgL is None or imgR is None:
        return None

    h, w = imgL.shape
    # rectification maps
    map1x, map1y = cv.fisheye.initUndistortRectifyMap(K1, D1, R1, P1[:, :3], (w, h), cv.CV_32FC1)
    map2x, map2y = cv.fisheye.initUndistortRectifyMap(K2, D2, R2, P2[:, :3], (w, h), cv.CV_32FC1)
    rL = cv.remap(imgL, map1x, map1y, interpolation=cv.INTER_LINEAR)
    rR = cv.remap(imgR, map2x, map2y, interpolation=cv.INTER_LINEAR)

    # ORB features
    orb = cv.ORB_create(2000)
    kptsL, desL = orb.detectAndCompute(rL, None)
    kptsR, desR = orb.detectAndCompute(rR, None)
    if desL is None or desR is None:
        return None
    bf = cv.BFMatcher(cv.NORM_HAMMING, crossCheck=True)
    matches = bf.match(desL, desR)
    if len(matches) < 30:
        return None

    matches = sorted(matches, key=lambda m: m.distance)[:500]
    ptsL = np.float32([kptsL[m.queryIdx].pt for m in matches])
    ptsR = np.float32([kptsR[m.trainIdx].pt for m in matches])

    # Триангуляция (в прямоугольной системе после rectification)
    # Построим проекционные матрицы
    P1_ = P1
    P2_ = P2
    ptsL_h = cv.convertPointsToHomogeneous(ptsL)[:, 0, :]
    ptsR_h = cv.convertPointsToHomogeneous(ptsR)[:, 0, :]
    pts4d = cv.triangulatePoints(P1_, P2_, ptsL.T, ptsR.T)
    pts3d = (pts4d[:3, :] / pts4d[3, :]).T  # (N,3)

    # Координаты: X,Y,Z в системе rectified (оси зависят от R,T), нам нужна "высота".
    # При зените и симметричной геометрии можно принять Z как "вдоль луча", Y как "вертикаль" условно.
    # В отсутствии точной ориентации берём модуль высоты как компонент с минимальной дисперсией у земли.
    Z = pts3d[:, 2]
    Y = pts3d[:, 1]

    # Грубый фильтр по расстоянию: облака должны быть дальше определённого радиуса
    dist = np.linalg.norm(pts3d, axis=1)
    mask = (dist > MIN_H) & (dist < 50000)
    pts3d = pts3d[mask]
    Y = pts3d[:, 1]

    if len(Y) < 30:
        return None

    # Оценка "высоты": берём отрицательную/положительную ось в зависимости от кластера
    medianY = np.median(Y)
    if abs(medianY) < 1e-3:
        return None

    # Примем признак: облака "сверху" относительно камеры -> выбираем >= некоторого порога
    # Здесь упрощённо: ВНГО ≈ нижний перцентиль по |Y|
    Yabs = np.abs(Y)
    vnogo = float(np.percentile(Yabs, 10))
    if vnogo < MIN_H or vnogo > MAX_H:
        return None

    return vnogo

def append_result(cycle_id, vnogo_m):
    ts = datetime.utcnow().isoformat() + "Z"
    row = [cycle_id, ts, f"{vnogo_m:.1f}"]
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["cycle_id", "timestamp_utc", "vnogo_m"])
        w.writerow(row)
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSONL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"cycle_id": cycle_id,
                            "timestamp_utc": ts,
                            "vnogo_m": vnogo_m}) + "\n")

def main():
    calib = load_calib()
    pairs = last_pairs()
    if not pairs:
        print("No pairs")
        return
    processed_cycles = set()
    if CSV_PATH.exists():
        for line in CSV_PATH.read_text(encoding="utf-8").splitlines()[1:]:
            if not line.strip():
                continue
            cid = int(line.split(",")[0])
            processed_cycles.add(cid)

    for cycle_id, imgL, imgR in pairs:
        if cycle_id in processed_cycles:
            continue
        vnogo = compute_cbh_for_pair(cycle_id, imgL, imgR, calib)
        if vnogo is None:
            print(f"cycle {cycle_id}: CBH failed")
            continue
        print(f"cycle {cycle_id}: VNOGO={vnogo:.1f} m")
        append_result(cycle_id, vnogo)

if __name__ == "__main__":
    main()
