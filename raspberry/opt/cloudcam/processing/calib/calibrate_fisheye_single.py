# /opt/cloudcam/processing/calib/calibrate_fisheye_single.py
import cv2 as cv
import numpy as np
from pathlib import Path
import yaml

CAM_ID = "cam120"  # или "cam160"
IMG_DIR = Path(f"/var/lib/cloudcam/{CAM_ID}_calib")  # сюда заранее сложите калибровочные кадры
OUT_YAML = Path(f"/opt/cloudcam/processing/calib_out/{CAM_ID}_fisheye.yml")

# параметры шахматки
CHECKERBOARD = (9, 6)  # внутренние углы
SQUARE_SIZE_M = 0.03   # 3 см, если так печатали

def main():
    images = sorted(IMG_DIR.glob("*.jpg"))
    if not images:
        raise SystemExit(f"No images in {IMG_DIR}")

    objp = np.zeros((1, CHECKERBOARD[0]*CHECKERBOARD[1], 3), np.float32)
    objp[0, :, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2)
    objp *= SQUARE_SIZE_M

    objpoints = []  # 3D
    imgpoints = []  # 2D

    for p in images:
        img = cv.imread(str(p), cv.IMREAD_GRAYSCALE)
        if img is None:
            continue
        ret, corners = cv.findChessboardCorners(img, CHECKERBOARD,
                                                cv.CALIB_CB_ADAPTIVE_THRESH + cv.CALIB_CB_FAST_CHECK + cv.CALIB_CB_NORMALIZE_IMAGE)
        if not ret:
            continue
        corners = cv.cornerSubPix(img, corners, (3, 3), (-1, -1),
                                  (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 1e-6))
        objpoints.append(objp)
        imgpoints.append(corners)

    if len(objpoints) < 10:
        raise SystemExit(f"Too few valid chessboard detections ({len(objpoints)})")

    h, w = img.shape[:2]
    K = np.zeros((3, 3))
    D = np.zeros((4, 1))
    rvecs, tvecs = [], []

    rms, _, _, _, _ = cv.fisheye.calibrate(
        objpoints, imgpoints, (w, h), K, D, rvecs, tvecs,
        cv.fisheye.CALIB_RECOMPUTE_EXTRINSIC + cv.fisheye.CALIB_CHECK_COND + cv.fisheye.CALIB_FIX_SKEW,
        (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 100, 1e-6)
    )
    # После строки: rms, _, _, _, _ = cv.fisheye.calibrate(...)

    print(f"\n=== АНАЛИЗ КАЧЕСТВА КАЛИБРОВКИ ===")
    print(f"RMS ошибка репроекции: {rms:.4f} пикселей")

    # Per-image ошибки
    per_img_errors = []
    for i in range(len(objpoints)):
        imgpoints2, _ = cv.fisheye.projectPoints(
            objpoints[i].reshape(-1, 1, 3), rvecs[i], tvecs[i], K, D
        )
        error = cv.norm(imgpoints[i], imgpoints2, cv.NORM_L2) / len(imgpoints2)
        per_img_errors.append(error)

    per_img_errors = np.array(per_img_errors)

    print(f"Средняя ошибка: {per_img_errors.mean():.4f} px")
    print(f"Медианная: {np.median(per_img_errors):.4f} px")
    print(f"Стд.откл.: {per_img_errors.std():.4f} px")
    print(f"Мин/Макс: {per_img_errors.min():.4f} / {per_img_errors.max():.4f} px")

    # Outliers
    threshold = per_img_errors.mean() + 2 * per_img_errors.std()
    outliers = np.where(per_img_errors > threshold)[0]
    if len(outliers) > 0:
        print(f"\n⚠ ВНИМАНИЕ: {len(outliers)} изображений с высокой ошибкой:")
        for idx in outliers:
            print(f"  Изображение {idx}: {per_img_errors[idx]:.4f} px")

    # Рекомендации
    print("\n=== ОЦЕНКА КАЧЕСТВА ===")
    if rms < 0.5:
        print("✓ ОТЛИЧНО - калибровка высокого качества")
    elif rms < 1.0:
        print("✓ ХОРОШО - приемлемо для большинства задач")
    elif rms < 2.0:
        print("⚠ ПРИЕМЛЕМО - рекомендуется улучшить (добавить 10+ снимков)")
    else:
        print("✗ ПЛОХО - требуется пересъёмка с улучшенными условиями")

    if len(outliers) > 0.2 * len(objpoints):
        print("✗ Более 20% изображений с высокой ошибкой - пересъёмка обязательна")

    # Сохранение детальной статистики
    data['per_image_errors'] = per_img_errors.tolist()
    data['outlier_indices'] = outliers.tolist()
    data['quality_assessment'] = 'excellent' if rms < 0.5 else 'good' if rms < 1.0 else 'acceptable' if rms < 2.0 else 'poor'

    OUT_YAML.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "image_width": int(w),
        "image_height": int(h),
        "K": K.tolist(),
        "D": D.tolist(),
        "rms": float(rms),
        "checkerboard": CHECKERBOARD,
        "square_size_m": SQUARE_SIZE_M,
        "cam_id": CAM_ID,
    }
    OUT_YAML.write_text(yaml.safe_dump(data), encoding="utf-8")
    print(f"Saved {OUT_YAML}, rms={rms}")

if __name__ == "__main__":
    main()
