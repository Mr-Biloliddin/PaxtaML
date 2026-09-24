"""Разбивает data/raw/<класс>/*.jpg на train/val/test в data/processed."""
import argparse
import random
import shutil
from pathlib import Path

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/raw")
    ap.add_argument("--dst", default="data/processed")
    ap.add_argument("--val", type=float, default=0.15)
    ap.add_argument("--test", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    src, dst = Path(args.src), Path(args.dst)
    for cls_dir in sorted(p for p in src.iterdir() if p.is_dir()):
        files = sorted(f for f in cls_dir.rglob("*") if f.suffix.lower() in IMG_EXT)
        rng.shuffle(files)
        n_val, n_test = int(len(files) * args.val), int(len(files) * args.test)
        splits = {
            "test": files[:n_test],
            "val": files[n_test:n_test + n_val],
            "train": files[n_test + n_val:],
        }
        for split, items in splits.items():
            out = dst / split / cls_dir.name
            out.mkdir(parents=True, exist_ok=True)
            for f in items:
                shutil.copy2(f, out / f.name)
        print(f"{cls_dir.name}: " + ", ".join(f"{k}={len(v)}" for k, v in splits.items()))


if __name__ == "__main__":
    main()
