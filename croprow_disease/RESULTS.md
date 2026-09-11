# croprow_disease RESULTS

One row per run. Public (LettuceMOTS) and own-frame metrics are kept as
separate rows -- never merged. The `labels` column records where the
healthy/unhealthy classes came from: `colour-derived` means the auto-label
rule in `health.py`, `annotated` means real human health labels. A number
against colour-derived labels measures agreement with that rule, NOT
verified disease accuracy -- do not quote it as the latter.

Per-class mAP50 is reported alongside the mean because the two classes are
imbalanced; a strong overall mAP can hide a weak `unhealthy` class, which
is the one that actually matters operationally.

| run | dataset | labels | mAP50 | mAP50-95 | precision | recall | mAP50 healthy | mAP50 unhealthy | epochs | imgsz |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

<!-- Rows are appended by utils.append_results_row() from notebooks 03/05. -->

## Dataset baseline — LettuceMOTS, colour-derived labels

Measured on the full set (2026-09-11, `HealthParams()` defaults, all 9 labeled
sequences, every frame read):

| | frames | healthy | unhealthy | quality-gated |
| --- | --- | --- | --- | --- |
| train (7 seqs) | 383 | 5,148 | 0 | — |
| val (2 seqs) | 213 | 2,696 | 0 | — |
| **total** | **596** | **7,844** | **0** | 933 (11.9%) |

**LettuceMOTS contains no unhealthy plants.** This is a property of the data,
not a failure of the rule. Establishing it took a specific check, and the check
is worth repeating on any new dataset:

Run without the quality gate, the colour rule *did* return an "unhealthy" tail —
about 1% of instances. Rendering those crops showed they were **motion-blurred,
shadowed and defocused captures**, not brown plants. The two populations
separate almost perfectly on image quality rather than on colour:

| metric | healthy p25 / median | "unhealthy" p75 / max |
| --- | --- | --- |
| sharpness (variance of Laplacian) | 2255 / 3126 | 107 / 899 |
| mean HSV value | 146 / 158 | 107 / 114 |

`min_sharpness` and `min_mean_value` in `HealthParams` sit in those gaps. With
them applied, zero instances remain unhealthy — the honest answer. Without
them, a model trained on this data would have learned to detect camera blur and
called it disease.

So these weights, trained on LettuceMOTS alone, can only be a **localisation
bootstrap**: they learn where plants are and what a healthy canopy looks like.
The `unhealthy` class becomes real only with a dataset that contains affected
plants — see `01b_provided_dataset` (a provided healthy/unhealthy dataset) or
`04_finetune` (your own captures).

Any row logged against `LettuceMOTS-val` with `labels=colour-derived` is
therefore a single-class localisation score wearing a two-class table. Read the
`mAP50 unhealthy` column: if it is `0` or `-`, the model has never seen the
class and the mean in the same row means nothing about disease detection.
