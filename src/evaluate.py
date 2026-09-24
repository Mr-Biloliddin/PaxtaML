"""Оценка обученной модели на отложенном test-наборе + матрица ошибок.

Запуск:  python src/evaluate.py --weights runs/growth_stage/<дата>/best.pt
Результат: отчёт в консоли, confusion_matrix.png и test_report.txt рядом с весами.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import timm
import torch
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score, classification_report,
                             confusion_matrix, f1_score, precision_score, recall_score)
from timm.data import resolve_data_config
from torch.utils.data import DataLoader
from torchvision import datasets, transforms


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--data", default="data/processed/test")
    ap.add_argument("--batch-size", type=int, default=64)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(args.weights, map_location="cpu")
    classes = ckpt["classes"]
    model = timm.create_model(ckpt["model_name"], pretrained=False, num_classes=len(classes))
    model.load_state_dict(ckpt["model"])
    model.to(device).eval()

    data_cfg = resolve_data_config({}, model=model)
    size = ckpt["image_size"]
    tf = transforms.Compose([
        transforms.Resize(int(size * 1.14)),
        transforms.CenterCrop(size),
        transforms.ToTensor(),
        transforms.Normalize(data_cfg["mean"], data_cfg["std"]),
    ])
    ds = datasets.ImageFolder(args.data, transform=tf)
    if ds.classes != classes:
        raise SystemExit(f"Классы test {ds.classes} не совпадают с моделью {classes}")
    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    y_true, y_pred = [], []
    with torch.no_grad():
        for x, y in dl:
            y_pred += model(x.to(device)).argmax(1).cpu().tolist()
            y_true += y.tolist()

    report = classification_report(y_true, y_pred, target_names=classes, digits=3)
    print(report)
    out_dir = Path(args.weights).parent
    (out_dir / "test_report.txt").write_text(report, encoding="utf-8")
    metrics = {
        "test_size": len(y_true),
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
        "precision": round(precision_score(y_true, y_pred, average="macro", zero_division=0), 4),
        "recall": round(recall_score(y_true, y_pred, average="macro", zero_division=0), 4),
        "f1": round(f1_score(y_true, y_pred, average="macro", zero_division=0), 4),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "classes": classes,
    }
    (out_dir / "test_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1),
                                               encoding="utf-8")

    cm = confusion_matrix(y_true, y_pred)
    fig, ax = plt.subplots(figsize=(8, 7))
    ConfusionMatrixDisplay(cm, display_labels=classes).plot(ax=ax, cmap="Greens",
                                                            xticks_rotation=35, colorbar=False)
    ax.set_title("Cotton leaf disease — test set")
    fig.tight_layout()
    fig.savefig(out_dir / "confusion_matrix.png", dpi=150)
    print(f"Сохранено: {out_dir / 'confusion_matrix.png'}, {out_dir / 'test_report.txt'}")


if __name__ == "__main__":
    main()
