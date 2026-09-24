"""Обучение YOLO-детектора (растения, бутоны, цветки, коробочки) на GPU.

Запуск:  python src/train_yolo.py --data configs/yolo_data.yaml --model yolo11s.pt
"""
import argparse

import torch
from ultralytics import YOLO


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="configs/yolo_data.yaml")
    ap.add_argument("--model", default="yolo11s.pt")  # n/s/m/l/x — больше = точнее и медленнее
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=1024)  # мелкие объекты на снимках с дрона
    ap.add_argument("--batch", type=int, default=-1)    # -1 = автоподбор под память GPU
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    device = 0 if torch.cuda.is_available() else "cpu"
    YOLO(args.model).train(
        data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        workers=args.workers, device=device, amp=True, cache=False,
        project="runs/yolo", name="cotton", patience=20,
    )


if __name__ == "__main__":
    main()
