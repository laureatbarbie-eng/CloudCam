# /opt/cloudcam/processing/calib/capture_calib_pairs.py
from pathlib import Path
import shutil
import json
import argparse

def find_pairs(storage_dir: Path, cam_left: str, cam_right: str):
    dL = storage_dir / cam_left
    dR = storage_dir / cam_right
    filesL = sorted(dL.glob("*.jpg"))
    filesR = sorted(dR.glob("*.jpg"))

    by_cycle_L = {}
    for p in filesL:
        cyc = p.stem.split("_")[0]
        by_cycle_L[cyc] = p

    pairs = []
    for p in filesR:
        cyc = p.stem.split("_")[0]
        if cyc in by_cycle_L:
            pairs.append((int(cyc), by_cycle_L[cyc], p))
    pairs.sort(key=lambda x: x[0])
    return pairs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage", default="/var/lib/cloudcam")
    ap.add_argument("--cam_left", default="cam120")
    ap.add_argument("--cam_right", default="cam160")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--out_stereo", default="/var/lib/cloudcam/stereo_calib")
    ap.add_argument("--out_single_left", default="/var/lib/cloudcam/cam120_calib")
    ap.add_argument("--out_single_right", default="/var/lib/cloudcam/cam160_calib")
    ap.add_argument("--dry_run", action="store_true")
    args = ap.parse_args()

    storage = Path(args.storage)
    out_stereo = Path(args.out_stereo); out_stereo.mkdir(parents=True, exist_ok=True)
    out_sl = Path(args.out_single_left); out_sl.mkdir(parents=True, exist_ok=True)
    out_sr = Path(args.out_single_right); out_sr.mkdir(parents=True, exist_ok=True)

    pairs = find_pairs(storage, args.cam_left, args.cam_right)
    if not pairs:
        raise SystemExit("No synchronized pairs found yet.")

    selected = pairs[-args.n:]
    manifest = []

    for cyc, pL, pR in selected:
        outL = out_stereo / f"{cyc}_{args.cam_left}.jpg"
        outR = out_stereo / f"{cyc}_{args.cam_right}.jpg"
        outL_single = out_sl / f"{cyc}.jpg"
        outR_single = out_sr / f"{cyc}.jpg"

        if args.dry_run:
            print("COPY", pL, "->", outL)
            print("COPY", pR, "->", outR)
        else:
            shutil.copy2(pL, outL)
            shutil.copy2(pR, outR)
            shutil.copy2(pL, outL_single)
            shutil.copy2(pR, outR_single)

        manifest.append({
            "cycle_id": cyc,
            "left_src": str(pL),
            "right_src": str(pR),
            "left_out": str(outL),
            "right_out": str(outR),
        })

    man_path = out_stereo / "manifest.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(selected)} pairs; manifest: {man_path}")

if __name__ == "__main__":
    main()
