import cv2 as cv
import numpy as np
from pathlib import Path
import yaml, json, csv
from datetime import datetime

CFG = json.loads(Path("/opt/cloudcam/processing/config.json").read_text(encoding="utf-8"))
STORAGE_DIR = Path(CFG["storage_dir"])
CAM_L, CAM_R = CFG["cam_left"], CFG["cam_right"] # Предположим: cam120 и cam160
CALIB_YAML = Path(CFG["calib_dir"]) / "stereo.yml"
CSV_PATH = Path(CFG["result_csv"])

def load_calib():
    data = yaml.safe_load(CALIB_YAML.read_text(encoding="utf-8"))
    return (np.array(data["K1"]), np.array(data["D1"]), np.array(data["K2"]), np.array(data["D2"]),
            np.array(data["R1"]), np.array(data["R2"]), np.array(data["P1"]), np.array(data["P2"]))

def compute_cbh_orb_multiscale(imgL_path, imgR_path, calib):
    K1, D1, K2, D2, R1, R2, P1, P2 = calib
    
    imgL = cv.imread(str(imgL_path), cv.IMREAD_GRAYSCALE)
    imgR = cv.imread(str(imgR_path), cv.IMREAD_GRAYSCALE)
    if imgL is None or imgR is None: return None

    # 1. Поиск масштабно-инвариантных признаков ORB
    # Увеличиваем количество точек для облаков
    orb = cv.ORB_create(nfeatures=5000, scaleFactor=1.2, nlevels=8)
    kp1, des1 = orb.detectAndCompute(imgL, None)
    kp2, des2 = orb.detectAndCompute(imgR, None)

    if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
        return None

    # 2. Кросс-сопоставление (поиск одинаковых участков облака на 12мм и 16мм)
    bf = cv.BFMatcher(cv.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    
    # Отбираем только надежные совпадения по дистанции Хэмминга
    matches = sorted(matches, key=lambda x: x.distance)
    good_matches = matches[:int(len(matches) * 0.5)] # Берем 50% лучших

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good_matches])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good_matches])

    if len(pts1) < 20: return None

    # 3. Жесткая геометрическая фильтрация (RANSAC)
    # Отсеивает точки, которые сместились "не по законам физики" стереопары
    F, mask = cv.findFundamentalMat(pts1, pts2, cv.FM_RANSAC, 3.0, 0.99)
    if mask is None: return None
    
    pts1_inliers = pts1[mask.ravel() == 1]
    pts2_inliers = pts2[mask.ravel() == 1]

    # 4. Устранение дисторсии и перевод в идеальную плоскость камер
    # Важно: используем P1 и P2 из калибровки для правильного стерео-выравнивания
    pts1_undist = cv.undistortPoints(pts1_inliers.reshape(-1, 1, 2), K1, D1, R=R1, P=P1)
    pts2_undist = cv.undistortPoints(pts2_inliers.reshape(-1, 1, 2), K2, D2, R=R2, P=P2)

    # 5. Триангуляция в 3D пространство (магия вычисления высоты)
    # cv.triangulatePoints возвращает 4D однородные координаты
    pts4D = cv.triangulatePoints(P1, P2, pts1_undist.reshape(2, -1), pts2_undist.reshape(2, -1))
    
    # Перевод в обычные 3D координаты (X, Y, Z) в метрах
    pts3D = pts4D[:3, :] / pts4D[3, :]

    # 6. Извлечение высоты (Ось Z!)
    Z = pts3D[2, :]
    
    # Фильтруем физически невозможные значения (например, отрицательную высоту)
    valid_Z = Z[(Z > 100) & (Z < 10000)] # от 100 м до 10 км

    if len(valid_Z) < 10: # Слишком мало валидных точек для принятия решения
        return None

    # ВНГО (Нижняя граница облачности) - это 10-й перцентиль самых низких точек
    vnogo = float(np.percentile(valid_Z, 10))
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
