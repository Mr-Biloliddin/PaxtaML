"""Обучение классификатора стадий роста хлопка на GPU.

Запуск:  python src/train.py --config configs/train.yaml
"""
import argparse
import json
import math
import os
import random
import time
from pathlib import Path

import numpy as np
import timm
import torch
import torch.nn as nn
import yaml
from timm.data import resolve_data_config
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from torchmetrics.classification import MulticlassAccuracy, MulticlassF1Score
from torchvision import datasets, transforms
from tqdm import tqdm


def resolve_num_workers(value) -> int:
    if value == "auto":
        return 2 if os.name == "nt" else min(8, os.cpu_count() or 1)
    return int(value)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_transforms(image_size: int, mean, std):
    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(image_size, scale=(0.6, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),  # снимки с дрона/сверху
        transforms.RandomRotation(15),
        transforms.ColorJitter(0.3, 0.3, 0.2, 0.03),  # освещение в поле
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])
    eval_tf = transforms.Compose([
        transforms.Resize(int(image_size * 1.14)),
        transforms.CenterCrop(image_size),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])
    return train_tf, eval_tf


def cosine_with_warmup(optimizer, warmup_steps: int, total_steps: int):
    def fn(step):
        if step < warmup_steps:
            return (step + 1) / max(1, warmup_steps)
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return 0.5 * (1 + math.cos(math.pi * progress))
    return torch.optim.lr_scheduler.LambdaLR(optimizer, fn)


@torch.no_grad()
def evaluate(model, loader, device, num_classes, amp_dtype, channels_last):
    model.eval()
    acc = MulticlassAccuracy(num_classes=num_classes).to(device)
    f1 = MulticlassF1Score(num_classes=num_classes, average="macro").to(device)
    loss_fn = nn.CrossEntropyLoss()
    total_loss, n = 0.0, 0
    for x, y in loader:
        x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
        if channels_last:
            x = x.to(memory_format=torch.channels_last)
        with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            logits = model(x)
        total_loss += loss_fn(logits.float(), y).item() * x.size(0)
        n += x.size(0)
        acc.update(logits, y)
        f1.update(logits, y)
    return total_loss / n, acc.compute().item(), f1.compute().item()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/train.yaml")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    dcfg, mcfg, tcfg = cfg["data"], cfg["model"], cfg["train"]

    seed_everything(tcfg["seed"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("[!] CUDA недоступна — обучение пойдёт на CPU (медленно).")

    amp_dtype = None
    if tcfg["amp"] and device.type == "cuda":
        amp_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    scaler = torch.amp.GradScaler("cuda", enabled=amp_dtype == torch.float16)

    root = Path(dcfg["root"])
    probe = datasets.ImageFolder(root / "train")
    classes = probe.classes
    num_classes = len(classes)
    print(f"Классы ({num_classes}): {classes}")

    model = timm.create_model(mcfg["name"], pretrained=mcfg["pretrained"],
                              num_classes=num_classes, drop_rate=mcfg["drop_rate"])
    data_cfg = resolve_data_config({}, model=model)
    train_tf, eval_tf = build_transforms(dcfg["image_size"], data_cfg["mean"], data_cfg["std"])

    train_ds = datasets.ImageFolder(root / "train", transform=train_tf)
    val_ds = datasets.ImageFolder(root / "val", transform=eval_tf)
    workers = resolve_num_workers(dcfg["num_workers"])
    # На Windows каждый воркер — отдельный процесс с копией torch/CUDA (~1-2 ГБ виртуальной памяти),
    # поэтому много воркеров переполняет файл подкачки. Валидацию там грузим в главном процессе.
    val_workers = 0 if os.name == "nt" else workers
    print(f"DataLoader workers: train={workers}, val={val_workers}")
    pin = device.type == "cuda"
    train_dl = DataLoader(train_ds, batch_size=tcfg["batch_size"], shuffle=True, drop_last=True,
                          num_workers=workers, pin_memory=pin, persistent_workers=workers > 0)
    val_dl = DataLoader(val_ds, batch_size=tcfg["batch_size"] * 2, shuffle=False,
                        num_workers=val_workers, pin_memory=pin, persistent_workers=val_workers > 0)

    model.to(device)
    if tcfg["channels_last"]:
        model.to(memory_format=torch.channels_last)
    train_model = torch.compile(model) if tcfg["compile"] else model

    optimizer = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"],
                                  weight_decay=tcfg["weight_decay"])
    accum = tcfg["grad_accum_steps"]
    steps_per_epoch = math.ceil(len(train_dl) / accum)
    scheduler = cosine_with_warmup(optimizer, tcfg["warmup_epochs"] * steps_per_epoch,
                                   tcfg["epochs"] * steps_per_epoch)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=tcfg["label_smoothing"])

    out_dir = Path(cfg["output_dir"]) / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "classes.json").write_text(json.dumps(classes, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    (out_dir / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    writer = SummaryWriter(out_dir / "tb")

    best_f1, bad_epochs = -1.0, 0
    # история обучения для графика на сайте
    history = {"model": mcfg["name"], "train_size": len(train_ds), "val_size": len(val_ds),
               "classes": classes, "epochs": []}
    for epoch in range(1, tcfg["epochs"] + 1):
        train_model.train()
        running, seen = 0.0, 0
        optimizer.zero_grad(set_to_none=True)
        pbar = tqdm(train_dl, desc=f"epoch {epoch}/{tcfg['epochs']}")
        for i, (x, y) in enumerate(pbar):
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            if tcfg["channels_last"]:
                x = x.to(memory_format=torch.channels_last)
            with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
                loss = loss_fn(train_model(x), y) / accum
            scaler.scale(loss).backward()
            if (i + 1) % accum == 0 or (i + 1) == len(train_dl):
                scaler.unscale_(optimizer)
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
                scheduler.step()
            running += loss.item() * accum * x.size(0)
            seen += x.size(0)
            pbar.set_postfix(loss=f"{running / seen:.4f}", lr=f"{scheduler.get_last_lr()[0]:.2e}")

        val_loss, val_acc, val_f1 = evaluate(model, val_dl, device, num_classes,
                                             amp_dtype, tcfg["channels_last"])
        writer.add_scalar("loss/train", running / seen, epoch)
        writer.add_scalar("loss/val", val_loss, epoch)
        writer.add_scalar("metrics/val_acc", val_acc, epoch)
        writer.add_scalar("metrics/val_f1", val_f1, epoch)
        print(f"val_loss={val_loss:.4f}  val_acc={val_acc:.4f}  val_f1={val_f1:.4f}")
        history["epochs"].append({"epoch": epoch, "train_loss": round(running / seen, 4),
                                  "val_loss": round(val_loss, 4), "val_acc": round(val_acc, 4),
                                  "val_f1": round(val_f1, 4)})
        (out_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=1),
                                              encoding="utf-8")

        ckpt = {"model": model.state_dict(), "model_name": mcfg["name"], "classes": classes,
                "image_size": dcfg["image_size"], "epoch": epoch, "val_f1": val_f1}
        torch.save(ckpt, out_dir / "last.pt")
        if val_f1 > best_f1:
            best_f1, bad_epochs = val_f1, 0
            torch.save(ckpt, out_dir / "best.pt")
            print(f"  -> новый лучший чекпоинт (F1={best_f1:.4f})")
        else:
            bad_epochs += 1
            if bad_epochs >= tcfg["early_stopping_patience"]:
                print("Ранняя остановка.")
                break

    writer.close()
    print(f"Готово. Лучший macro-F1={best_f1:.4f}. Веса: {out_dir / 'best.pt'}")


if __name__ == "__main__":
    main()
