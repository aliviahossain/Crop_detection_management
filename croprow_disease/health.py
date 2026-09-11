"""Colour-based plant-health scoring for the croprow_disease module.

Why this module exists
----------------------
LettuceMOTS is a *single-class* dataset: every annotated instance is "a lettuce
plant". It carries no health/disease attribute. To train a two-class detector
(``healthy`` vs ``unhealthy``) we therefore have to derive the health class from
somewhere, and the only honest source available is **the real pixels inside the
real annotation polygon**.

So: the *boxes* come from the human-drawn LettuceMOTS polygons, and the *class*
comes from a deterministic colour rule applied to the pixels those polygons
enclose. A plant whose canopy is mostly vigorous green is ``healthy``; one whose
canopy has gone brown / yellow / washed-out ("off") is ``unhealthy``.

**This is an auto-label, not agronomist ground truth.** Nothing here is
synthetic -- every pixel is a real captured frame and every polygon is a real
annotation -- but the healthy/unhealthy split is a colour heuristic, and every
metric produced from it must be reported as "colour-derived labels", never as
verified disease ground truth. ``02_verify_labels`` renders a sample so the
rule can be eyeballed, and ``utils.label_report`` prints the score distribution
so the threshold can be tuned against what the crop actually looks like. If
real annotated health labels ever arrive, ``utils.inspect_label_format``
detects 2-class box labels and passes them through untouched instead.

The rule
--------
For each pixel inside the polygon, three tests decide whether it is "vigorous
green canopy":

1. **Hue** in the green band (OpenCV H, 0-179). Green foliage sits around
   H 35-85; senescent brown/yellow tissue falls below it, toward H 5-35.
2. **Excess Green index** ``ExG = 2g - r - b`` on chromatic coordinates
   ``r = R/(R+G+B)`` etc. This is the standard vegetation index for RGB field
   imagery -- it is illumination-normalised, so it survives the exposure swings
   of a cultivator-mounted camera far better than raw RGB thresholds.
3. **Saturation / value floors**, which drop near-grey soil and near-black
   shadow pixels out of the denominator entirely rather than letting them vote.

``health_score`` is then the fraction of *non-background* polygon pixels that
pass (1) and (2). A plant is ``healthy`` when that fraction is at or above
``green_frac_threshold``, else ``unhealthy``. The score is continuous and is
kept alongside the class so a notebook can plot it and re-threshold without
re-reading the images.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

import cv2
import numpy as np

# Two classes. Index order is what lands in the YOLO label files and the data
# yaml -- do NOT reorder without regenerating every label.
HEALTHY = 0
UNHEALTHY = 1
CLASS_NAMES = ["healthy", "unhealthy"]

# BGR draw colours: green for healthy, orange-red for unhealthy.
CLASS_COLORS = {HEALTHY: (0, 200, 0), UNHEALTHY: (0, 90, 235)}


@dataclass(frozen=True)
class HealthParams:
    """Thresholds for the colour rule. Defaults tuned on LettuceMOTS train.

    Every notebook takes these from its config cell, so a different crop or
    camera can be retuned in one place without editing this module.
    """

    hue_lo: int = 35          # OpenCV hue (0-179); green band lower edge
    hue_hi: int = 85          # green band upper edge
    sat_min: int = 45         # below this the pixel is grey-ish -> background
    val_min: int = 35         # below this the pixel is shadow -> background
    val_max: int = 250        # above this the pixel is blown out -> background
    exg_min: float = 0.05     # excess-green index floor for "vigorous"
    green_frac_threshold: float = 0.55   # >= this fraction green -> healthy
    min_canopy_pixels: int = 25          # see classify_score
    # Quality gates -- see `judgeable` and the note in classify_score. These
    # floors are measured, not guessed. Over 120 random LettuceMOTS frames
    # (1588 instances), every instance the colour rule called "unhealthy" was a
    # motion-blurred or shadowed capture rather than a brown plant, and the two
    # populations separate almost perfectly on image quality:
    #
    #     metric       healthy p25 / median   "unhealthy" p75 / max
    #     sharpness         2255 / 3126              107 / 899
    #     mean_value         146 /  158              107 / 114
    #
    # The thresholds sit in those gaps. A genuinely brown plant shot sharply and
    # in good light still passes the gate and is still classified on colour --
    # only crops too blurred or too dark to judge are excluded.
    min_sharpness: float = 1000.0  # variance of Laplacian over the instance crop
    min_mean_value: int = 120      # mean HSV V; below this the crop is in shadow

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_PARAMS = HealthParams()


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #
def polygon_to_pixels(poly_norm: Sequence[float], width: int, height: int) -> np.ndarray:
    """Normalized ``[x1, y1, x2, y2, ...]`` -> int pixel vertices ``(N, 2)``."""
    pts = np.asarray(poly_norm, dtype=np.float64).reshape(-1, 2)
    pts[:, 0] = np.clip(pts[:, 0], 0.0, 1.0) * width
    pts[:, 1] = np.clip(pts[:, 1], 0.0, 1.0) * height
    return np.round(pts).astype(np.int32)


def polygon_mask(poly_norm: Sequence[float], width: int, height: int) -> np.ndarray:
    """Filled uint8 mask (255 inside the polygon) at full frame size."""
    mask = np.zeros((height, width), dtype=np.uint8)
    pts = polygon_to_pixels(poly_norm, width, height)
    if len(pts) >= 3:
        cv2.fillPoly(mask, [pts], 255)
    return mask


def bbox_from_polygon(poly_norm: Sequence[float]) -> tuple[float, float, float, float] | None:
    """Axis-aligned normalized ``(cx, cy, w, h)`` from polygon vertices.

    Same derivation croprow uses -- min/max of the real annotation's vertices,
    clamped to the frame. ``None`` for a degenerate (zero-area) box.
    """
    pts = np.asarray(poly_norm, dtype=np.float64).reshape(-1, 2)
    xs = np.clip(pts[:, 0], 0.0, 1.0)
    ys = np.clip(pts[:, 1], 0.0, 1.0)
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    w, h = x1 - x0, y1 - y0
    if w <= 0.0 or h <= 0.0:
        return None
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0, w, h


# --------------------------------------------------------------------------- #
# Colour indices
# --------------------------------------------------------------------------- #
def excess_green(img_bgr: np.ndarray) -> np.ndarray:
    """Excess Green index (ExG = 2g - r - b) on chromatic coordinates.

    Returns a float32 array in roughly [-1, 2]. Chromatic normalisation makes
    it largely invariant to how bright the frame is, which matters for a
    tractor-mounted camera moving in and out of its own shadow.
    """
    bgr = img_bgr.astype(np.float32)
    total = bgr.sum(axis=2)
    total[total == 0] = 1.0          # avoid /0 on pure-black pixels
    b, g, r = bgr[..., 0] / total, bgr[..., 1] / total, bgr[..., 2] / total
    return 2.0 * g - r - b


def canopy_masks(
    img_bgr: np.ndarray, params: HealthParams = DEFAULT_PARAMS
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(foreground, green)`` boolean masks for a whole frame.

    ``foreground`` = pixels colourful and bright enough to be plant tissue at
    all (soil, deep shadow and blown-out highlights are excluded, so they never
    dilute the score). ``green`` = foreground pixels that are *also* in the
    green hue band and above the ExG floor, i.e. vigorous canopy.
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    foreground = (s >= params.sat_min) & (v >= params.val_min) & (v <= params.val_max)
    in_green_hue = (h >= params.hue_lo) & (h <= params.hue_hi)
    green = foreground & in_green_hue & (excess_green(img_bgr) >= params.exg_min)
    return foreground, green


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def score_mask(
    img_bgr: np.ndarray,
    mask: np.ndarray,
    params: HealthParams = DEFAULT_PARAMS,
) -> tuple[float, int]:
    """``(health_score, canopy_pixels)`` for one masked instance.

    ``health_score`` is the fraction of canopy (non-background) pixels inside
    the mask that read as vigorous green. ``canopy_pixels`` is how many pixels
    that fraction was computed over -- the caller needs it to know whether the
    score is trustworthy or came from a handful of edge pixels.
    """
    sel = mask.astype(bool)
    if not sel.any():
        return 0.0, 0
    foreground, green = canopy_masks(img_bgr, params)
    canopy = int(np.count_nonzero(foreground & sel))
    if canopy == 0:
        return 0.0, 0
    return float(np.count_nonzero(green & sel)) / canopy, canopy


def crop_quality(img_bgr: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    """``(sharpness, mean_value)`` for the masked region's bounding crop.

    Sharpness is the variance of the Laplacian -- the standard blur metric: a
    crisp leaf edge produces large second derivatives, a motion-blurred smear
    produces almost none. ``mean_value`` is the mean HSV V channel, i.e. how
    well lit the crop is.
    """
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return 0.0, 0.0
    crop = img_bgr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    if crop.size == 0:
        return 0.0, 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_value = float(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 2].mean())
    return sharpness, mean_value


def judgeable(
    canopy_pixels: int,
    sharpness: float,
    mean_value: float,
    params: HealthParams = DEFAULT_PARAMS,
) -> bool:
    """Whether this instance can be judged on colour at all.

    False for instances that are too small, too blurred, or too dark. Verified
    against LettuceMOTS: rendering the lowest-scoring instances showed motion
    blur, deep shadow and defocus -- image-capture artifacts, not senescence.
    Without this gate the rule labels camera problems as disease, and a model
    trained on it learns to detect blur.
    """
    return (
        canopy_pixels >= params.min_canopy_pixels
        and sharpness >= params.min_sharpness
        and mean_value >= params.min_mean_value
    )


def classify_score(
    score: float,
    canopy_pixels: int,
    params: HealthParams = DEFAULT_PARAMS,
    sharpness: float = float("inf"),
    mean_value: float = float("inf"),
) -> int:
    """Map a health score to ``HEALTHY`` / ``UNHEALTHY``.

    Instances that fail ``judgeable`` -- too few usable pixels, too blurred, or
    too dark -- are called ``HEALTHY``. That is the deliberate conservative
    choice: a colour rule with nothing trustworthy to look at should not be the
    thing that invents a disease detection. ``utils.label_report`` counts these
    separately so the fraction of low-confidence labels stays visible rather
    than buried.

    The sharpness/value defaults are infinite so a caller that has not measured
    them keeps the old size-only behaviour instead of silently failing the gate.
    """
    if not judgeable(canopy_pixels, sharpness, mean_value, params):
        return HEALTHY
    return HEALTHY if score >= params.green_frac_threshold else UNHEALTHY


def classify_polygon(
    img_bgr: np.ndarray,
    poly_norm: Sequence[float],
    params: HealthParams = DEFAULT_PARAMS,
) -> tuple[int, float, int, float, float]:
    """``(class_id, health_score, canopy_pixels, sharpness, mean_value)``.

    The quality numbers come back with the class so callers can report how many
    labels were decided on real evidence versus defaulted by the quality gate.
    """
    height, width = img_bgr.shape[:2]
    mask = polygon_mask(poly_norm, width, height)
    score, canopy = score_mask(img_bgr, mask, params)
    sharpness, mean_value = crop_quality(img_bgr, mask)
    cls = classify_score(score, canopy, params, sharpness, mean_value)
    return cls, score, canopy, sharpness, mean_value


def classify_bbox(
    img_bgr: np.ndarray,
    box_norm: Sequence[float],
    params: HealthParams = DEFAULT_PARAMS,
) -> tuple[int, float, int, float, float]:
    """Same, for a normalized ``(cx, cy, w, h)`` box instead of a polygon.

    Used when a dataset ships boxes rather than polygons. A box includes soil
    between the leaves, so the background rejection in ``canopy_masks`` is what
    keeps the score meaningful here -- it is nonetheless a looser signal than
    the polygon path, which is why polygons are preferred when available.
    """
    cx, cy, w, h = (float(v) for v in box_norm)
    height, width = img_bgr.shape[:2]
    x0 = int(round(max(cx - w / 2, 0.0) * width))
    y0 = int(round(max(cy - h / 2, 0.0) * height))
    x1 = int(round(min(cx + w / 2, 1.0) * width))
    y1 = int(round(min(cy + h / 2, 1.0) * height))
    mask = np.zeros((height, width), dtype=np.uint8)
    if x1 > x0 and y1 > y0:
        mask[y0:y1, x0:x1] = 255
    score, canopy = score_mask(img_bgr, mask, params)
    sharpness, mean_value = crop_quality(img_bgr, mask)
    cls = classify_score(score, canopy, params, sharpness, mean_value)
    return cls, score, canopy, sharpness, mean_value
