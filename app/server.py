"""Локальный веб-сервер для проверки модели по фото листа хлопка.

Запуск:  python app/server.py                    (последняя модель из runs/growth_stage)
         python app/server.py --weights путь/best.pt --port 8000
Открыть: http://127.0.0.1:8000
"""
import argparse
import io
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from advice import LOW_CONFIDENCE, advice_for  # noqa: E402


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
        self.info = {"weights": str(weights), "model": ckpt["model_name"],
                     "classes": self.classes, "device": str(self.device),
                     "val_f1": round(float(ckpt.get("val_f1", 0)), 4)}

    def predict(self, img: Image.Image) -> list[tuple[str, float]]:
        x = self.tf(img.convert("RGB")).unsqueeze(0).to(self.device)
        with self.torch.no_grad():
            probs = self.model(x).softmax(-1)[0].cpu().tolist()
        return sorted(zip(self.classes, probs), key=lambda p: p[1], reverse=True)


def find_latest_weights() -> Path | None:
    found = sorted(ROOT.glob("runs/growth_stage/*/best.pt"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def create_app(predictor) -> FastAPI:
    app = FastAPI(title="PaxtaML")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/info")
    def info():
        return predictor.info

    @app.post("/api/predict")
    async def predict(file: UploadFile = File(...)):
        try:
            img = Image.open(io.BytesIO(await file.read()))
            img.load()
        except (UnidentifiedImageError, OSError):
            raise HTTPException(400, "Не удалось прочитать изображение")
        ranked = predictor.predict(img)
        top_cls, top_p = ranked[0]
        return {
            "prediction": top_cls,
            "confidence": round(top_p, 4),
            "low_confidence": top_p < LOW_CONFIDENCE,
            "probabilities": [{"class": c, "p": round(p, 4)} for c, p in ranked],
            "advice": advice_for(top_cls, top_p),
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
