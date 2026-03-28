import cv2 as cv
import numpy as np
from pathlib import Path
import yaml

CALIB_OUT_DIR = Path("/opt/cloudcam/processing/calib_out")
STEREO_DIR    = Path("/var/lib/cloudcam/stereo_calib")
OUT_YAML      = CALIB_OUT_DIR / "stereo_fisheye.yml"

CAM_LEFT  = "cam120"
CAM_RIGHT = "cam160"

CHECKERBOARD = (9, 6)
SQUARE_SIZE  = 28.0   # мм


def load_cam_params(cam_id):
    p    = CALIB_OUT_DIR / f"{cam_id}_fisheye.yml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    K    = np.array(data["K"], dtype=np.float64)
    D    = np.array(data["D"], dtype=np.float64).reshape(4, 1)
    return K, D, int(data["image_width"]), int(data["image_height"])


def corners_in_bounds(corners, w, h, margin=10):
    pts = corners[:, 0, :]
    return (pts[:, 0].min() > margin and pts[:, 0].max() < w - margin and
            pts[:, 1].min() > margin and pts[:, 1].max() < h - margin)


def stereo_calibrate(obj, ip1, ip2, K1, D1, K2, D2, w, h):
    flags    = cv.fisheye.CALIB_FIX_INTRINSIC
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 100, 1e-6)
    result   = cv.fisheye.stereoCalibrate(
        obj, ip1, ip2,
        K1.copy(), D1.copy(), K2.copy(), D2.copy(),
        (w, h), flags=flags, criteria=criteria
    )
    rms = float(result[0])
    K1n = np.asarray(result[1], dtype=np.float64)
    D1n = np.asarray(result[2], dtype=np.float64)
    K2n = np.asarray(result[3], dtype=np.float64)
    D2n = np.asarray(result[4], dtype=np.float64)
    R   = np.asarray(result[5], dtype=np.float64)  # (3,3) матрица вращения
    T   = np.asarray(result[6], dtype=np.float64)  # (3,1) вектор трансляции
    # result[7] и result[8] — rvecs/tvecs по парам, они нам не нужны
    return rms, K1n, D1n, K2n, D2n, R, T


def stereo_rectify(K1, D1, K2, D2, w, h, R, T):
    # R уже (3,3), T уже (3,1) — приводим типы на всякий случай
    R = np.asarray(R, dtype=np.float64).reshape(3, 3)
    T = np.asarray(T, dtype=np.float64).reshape(3, 1)
    size = (int(w), int(h))
    R1, R2, P1, P2, Q = cv.fisheye.stereoRectify(
        K1, D1, K2, D2,
        size, R, T,
        cv.fisheye.CALIB_ZERO_DISPARITY,
        newImageSize=size,
        balance=0.0,
        fov_scale=1.0
    )
    return R1, R2, P1, P2, Q


def try_calibrate(objpoints, imgpoints1, imgpoints2, indices, K1, D1, K2, D2, w, h):
    obj = [objpoints[i] for i in indices]
    ip1 = [imgpoints1[i] for i in indices]
    ip2 = [imgpoints2[i] for i in indices]
    try:
        stereo_calibrate(obj, ip1, ip2, K1, D1, K2, D2, w, h)
        return True
    except Exception:
        return False


def remove_bad_pairs(objpoints, imgpoints1, imgpoints2, K1, D1, K2, D2, w, h):
    good_idx = list(range(len(objpoints)))
    removed  = []
    for iteration in range(30):
        if try_calibrate(objpoints, imgpoints1, imgpoints2,
                         good_idx, K1, D1, K2, D2, w, h):
            break
        found = False
        for i in range(len(good_idx)):
            subset = good_idx[:i] + good_idx[i+1:]
            if len(subset) < 10:
                break
            if try_calibrate(objpoints, imgpoints1, imgpoints2,
                              subset, K1, D1, K2, D2, w, h):
                removed.append(good_idx[i])
                print(f"  Удалена нестабильная пара {good_idx[i]+1}, осталось {len(subset)}")
                good_idx = subset
                found = True
                break
        if not found:
            break
    return good_idx, removed


def main():
    K1, D1, w, h   = load_cam_params(CAM_LEFT)
    K2, D2, w2, h2 = load_cam_params(CAM_RIGHT)
    assert w == w2 and h == h2, "Разные размеры изображений у камер!"

    pairs = []
    for p in sorted(STEREO_DIR.glob(f"*_{CAM_LEFT}.jpg")):
        idx = p.name.split(f"_{CAM_LEFT}.jpg")[0]
        q   = STEREO_DIR / f"{idx}_{CAM_RIGHT}.jpg"
        if q.exists():
            pairs.append((p, q))

    N_pts = CHECKERBOARD[0] * CHECKERBOARD[1]
    objp  = np.zeros((N_pts, 1, 3), np.float64)
    objp[:, 0, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2)
    objp  *= SQUARE_SIZE

    objpoints, imgpoints1, imgpoints2 = [], [], []
    bad_pairs_count = 0

    for pL, pR in pairs:
        imgL = cv.imread(str(pL), cv.IMREAD_GRAYSCALE)
        imgR = cv.imread(str(pR), cv.IMREAD_GRAYSCALE)
        if imgL is None or imgR is None:
            continue

        retL, cornersL = cv.findChessboardCorners(imgL, CHECKERBOARD,
            cv.CALIB_CB_ADAPTIVE_THRESH + cv.CALIB_CB_FAST_CHECK + cv.CALIB_CB_NORMALIZE_IMAGE)
        retR, cornersR = cv.findChessboardCorners(imgR, CHECKERBOARD,
            cv.CALIB_CB_ADAPTIVE_THRESH + cv.CALIB_CB_FAST_CHECK + cv.CALIB_CB_NORMALIZE_IMAGE)
        if not (retL and retR):
            continue

        cornersL = cv.cornerSubPix(imgL, cornersL, (3, 3), (-1, -1),
            (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 1e-6))
        cornersR = cv.cornerSubPix(imgR, cornersR, (3, 3), (-1, -1),
            (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 1e-6))

        if not (corners_in_bounds(cornersL, w, h) and corners_in_bounds(cornersR, w, h)):
            bad_pairs_count += 1
            continue

        vL = cornersL[8, 0] - cornersL[0, 0]
        vR = cornersR[8, 0] - cornersR[0, 0]
        if np.dot(vL, vR) < 0:
            bad_pairs_count += 1
            continue

        y_diff = np.mean(np.abs(cornersL[:, 0, 1] - cornersR[:, 0, 1]))
        if y_diff > 300:
            bad_pairs_count += 1
            continue

        objpoints.append(objp)
        imgpoints1.append(cornersL.reshape(-1, 1, 2).astype(np.float64))
        imgpoints2.append(cornersR.reshape(-1, 1, 2).astype(np.float64))

    N = len(objpoints)
    print(f"Успешно отобрано стерео-пар: {N} (отброшено: {bad_pairs_count})")
    if N < 10:
        raise SystemExit("Слишком мало пар для калибровки!")

    print("Проверка стабильности данных...")
    good_idx, removed = remove_bad_pairs(
        objpoints, imgpoints1, imgpoints2, K1, D1, K2, D2, w, h)
    if removed:
        print(f"Итого удалено нестабильных пар: {len(removed)}")
    else:
        print("Все пары стабильны.")

    if len(good_idx) < 10:
        raise SystemExit("После очистки осталось слишком мало пар!")

    obj_final = [objpoints[i]  for i in good_idx]
    ip1_final = [imgpoints1[i] for i in good_idx]
    ip2_final = [imgpoints2[i] for i in good_idx]

    print("Запуск финальной калибровки...")
    rms, K1n, D1n, K2n, D2n, R, T = stereo_calibrate(
        obj_final, ip1_final, ip2_final, K1, D1, K2, D2, w, h)

    print("Запуск ректификации...")
    R1, R2, P1, P2, Q = stereo_rectify(K1n, D1n, K2n, D2n, w, h, R, T)

    CALIB_OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "image_width":  int(w),
        "image_height": int(h),
        "K1": K1n.tolist(), "D1": D1n.tolist(),
        "K2": K2n.tolist(), "D2": D2n.tolist(),
        "R":  R.tolist(),   "T":  T.tolist(),
        "R1": R1.tolist(),  "R2": R2.tolist(),
        "P1": P1.tolist(),  "P2": P2.tolist(),
        "Q":  Q.tolist(),
        "rms":        float(rms),
        "cam_left":   CAM_LEFT,
        "cam_right":  CAM_RIGHT,
        "pairs_used": len(good_idx),
    }
    OUT_YAML.write_text(yaml.safe_dump(data), encoding="utf-8")

    print(f"\nСтереокалибровка завершена! RMS = {rms:.4f}")
    print(f"Использовано пар: {len(good_idx)}")
    print(f"Расстояние между камерами: {np.linalg.norm(T):.1f} мм")
    print(f"Файл сохранен: {OUT_YAML}")

    if rms > 3.0:
        print(f"\nВНИМАНИЕ: RMS={rms:.4f} - высокое значение.")
        print("Рекомендуется перекалибровать cam160 (fx=553 подозрительно мал для 1600x1200).")


if __name__ == "__main__":
    main()