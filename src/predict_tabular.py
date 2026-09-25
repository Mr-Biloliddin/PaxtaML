"""Предсказание табличной моделью.

python src/predict_tabular.py --model runs/tabular/<дата>/model.joblib --data new.csv --out pred.csv
"""
import argparse
from pathlib import Path

import joblib

from train_tabular import load_table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="predictions.csv")
    args = ap.parse_args()

    bundle = joblib.load(args.model)
    df = load_table(Path(args.data))
    X = df[bundle["features"]]
    pipe = bundle["pipeline"]

    if bundle["task"] == "anomaly":
        df["anomaly_score"] = -pipe.score_samples(X)
        df["is_anomaly"] = pipe.predict(X) == -1
    elif bundle["task"] == "classification":
        classes = bundle["classes"]
        proba = pipe.predict_proba(X)
        df["prediction"] = [classes[i] for i in proba.argmax(1)]
        df["confidence"] = proba.max(1).round(3)
    else:
        df["prediction"] = pipe.predict(X)

    df.to_csv(args.out, index=False)
    print(df.head(20).to_string(index=False))
    print(f"\nСохранено: {args.out}")


if __name__ == "__main__":
    main()
