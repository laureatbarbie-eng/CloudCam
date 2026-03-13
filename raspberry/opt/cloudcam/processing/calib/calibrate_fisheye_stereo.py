# /opt/cloudcam/processing/calib/calibrate_fisheye_stereo.py
import cv2 as cv
import numpy as np
from pathlib import Path
import yaml
import json

CALIB_OUT_DIR = Path("/opt/cloudcam/processing/calib_out")
STEREO_DIR = Path("/var/lib/cloudcam/stereo_calib")  # пары кадров cam120/cam160 шахматки
OUT_YAML = CALIB_OUT_DIR / "stereo_fisheye.yml"

CAM_LEFT = "cam120"
CAM_RIGHT = "cam160"

CHECKERBOARD = (9, 6)
SQUARE_SIZE_M = 0.03

def load_cam_params(cam_id):
    p = CALIB_OUT_DIR / f"{cam_id}_fisheye.yml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    K = np.array(data["K"], dtype=np.float64)
    D = np.array(data["D"], dtype=np.float64)
    return K, D, data["image_width"], data["image_height"]

def main():
    K1, D1, w, h = load_cam_params(CAM_LEFT)
    K2, D2, w2, h2 = load_cam_params(CAM_RIGHT)
    assert w == w2 and h == h2

    # Пары файлов вида <idx>_cam120.jpg, <idx>_cam160.jpg
    pairs = []
    for p in sorted(STEREO_DIR.glob("*_cam120.jpg")):
        idx = p.name.split("_cam120.jpg")[0]
        q = STEREO_DIR / f"{idx}_cam160.jpg"
        if q.exists():
            pairs.append((p, q))
    if len(pairs) < 10:
        raise SystemExit("Need >=10 stereo pairs")

    objp = np.zeros((1, CHECKERBOARD[0]*CHECKERBOARD[1], 3), np.float32)
    objp[0, :, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2)
    objp *= SQUARE_SIZE_M

    objpoints = []
    imgpoints1 = []
    imgpoints2 = []

    for pL, pR in pairs:
        imgL = cv.imread(str(pL), cv.IMREAD_GRAYSCALE)
        imgR = cv.imread(str(pR), cv.IMREAD_GRAYSCALE)
        if imgL is None or imgR is None:
            continue

        retL, cornersL = cv.findChessboardCorners(imgL, CHECKERBOARD, None)
        retR, cornersR = cv.findChessboardCorners(imgR, CHECKERBOARD, None)
        if not (retL and retR):
            continue

        cornersL = cv.cornerSubPix(imgL, cornersL, (3, 3), (-1, -1),
                                   (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 1e-6))
        cornersR = cv.cornerSubPix(imgR, cornersR, (3, 3), (-1, -1),
                                   (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 1e-6))

        objpoints.append(objp)
        imgpoints1.append(cornersL)
        imgpoints2.append(cornersR)

    N = len(objpoints)
    print("Stereo valid pairs:", N)
    if N < 10:
        raise SystemExit("Too few valid stereo pairs")

    flags = cv.fisheye.CALIB_FIX_INTRINSIC
    R = np.eye(3)
    T = np.zeros((3, 1))
    rvecs1, rvecs2, tvecs1, tvecs2 = [], [], [], []

    rms, K1n, D1n, K2n, D2n, R, T = cv.fisheye.stereoCalibrate(
        objpoints, imgpoints1, imgpoints2,
        K1, D1, K2, D2,
        (w, h), R, T, flags=flags,
        criteria=(cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 100, 1e-6)
    )

    R1 = np.eye(3)
    R2 = np.eye(3)
    P1 = np.zeros((3, 4))
    P2 = np.zeros((3, 4))
    Q = np.zeros((4, 4))

    cv.fisheye.stereoRectify(
        K1n, D1n, K2n, D2n,
        (w, h), R, T, R1, R2, P1, P2, Q,
        flags=cv.CALIB_ZERO_DISPARITY, newImageSize=(w, h), balance=0.0, fov_scale=1.0
    )

    CALIB_OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "image_width": int(w),
        "image_height": int(h),
        "K1": K1n.tolist(),
        "D1": D1n.tolist(),
        "K2": K2n.tolist(),
        "D2": D2n.tolist(),
        "R": R.tolist(),
        "T": T.tolist(),
        "R1": R1.tolist(),
        "R2": R2.tolist(),
        "P1": P1.tolist(),
        "P2": P2.tolist(),
        "Q": Q.tolist(),
        "rms": float(rms),
        "cam_left": CAM_LEFT,
        "cam_right": CAM_RIGHT
    }
    OUT_YAML.write_text(yaml.safe_dump(data), encoding="utf-8")
    print("Saved", OUT_YAML, "rms=", rms)

if __name__ == "__main__":
    main()
