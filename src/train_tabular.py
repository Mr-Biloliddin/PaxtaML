"""Обучение модели на табличном датасете (CSV / Excel): NDVI, погода, почва и т.п.

Классификация / регрессия (тип задачи определяется по целевой колонке автоматически):
    python src/train_tabular.py --data data/raw/dataset.csv --target risk_level

Детекция аномалий без разметки (Isolation Forest):
    python src/train_tabular.py --data data/raw/dataset.csv --anomaly

Результат в runs/tabular/<дата>/: model.joblib, metrics.json, feature_importance.csv
"""
import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import (accuracy_score, classification_report, f1_score,
                             mean_absolute_error, r2_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, OneHotEncoder

try:
    import xgboost as xgb
except ImportError:  # без xgboost работаем на RandomForest
    xgb = None


def load_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, sep=None, engine="python")  # сам определит , или ;


def gpu_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def build_preprocessor(X: pd.DataFrame) -> ColumnTransformer:
    num_cols = X.select_dtypes(include="number").columns.tolist()
    cat_cols = [c for c in X.columns if c not in num_cols]
    return ColumnTransformer([
        ("num", SimpleImputer(strategy="median"), num_cols),
        ("cat", Pipeline([
            ("imp", SimpleImputer(strategy="most_frequent")),
            ("oh", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), cat_cols),
    ])


def is_classification(y: pd.Series) -> bool:
    return y.dtype == object or str(y.dtype) == "category" or y.nunique() <= 15


def make_model(task: str, n_classes: int, use_gpu: bool):
    if xgb is not None:
        common = dict(n_estimators=600, learning_rate=0.05, max_depth=6, subsample=0.8,
                      colsample_bytree=0.8, tree_method="hist",
                      device="cuda" if use_gpu else "cpu", random_state=42)
        if task == "classification":
            return xgb.XGBClassifier(**common, eval_metric="mlogloss" if n_classes > 2 else "logloss")
        return xgb.XGBRegressor(**common)
    if task == "classification":
        return RandomForestClassifier(n_estimators=500, class_weight="balanced",
                                      n_jobs=-1, random_state=42)
    return RandomForestRegressor(n_estimators=500, n_jobs=-1, random_state=42)


def feature_importance(pipe: Pipeline) -> pd.DataFrame:
    names = pipe.named_steps["prep"].get_feature_names_out()
    imp = pipe.named_steps["model"].feature_importances_
    return (pd.DataFrame({"feature": names, "importance": imp})
            .sort_values("importance", ascending=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="CSV / XLSX / Parquet")
    ap.add_argument("--target", help="целевая колонка (для классификации/регрессии)")
    ap.add_argument("--drop", nargs="*", default=[], help="колонки, которые не использовать (id, дата...)")
    ap.add_argument("--anomaly", action="store_true", help="обучить Isolation Forest без разметки")
    ap.add_argument("--contamination", type=float, default=0.1, help="доля аномалий для --anomaly")
    ap.add_argument("--test-size", type=float, default=0.2)
    ap.add_argument("--out", default="runs/tabular")
    args = ap.parse_args()

    df = load_table(Path(args.data))
    print(f"Загружено: {df.shape[0]} строк, {df.shape[1]} колонок")
    df = df.drop(columns=[c for c in args.drop if c in df.columns])

    out_dir = Path(args.out) / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    use_gpu = gpu_available()

    if args.anomaly:
        X = df.drop(columns=[args.target]) if args.target else df
        pipe = Pipeline([
            ("prep", build_preprocessor(X)),
            ("model", IsolationForest(n_estimators=400, contamination=args.contamination,
                                      random_state=42, n_jobs=-1)),
        ])
        pipe.fit(X)
        scores = -pipe.score_samples(X)  # больше = аномальнее
        flags = pipe.predict(X) == -1
        result = df.assign(anomaly_score=scores, is_anomaly=flags)
        result.to_csv(out_dir / "anomalies.csv", index=False)
        metrics = {"task": "anomaly", "rows": len(df), "anomalies": int(flags.sum())}
        joblib.dump({"pipeline": pipe, "features": X.columns.tolist(), "task": "anomaly"},
                    out_dir / "model.joblib")
        print(f"Аномалий: {flags.sum()} из {len(df)} -> {out_dir / 'anomalies.csv'}")
    else:
        if not args.target:
            ap.error("укажите --target или --anomaly")
        df = df.dropna(subset=[args.target])
        y_raw = df[args.target]
        X = df.drop(columns=[args.target])
        task = "classification" if is_classification(y_raw) else "regression"
        print(f"Задача: {task}, признаков: {X.shape[1]}, "
              f"модель: {'XGBoost' if xgb else 'RandomForest'} ({'GPU' if use_gpu and xgb else 'CPU'})")

        encoder = None
        if task == "classification":
            encoder = LabelEncoder()
            y = encoder.fit_transform(y_raw.astype(str))
            print("Классы:", dict(zip(encoder.classes_.tolist(), np.bincount(y).tolist())))
            strat = y if np.bincount(y).min() >= 2 else None
        else:
            y = y_raw.astype(float).to_numpy()
            strat = None

        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=args.test_size,
                                                  random_state=42, stratify=strat)
        n_classes = len(encoder.classes_) if encoder else 0
        pipe = Pipeline([("prep", build_preprocessor(X)),
                         ("model", make_model(task, n_classes, use_gpu))])
        pipe.fit(X_tr, y_tr)
        pred = pipe.predict(X_te)

        if task == "classification":
            metrics = {"task": task, "accuracy": accuracy_score(y_te, pred),
                       "f1_macro": f1_score(y_te, pred, average="macro")}
            labels = np.arange(n_classes)
            print(classification_report(y_te, pred, labels=labels,
                                        target_names=encoder.classes_, zero_division=0))
        else:
            metrics = {"task": task, "mae": mean_absolute_error(y_te, pred),
                       "r2": r2_score(y_te, pred)}
        print("Метрики:", {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()})

        fi = feature_importance(pipe)
        fi.to_csv(out_dir / "feature_importance.csv", index=False)
        print("Топ-10 важных признаков:\n", fi.head(10).to_string(index=False))

        pipe.fit(X, y)  # финальная модель на всех данных
        joblib.dump({"pipeline": pipe, "features": X.columns.tolist(), "task": task,
                     "classes": encoder.classes_.tolist() if encoder else None,
                     "target": args.target}, out_dir / "model.joblib")

    (out_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"Модель сохранена: {out_dir / 'model.joblib'}")


if __name__ == "__main__":
    main()
