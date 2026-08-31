"""Secondary risk layer: XGBoost + SHAP reweighting of the agronomic scores.

This is deliberately *additive refinement*, exactly as scoped in the brief. The
deterministic models in `risk_models.py` are the foundation and always run. If
and only if a trained artifact exists at `ml/weights/risk_xgb.json` -- produced
by `ml/train_risk_xgb.py` from real historical surveillance data (CROPSAP
Maharashtra bulletins, ICAR/NCIPM records) -- this layer nudges the rule-based
score and explains the nudge with SHAP values.

With no artifact present the layer is a documented no-op. Nothing downstream
changes; the API just reports `secondary_layer.active = false` and why. That
honesty is the point: we do not ship a model trained on data that does not
exist.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

from app.config import REPO_ROOT

log = logging.getLogger(__name__)

MODEL_PATH = REPO_ROOT / "ml" / "weights" / "risk_xgb.json"
META_PATH = REPO_ROOT / "ml" / "weights" / "risk_xgb_meta.json"

# Order must match ml/train_risk_xgb.py
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

# How far the secondary layer is allowed to move the rule-based score. Capped
# so a thinly-trained model can never override a fired Smith Period.
MAX_ADJUSTMENT = 0.20


class SecondaryRiskLayer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self._booster = None
        self._explainer = None
        self._meta: dict = {}
        self._reason = "No trained artifact at ml/weights/risk_xgb.json."

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            if not Path(MODEL_PATH).exists():
                log.info("Secondary risk layer inactive: %s", self._reason)
                return
            try:
                import xgboost as xgb

                self._booster = xgb.Booster()
                self._booster.load_model(str(MODEL_PATH))
                if Path(META_PATH).exists():
                    self._meta = json.loads(Path(META_PATH).read_text(encoding="utf-8"))
                self._reason = "Active."
                log.info("Secondary risk layer loaded from %s", MODEL_PATH)
            except Exception as exc:  # pragma: no cover - optional dependency path
                self._booster = None
                self._reason = f"Failed to load XGBoost artifact: {exc}"
                log.warning(self._reason)

    @property
    def active(self) -> bool:
        self._load()
        return self._booster is not None

    def status(self) -> dict:
        self._load()
        return {
            "active": self.active,
            "reason": self._reason,
            "model_path": str(MODEL_PATH),
            "trained_on": self._meta.get("trained_on"),
            "rows": self._meta.get("rows"),
            "features": FEATURE_ORDER,
        }

    def adjust(self, rule_score: float, features: dict[str, float]) -> dict:
        """Return the adjusted score plus a SHAP-based explanation."""
        self._load()
        if not self.active:
            return {
                "active": False,
                "reason": self._reason,
                "rule_score": round(rule_score, 3),
                "adjusted_score": round(rule_score, 3),
                "adjustment": 0.0,
                "contributions": [],
            }

        import xgboost as xgb

        vec = np.array(
            [[float(features.get(name, 0.0)) for name in FEATURE_ORDER]], dtype=np.float32
        )
        dmat = xgb.DMatrix(vec, feature_names=FEATURE_ORDER)
        predicted = float(self._booster.predict(dmat)[0])

        raw_delta = predicted - rule_score
        delta = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, raw_delta))
        adjusted = max(0.0, min(1.0, rule_score + delta))

        contributions: list[dict] = []
        try:
            # pred_contribs gives exact SHAP values for tree models, no extra dependency.
            shap_row = self._booster.predict(dmat, pred_contribs=True)[0]
            pairs = list(zip(FEATURE_ORDER, shap_row[:-1]))
            pairs.sort(key=lambda kv: abs(kv[1]), reverse=True)
            contributions = [
                {
                    "feature": name,
                    "value": round(float(features.get(name, 0.0)), 3),
                    "shap": round(float(val), 4),
                    "direction": "increases risk" if val > 0 else "reduces risk",
                }
                for name, val in pairs[:5]
            ]
        except Exception as exc:  # pragma: no cover
            log.warning("SHAP contribution computation failed: %s", exc)

        return {
            "active": True,
            "reason": "Historical-data model adjusted the agronomic score.",
            "rule_score": round(rule_score, 3),
            "model_score": round(predicted, 3),
            "adjusted_score": round(adjusted, 3),
            "adjustment": round(delta, 3),
            "adjustment_capped": abs(raw_delta) > MAX_ADJUSTMENT,
            "max_adjustment": MAX_ADJUSTMENT,
            "contributions": contributions,
        }


secondary_layer = SecondaryRiskLayer()
