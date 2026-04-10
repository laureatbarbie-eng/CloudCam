import cv2 as cv
import numpy as np
from pathlib import Path
import yaml, json, csv
from datetime import datetime

CFG = json.loads(Path("/opt/cloudcam/processing/config.json").read_text(encoding="utf-8"))
STORAGE_DIR = Path(CFG["storage_dir"])
CAM_L, CAM_R = CFG["cam_left"], CFG["cam_right"]
CAM_WIND = CFG.get("cam_wind", "cam180")
CALIB_YAML = Path(CFG["calib_dir"]) / "stereo_fisheye.yml"
CSV_PATH = Path(CFG["result_csv"])

WIND_DELAY_SEC = 5.0
FOCAL_LENGTH_PX_180 = 800.0

def load_calib():
    data = yaml.safe_load(CALIB_YAML.read_text(encoding="utf-8"))
    return (
        np.array(data["K1"]), np.array(data["D1"]),
        np.array(data["K2"]), np.array(data["D2"]),
        np.array(data["R1"]), np.array(data["R2"]),
        np.array(data["P1"]), np.array(data["P2"])
    )

def compute_wind_speed(img1_path, img2_path, vnogo_m):
    """
    Возвращает: (wind_speed_mps, wind_dir_deg, wind_status)
    """
    if vnogo_m is None or vnogo_m <= 0:
        return None, None, "vnogo_failed"

    img1 = cv.imread(str(img1_path), cv.IMREAD_GRAYSCALE)
    img2 = cv.imread(str(img2_path), cv.IMREAD_GRAYSCALE)
    if img1 is None or img2 is None:
        return None, None, "wind_images_unreadable"

    h, w = img1.shape
    cz = 512
    y1, y2 = h // 2 - cz // 2, h // 2 + cz // 2
    x1, x2 = w // 2 - cz // 2, w // 2 + cz // 2

    roi1 = np.float32(img1[y1:y2, x1:x2])
    roi2 = np.float32(img2[y1:y2, x1:x2])

    hann = cv.createHanningWindow((cz, cz), cv.CV_32F)
    shift, response = cv.phaseCorrelate(roi1, roi2, window=hann)
    dx, dy = shift

    if response < 0.05:
        return None, None, "low_phasecorr_response"

    gsd = vnogo_m / FOCAL_LENGTH_PX_180
    shift_meters_x = dx * gsd
    shift_meters_y = dy * gsd
    distance_meters = np.sqrt(shift_meters_x**2 + shift_meters_y**2)

    velocity_mps = distance_meters / WIND_DELAY_SEC
    direction_deg = (np.degrees(np.arctan2(dy, dx)) + 360) % 360
    return velocity_mps, direction_deg, "ok"

def compute_cbh_orb_multiscale(imgL_path, imgR_path, calib):
    K1, D1, K2, D2, R1, R2, P1, P2 = calib
    imgL = cv.imread(str(imgL_path), cv.IMREAD_GRAYSCALE)
    imgR = cv.imread(str(imgR_path), cv.IMREAD_GRAYSCALE)
    if imgL is None or imgR is None:
        return None

    orb = cv.ORB_create(nfeatures=5000, scaleFactor=1.2, nlevels=8)
    kp1, des1 = orb.detectAndCompute(imgL, None)
    kp2, des2 = orb.detectAndCompute(imgR, None)
    if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
        return None

    bf = cv.BFMatcher(cv.NORM_HAMMING, crossCheck=True)
    matches = sorted(bf.match(des1, des2), key=lambda x: x.distance)
    good_matches = matches[:int(len(matches) * 0.5)]

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good_matches])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good_matches])
    if len(pts1) < 20:
        return None

    _, mask = cv.findFundamentalMat(pts1, pts2, cv.FM_RANSAC, 3.0, 0.99)
    if mask is None:
        return None

    pts1_inliers = pts1[mask.ravel() == 1]
    pts2_inliers = pts2[mask.ravel() == 1]

    pts1_undist = cv.undistortPoints(pts1_inliers.reshape(-1, 1, 2), K1, D1, R=R1, P=P1)
    pts2_undist = cv.undistortPoints(pts2_inliers.reshape(-1, 1, 2), K2, D2, R=R2, P=P2)

    pts4D = cv.triangulatePoints(P1, P2, pts1_undist.reshape(2, -1), pts2_undist.reshape(2, -1))
    pts3D = pts4D[:3, :] / pts4D[3, :]
    Z = pts3D[2, :]
    valid_Z = Z[(Z > 100) & (Z < 10000)]
    if len(valid_Z) < 10:
        return None
    return float(np.percentile(valid_Z, 10))

def get_files_for_cycle(cycle_id):
    camL_files = list((STORAGE_DIR / CAM_L).glob(f"{cycle_id}_*.jpg"))
    camR_files = list((STORAGE_DIR / CAM_R).glob(f"{cycle_id}_*.jpg"))
    wind_files = sorted(list((STORAGE_DIR / CAM_WIND).glob(f"{cycle_id}_*.jpg")))

    imgL = camL_files[0] if camL_files else None
    imgR = camR_files[0] if camR_files else None
    imgW1 = wind_files[0] if len(wind_files) > 0 else None
    imgW2 = wind_files[1] if len(wind_files) > 1 else None
    return imgL, imgR, imgW1, imgW2

def append_result(cycle_id, vnogo_m, wind_spd, wind_dir, wind_status):
    ts = datetime.utcnow().isoformat() + "Z"

    spd_str = f"{wind_spd:.1f}" if wind_spd is not None else "-"
    dir_str = f"{wind_dir:.0f}" if wind_dir is not None else "-"
    row = [cycle_id, ts, f"{vnogo_m:.1f}", spd_str, dir_str, wind_status]

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow([
                "cycle_id",
                "timestamp_utc",
                "vnogo_m",
                "wind_speed_mps",
                "wind_dir_deg",
                "wind_status",
            ])
        w.writerow(row)

def main():
    calib = load_calib()

    all_cycles = set()
    for f in (STORAGE_DIR / CAM_L).glob("*.jpg"):
        try:
            all_cycles.add(int(f.name.split("_")[0]))
        except Exception:
            continue

    processed_cycles = set()
    if CSV_PATH.exists():
        for line in CSV_PATH.read_text(encoding="utf-8").splitlines()[1:]:
            if not line.strip():
                continue
            try:
                processed_cycles.add(int(line.split(",")[0]))
            except Exception:
                continue

    unprocessed = sorted(list(all_cycles - processed_cycles))

    print(f"[DEBUG] Найдено циклов всего: {len(all_cycles)}")
    print(f"[DEBUG] Уже в CSV: {len(processed_cycles)}")
    print(f"[DEBUG] К обработке: {len(unprocessed)}")

    if not unprocessed:
        print("[INFO] Нет новых циклов для вычисления. Выход.")
        return

    for cycle_id in unprocessed:
        imgL, imgR, imgW1, imgW2 = get_files_for_cycle(cycle_id)

        vnogo = None
        if imgL and imgR:
            vnogo = compute_cbh_orb_multiscale(imgL, imgR, calib)

        if vnogo is None:
            print(f"cycle {cycle_id}: CBH failed. Skipping cycle.")
            continue

        wind_spd, wind_dir, wind_status = None, None, "no_cam180_images"
        if imgW1 and imgW2:
            wind_spd, wind_dir, wind_status = compute_wind_speed(imgW1, imgW2, vnogo)
        elif imgW1 and not imgW2:
            wind_status = "only_one_cam180_image"
        elif (not imgW1) and imgW2:
            wind_status = "only_one_cam180_image"

        print(
            f"cycle {cycle_id}: VNOGO={vnogo:.1f}m | "
            f"Wind={wind_spd}m/s Dir={wind_dir}deg | wind_status={wind_status}"
        )
        append_result(cycle_id, vnogo, wind_spd, wind_dir, wind_status)

if __name__ == "__main__":
    main()