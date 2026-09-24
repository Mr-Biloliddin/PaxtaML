"""Предсказание стадии роста для изображения или папки.

Запуск:  python src/predict.py --weights runs/growth_stage/<дата>/best.pt --input photo.jpg
"""
import argparse
from pathlib import Path

import timm
import torch
from PIL import Image
from timm.data import resolve_data_config
from torchvision import transforms

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--input", required=True)
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

    inp = Path(args.input)
    files = [inp] if inp.is_file() else sorted(f for f in inp.rglob("*") if f.suffix.lower() in IMG_EXT)
    with torch.no_grad():
        for f in files:
            x = tf(Image.open(f).convert("RGB")).unsqueeze(0).to(device)
            probs = model(x).softmax(-1)[0]
            conf, idx = probs.max(0)
            print(f"{f}: {classes[idx]} ({conf.item():.1%})")


if __name__ == "__main__":
    main()
