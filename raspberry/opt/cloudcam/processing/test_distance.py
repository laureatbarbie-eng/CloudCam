import cv2 as cv
import numpy as np
from pathlib import Path
import yaml
import sys

CALIB_YAML = Path("/opt/cloudcam/processing/calib_out/stereo_fisheye.yml")
CHECKERBOARD = (9, 6)

def main():
    if len(sys.argv) < 3:
        print("Использование: python3 test_distance.py <фото_120.jpg> <фото_160.jpg>")
        return

    imgL_path = sys.argv[1]
    imgR_path = sys.argv[2]

    data = yaml.safe_load(CALIB_YAML.read_text(encoding="utf-8"))
    K1 = np.array(data["K1"]); D1 = np.array(data["D1"])
    K2 = np.array(data["K2"]); D2 = np.array(data["D2"])
    
    R = np.array(data["R"])
    T = np.array(data["T"])

    imgL = cv.imread(imgL_path, cv.IMREAD_GRAYSCALE)
    imgR = cv.imread(imgR_path, cv.IMREAD_GRAYSCALE)

    if imgL is None or imgR is None:
        print("Ошибка загрузки картинок!")
        return

    retL, cornersL = cv.findChessboardCorners(imgL, CHECKERBOARD, cv.CALIB_CB_ADAPTIVE_THRESH + cv.CALIB_CB_FAST_CHECK + cv.CALIB_CB_NORMALIZE_IMAGE)
    retR, cornersR = cv.findChessboardCorners(imgR, CHECKERBOARD, cv.CALIB_CB_ADAPTIVE_THRESH + cv.CALIB_CB_FAST_CHECK + cv.CALIB_CB_NORMALIZE_IMAGE)

    if not (retL and retR):
        print("Не удалось распознать доску на одном или обоих кадрах!")
        return

    cornersL = cv.cornerSubPix(imgL, cornersL, (3, 3), (-1, -1), (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 1e-6))
    cornersR = cv.cornerSubPix(imgR, cornersR, (3, 3), (-1, -1), (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 1e-6))

    vL = cornersL[8, 0] - cornersL[0, 0]
    vR = cornersR[8, 0] - cornersR[0, 0]
    if np.dot(vL, vR) < 0:
        cornersR = cornersR[::-1]

    pts1_norm = cv.fisheye.undistortPoints(cornersL, K1, D1)
    pts2_norm = cv.fisheye.undistortPoints(cornersR, K2, D2)

    pts1_for_tri = pts1_norm.reshape(-1, 2).T
    pts2_for_tri = pts2_norm.reshape(-1, 2).T

    Proj1 = np.hstack((np.eye(3), np.zeros((3, 1))))
    Proj2 = np.hstack((R, T))

    pts4D = cv.triangulatePoints(Proj1, Proj2, pts1_for_tri, pts2_for_tri)
    pts3D = pts4D[:3, :] / pts4D[3, :]

    Z = np.abs(pts3D[2, :])
    
    print(f"Сырые значения глубины (первые 5 точек): {Z[:5]}")
    
    if len(Z) > 0:
        distance = float(np.median(Z))
        print(f"РАССЧИТАННОЕ РАССТОЯНИЕ ДО ДОСКИ: {distance:.1f} мм (это {distance / 10:.1f} см!)")
    else:
        print("Точки не найдены.")

    # Рисуем связи
    kp1 = [cv.KeyPoint(float(p[0][0]), float(p[0][1]), 1) for p in cornersL]
    kp2 = [cv.KeyPoint(float(p[0][0]), float(p[0][1]), 1) for p in cornersR]
    matches = [cv.DMatch(i, i, 0) for i in range(len(cornersL))]
    
    img_matches = cv.drawMatches(imgL, kp1, imgR, kp2, matches, None, matchColor=(0, 255, 0), flags=2)
    cv.imwrite("/opt/cloudcam/processing/test_matches_chess.jpg", img_matches)
    print("Сохранена картинка с сопоставлением: /opt/cloudcam/processing/test_matches_chess.jpg")

if __name__ == "__main__":
    main()