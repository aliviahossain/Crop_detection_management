"""Train the OPTIONAL secondary risk layer (XGBoost + SHAP).

Read this before running it: **you need real historical outbreak data.** The
brief is right that no ready-made dataset links weather + crop stage + variety +
soil + local pest history to actual outbreak events for Indian crops. Until you
have sourced that -- CROPSAP Maharashtra pest surveillance bulletins, ICAR/NCIPM
records, or your own accumulated confirmed cases -- the deterministic agronomic
models in the backend are the whole risk engine, and that is a defensible
position, not a gap.

This script refuses to train on fewer than 200 rows for exactly that reason. A
model fitted on 30 rows of hand-entered data would look like machine learning
and behave like noise.

Expected CSV columns (one row per field-week observation):

    rule_score, temp_mean_c, humidity_mean, rainfall_total_mm, wetness_hours_7d,
    crop_stage_index, variety_susceptibility, soil_drainage_index,
    local_history_count, trap_count_mean, outbreak

`outbreak` is the target: 1 if disease was confirmed in that field within the
following two weeks, else 0. `rule_score` is what the agronomic models said at
the time -- including it is what makes this layer a *correction* to the rules
rather than a replacement for them.

    python ml/train_risk_xgb.py --csv data/cropsap_potato.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

FEATURE_ORDER = [
    "rule_score",
    "temp_mean_c",
    "humidity_mean",
    "rainfall_total_mm",
    "wetness_hours_7d",
    "crop_stage_index",
    "variety_susceptibility",
    "soil_drainage_index",
    "local_history_count",
    "trap_count_mean",
]
TARGET = "outbreak"
MIN_ROWS = 200


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("ml/weights/risk_xgb.json"))
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--force-small", action="store_true", help="Train anyway on a small dataset")
    args = ap.parse_args()

    import numpy as np
    import pandas as pd
    import xgboost as xgb
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.model_selection import train_test_split

    df = pd.read_csv(args.csv)
    missing = [c for c in FEATURE_ORDER + [TARGET] if c not in df.columns]
    if missing:
        print(f"CSV is missing columns: {missing}", file=sys.stderr)
        return 1

    df = df.dropna(subset=[TARGET])
    if len(df) < MIN_ROWS and not args.force_small:
        print(
            f"Only {len(df)} rows. Refusing to train below {MIN_ROWS} -- see this file's "
            "docstring. Pass --force-small only for a pipeline smoke test, never for a model "
            "you intend to deploy.",
            file=sys.stderr,
        )
        return 1

    X = df[FEATURE_ORDER].fillna(0.0).astype("float32")
    y = df[TARGET].astype(int)
    if y.nunique() < 2:
        print("Target has only one class; nothing to learn.", file=sys.stderr)
        return 1

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=args.test_size, random_state=42, stratify=y
    )
    dtrain = xgb.DMatrix(X_tr, label=y_tr, feature_names=FEATURE_ORDER)
    dtest = xgb.DMatrix(X_te, label=y_te, feature_names=FEATURE_ORDER)

    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        # Shallow and heavily regularised on purpose: with a few hundred rows,
        # depth is how you memorise the training set.
        "max_depth": 3,
        "eta": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "lambda": 2.0,
        "scale_pos_weight": float((y_tr == 0).sum() / max((y_tr == 1).sum(), 1)),
        "seed": 42,
    }
    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=400,
        evals=[(dtrain, "train"), (dtest, "test")],
        early_stopping_rounds=40,
        verbose_eval=50,
    )

    pred = booster.predict(dtest)
    auc = float(roc_auc_score(y_te, pred))
    brier = float(brier_score_loss(y_te, pred))

    # SHAP importance, so the deployed explanations are grounded in the same
    # numbers the training run reported.
    contribs = booster.predict(xgb.DMatrix(X_te, feature_names=FEATURE_ORDER), pred_contribs=True)
    importance = {
        name: round(float(np.abs(contribs[:, i]).mean()), 5)
        for i, name in enumerate(FEATURE_ORDER)
    }

    print(f"\nHold-out AUC: {auc:.3f}   Brier: {brier:.4f}")
    print("Mean |SHAP| by feature:")
    for name, val in sorted(importance.items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {name:26s} {val}")

    if auc < 0.6:
        print(
            "\nAUC below 0.6 -- this model is not better than the agronomic rules it would "
            "adjust. Not saving it. Get more or better data.",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(args.out))
    meta_path = args.out.with_name(args.out.stem + "_meta.json")
    meta_path.write_text(
        json.dumps(
            {
                "trained_on": str(args.csv),
                "trained_at": date.today().isoformat(),
                "rows": int(len(df)),
                "features": FEATURE_ORDER,
                "auc": round(auc, 4),
                "brier": round(brier, 4),
                "shap_importance": importance,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved {args.out} and {meta_path}")
    print("The backend picks it up automatically; /risk/models will report it as active.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
