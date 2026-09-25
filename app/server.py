"""Локальный сайт «Oq Oltin» — мониторинг хлопка + проверка модели по фото листа.

Запуск:  python app/server.py                    (последняя модель из runs/growth_stage)
         python app/server.py --weights путь/best.pt --port 8000
Открыть: http://127.0.0.1:8000
"""
import argparse
import io
import json
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
STATIC = APP_DIR / "static"
STATE_DIR = ROOT / "runs" / "app"          # история анализов и загруженные фото
UPLOADS = STATE_DIR / "uploads"
HISTORY_FILE = STATE_DIR / "history.json"
SAMPLES_DIR = ROOT / "data" / "processed" / "test"
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

sys.path.insert(0, str(APP_DIR))
from advice import ADVICE, LOW_CONFIDENCE, advice_for  # noqa: E402


class Predictor:
    def __init__(self, weights: Path):
        import timm
        import torch
        from timm.data import resolve_data_config
        from torchvision import transforms

        self.torch = torch
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        ckpt = torch.load(weights, map_location="cpu")
        self.classes = ckpt["classes"]
        self.model = timm.create_model(ckpt["model_name"], pretrained=False,
                                       num_classes=len(self.classes))
        self.model.load_state_dict(ckpt["model"])
        self.model.to(self.device).eval()
        cfg = resolve_data_config({}, model=self.model)
        size = ckpt["image_size"]
        self.tf = transforms.Compose([
            transforms.Resize(int(size * 1.14)),
            transforms.CenterCrop(size),
            transforms.ToTensor(),
            transforms.Normalize(cfg["mean"], cfg["std"]),
        ])
        self.weights_dir = weights.parent
        self.info = {"weights": str(weights), "model": ckpt["model_name"],
                     "classes": self.classes, "device": str(self.device),
                     "image_size": size, "epoch": ckpt.get("epoch"),
                     "val_f1": round(float(ckpt.get("val_f1", 0)), 4)}
        # прогрев, чтобы первый запрос на демо не был медленным
        self.predict(Image.new("RGB", (size, size)))

    def predict(self, img: Image.Image):
        """Возвращает (отсортированные вероятности, тайминги в мс)."""
        t0 = time.perf_counter()
        x = self.tf(img.convert("RGB")).unsqueeze(0).to(self.device)
        t1 = time.perf_counter()
        with self.torch.no_grad():
            probs = self.model(x).softmax(-1)[0].cpu().tolist()
        t2 = time.perf_counter()
        ranked = sorted(zip(self.classes, probs), key=lambda p: p[1], reverse=True)
        return ranked, {"preprocess": (t1 - t0) * 1000, "inference": (t2 - t1) * 1000}


def find_latest_weights() -> Path | None:
    found = sorted(ROOT.glob("runs/growth_stage/*/best.pt"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class History:
    """Последние анализы: хранятся в runs/app/history.json, фото — в runs/app/uploads."""

    def __init__(self, limit: int = 60):
        self.limit = limit
        self.lock = threading.Lock()
        UPLOADS.mkdir(parents=True, exist_ok=True)
        self.items = read_json(HISTORY_FILE, [])

    def add(self, img: Image.Image, record: dict) -> dict:
        rid = uuid.uuid4().hex[:12]
        thumb = img.convert("RGB")
        thumb.thumbnail((640, 640))
        thumb.save(UPLOADS / f"{rid}.jpg", quality=85)
        record = {"id": rid, "image": f"/uploads/{rid}.jpg",
                  "time": datetime.now().isoformat(timespec="seconds"), **record}
        with self.lock:
            self.items.insert(0, record)
            for old in self.items[self.limit:]:
                (UPLOADS / f"{old['id']}.jpg").unlink(missing_ok=True)
            self.items = self.items[:self.limit]
            HISTORY_FILE.write_text(json.dumps(self.items, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        return record


def list_samples(per_class: int = 3) -> dict:
    """Несколько фото из test-набора на класс — для демо-страниц."""
    out = {}
    if SAMPLES_DIR.is_dir():
        for cls_dir in sorted(p for p in SAMPLES_DIR.iterdir() if p.is_dir()):
            files = sorted(f for f in cls_dir.iterdir() if f.suffix.lower() in IMG_EXT)[:per_class]
            out[cls_dir.name] = [f"/samples/{cls_dir.name}/{f.name}" for f in files]
    return out


def create_app(predictor) -> FastAPI:
    app = FastAPI(title="Oq Oltin")
    history = History()
    UPLOADS.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
    if SAMPLES_DIR.is_dir():
        app.mount("/samples", StaticFiles(directory=SAMPLES_DIR), name="samples")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/info")
    def info():
        wdir = getattr(predictor, "weights_dir", None)
        return {
            **predictor.info,
            "low_confidence": LOW_CONFIDENCE,
            "titles": {c: ADVICE.get(c, {}).get("short", c) for c in predictor.classes},
            "training": read_json(wdir / "history.json") if wdir else None,
            "test": read_json(wdir / "test_metrics.json") if wdir else None,
        }

    @app.get("/api/demo")
    def demo():
        return {**read_json(APP_DIR / "demo_data.json", {}), "samples": list_samples()}

    @app.get("/api/history")
    def get_history(limit: int = 12):
        return history.items[:limit]

    @app.post("/api/predict")
    async def predict(file: UploadFile = File(...), field: str = Form("")):
        t0 = time.perf_counter()
        try:
            img = Image.open(io.BytesIO(await file.read()))
            img = ImageOps.exif_transpose(img)  # фото с телефона — правильная ориентация
            img.load()
        except (UnidentifiedImageError, OSError):
            raise HTTPException(400, "Не удалось прочитать изображение")
        t_load = (time.perf_counter() - t0) * 1000
        ranked, timing = predictor.predict(img)
        top_cls, top_p = ranked[0]
        t_adv = time.perf_counter()
        advice = advice_for(top_cls, top_p)
        timing = {"load": t_load, **timing, "advice": (time.perf_counter() - t_adv) * 1000}
        record = history.add(img, {
            "prediction": top_cls, "title": advice["title"], "severity": advice["severity"],
            "confidence": round(top_p, 4), "field": field.strip()[:60],
        })
        return {
            "id": record["id"],
            "image": record["image"],
            "prediction": top_cls,
            "confidence": round(top_p, 4),
            "low_confidence": top_p < LOW_CONFIDENCE,
            "probabilities": [{"class": c, "title": ADVICE.get(c, {}).get("short", c),
                               "p": round(p, 4)} for c, p in ranked],
            "advice": advice,
            "timing_ms": {k: round(v, 1) for k, v in timing.items()},
        }

    return app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", help="путь к best.pt (по умолчанию — последний из runs/growth_stage)")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 — открыть для других устройств в сети")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    weights = Path(args.weights) if args.weights else find_latest_weights()
    if weights is None or not weights.is_file():
        raise SystemExit("Модель не найдена. Сначала обучите: python src/train.py "
                         "или укажите --weights путь/best.pt")
    predictor = Predictor(weights)
    print(f"Модель: {weights}  ({predictor.info['device']})")
    print(f"Откройте в браузере: http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}")
    uvicorn.run(create_app(predictor), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
