# PaxtaML — мониторинг роста хлопка

Локальное обучение на GPU (NVIDIA + CUDA) двух типов моделей:

1. **Классификация стадии роста** (`src/train.py`): всходы → бутонизация → цветение → коробочки → раскрытие.
2. **Детекция объектов** (`src/train_yolo.py`): растения, бутоны, цветки, коробочки, для подсчёта и оценки урожая.

## 1. Требования

- Видеокарта NVIDIA, свежий драйвер (`nvidia-smi` должен работать)
- Python 3.10–3.12
- CUDA Toolkit отдельно ставить **не нужно**: колёса PyTorch уже содержат CUDA и cuDNN

| Видеокарта / драйвер | Параметр |
|---|---|
| RTX 20xx/30xx/40xx, драйвер ≥ 560 | `cu126` (по умолчанию) |
| RTX 50xx (Blackwell), драйвер ≥ 570 | `cu128` |
| Старый драйвер (≥ 520) | `cu118` |

## 2. Установка

Linux:
```bash
./install_gpu.sh                # или: CUDA=cu128 ./install_gpu.sh
source .venv/bin/activate
```

Windows:
```bat
install_gpu.bat                 :: или: install_gpu.bat cu128
.venv\Scripts\activate
```

В конце скрипт запускает `scripts/check_gpu.py`. Он должен вывести название GPU и `OK`.

## 3. Датасет

### Классификация стадий
Положите фото по папкам-классам:
```
data/raw/
  1_vskhody/        *.jpg
  2_butonizatsiya/  *.jpg
  3_tsvetenie/      *.jpg
  4_korobochki/     *.jpg
  5_raskrytie/      *.jpg
```
Затем разбейте на train/val/test:
```bash
python scripts/split_dataset.py      # -> data/processed/{train,val,test}
```

### Детекция (YOLO)
```
data/yolo/images/{train,val}/*.jpg
data/yolo/labels/{train,val}/*.txt   # class cx cy w h (0..1)
```
Классы задаются в `configs/yolo_data.yaml`. Разметку можно делать в CVAT, Label Studio или Roboflow (экспорт в формате YOLO).

## 4. Обучение

### Табличный датасет (CSV/Excel: NDVI, погода, почва…) — быстрый старт
```bash
# классификация риска / регрессия урожайности — тип задачи определяется сам
python src/train_tabular.py --data data/raw/dataset.csv --target risk_level --drop zone_id date
# поиск аномальных зон без разметки (Isolation Forest)
python src/train_tabular.py --data data/raw/dataset.csv --anomaly --drop zone_id date
# предсказание
python src/predict_tabular.py --model runs/tabular/<дата>/model.joblib --data new.csv --out pred.csv
```
XGBoost автоматически использует GPU, если он есть. Результаты: `runs/tabular/<дата>/` (model.joblib, metrics.json, feature_importance.csv).

### Фото

```bash
# классификатор стадий роста
python src/train.py --config configs/train.yaml
tensorboard --logdir runs/growth_stage       # графики

# детектор
python src/train_yolo.py --data configs/yolo_data.yaml --model yolo11s.pt
```

Предсказание:
```bash
python src/predict.py --weights runs/growth_stage/<дата>/best.pt --input path/to/images
```

## 5. Локальный сайт «Oq Oltin»

```bash
python app/server.py            # Windows: run_app.bat
```
Откройте http://127.0.0.1:8000. Страницы:

| Страница | Данные |
|---|---|
| **ИИ-анализ** | реальная модель: загрузка фото (кнопка, drag&drop, Ctrl+V, камера телефона) → диагноз, вероятности, время каждого шага, рекомендации; метрики и график обучения из `history.json` / `test_metrics.json` |
| Обзор, Поля, Фитосанитария | демо-данные хозяйства из `app/demo_data.json` (помечены «демо-данные»); фото берутся из `data/processed/test`; блок «Последние распознавания» — реальная история анализов |

- Модель по умолчанию — последний `runs/growth_stage/*/best.pt`; другая: `--weights путь/best.pt`.
- Чтобы на сайте появились метрики на test (Accuracy/Precision/Recall/F1), один раз запустите `python src/evaluate.py --weights …/best.pt`.
- История анализов и загруженные фото хранятся в `runs/app/`.
- Открыть с телефона в той же Wi-Fi сети: `python app/server.py --host 0.0.0.0` → `http://<IP компьютера>:8000`.
- Тексты рекомендаций по болезням — `app/advice.py`.

## 6. Что уже настроено для GPU

- Смешанная точность (AMP): bf16 на Ampere и новее, иначе fp16 с GradScaler
- TF32, `cudnn.benchmark`, `channels_last`, `pin_memory`, многопоточная загрузка данных
- Накопление градиентов (`grad_accum_steps`) для маленьких GPU
- `torch.compile` по желанию (`compile: true`, лучше работает на Linux)
- Косинусный LR с прогревом, label smoothing, ранняя остановка по macro-F1

## 7. Если не хватает памяти (CUDA out of memory)

- Уменьшите `batch_size` (32 → 16 → 8) и увеличьте `grad_accum_steps`
- Уменьшите `image_size` (384 → 288 → 224)
- Возьмите модель поменьше: `efficientnet_b0`, `convnext_nano`, `resnet50`
- Для YOLO: `--batch -1` сам подбирает размер батча, либо `--model yolo11n.pt`
- На Windows при ошибках DataLoader поставьте `num_workers: 0`
