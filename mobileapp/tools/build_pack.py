"""Assemble a crop pack from the repo's sources, and build the catalogue index.

A crop is a downloadable pack, not an app release. This script is the only
supported way to produce one, because the invariant that matters -- that the
weights, the thresholds tuned FOR those weights, the taxonomy naming their
classes and the KB pages that turn a class into advice all version together --
is not something you can hold in your head while copying files by hand.

    python mobileapp/tools/build_pack.py --crop potato --version 1.0.0
    python mobileapp/tools/build_pack.py --index          # rebuild index.json

Output lands in `dist/packs/`, ready to sync to object storage:

    dist/packs/index.json
    dist/packs/potato/1.0.0/manifest.json
    dist/packs/potato/1.0.0/model.onnx
    ...

`manifest.json` carries a SHA-256 for every payload file. The phone verifies
each one after download and installs atomically, because the payload contains
pesticide dose tables: TLS protects the transport, not a compromised bucket or
a wrong upload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

DIST = REPO / "dist" / "packs"

# Bumped when the on-device reader changes in a way older apps cannot handle.
PACK_FORMAT = 1

# The lab detectors. These are not crops: they localise plants rather than
# diagnosing disease, they carry no knowledge base, and nothing they output is
# turned into treatment advice. They ride the same pack machinery anyway -
# download, verify, atomic install, one version on disk - because that is where
# the safety properties live, and a second delivery path would be a second
# place to get them wrong.
#
# The key IS the endpoint prefix the UI already calls (/croprow, /crophealth).
DETECTORS = {
    "croprow": {
        "title": "Crop row scan",
        "model": REPO / "croprow" / "models" / "best.onnx",
        "classes": ["lettuce"],
        "conf_threshold": 0.25,
        "iou_threshold": 0.45,
        "note": "Single-class crop localisation. Draws boxes; makes no diagnosis.",
    },
    "crophealth": {
        "title": "Crop health scan",
        "model": REPO / "croprow_disease" / "models" / "best.onnx",
        "classes": ["healthy", "unhealthy"],
        "conf_threshold": 0.25,
        "iou_threshold": 0.45,
        "note": (
            "Two-class healthy/unhealthy plant detection. A coarse triage "
            "signal, not a diagnosis: it names no disease and prescribes "
            "nothing."
        ),
    },
}


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 with LF line endings, always.

    ``Path.write_text`` opens in text mode, so on Windows every newline is
    written as CRLF. The manifest hashes THESE bytes, so a pack built on
    Windows and served from anywhere that normalises line endings - git, and
    therefore GitHub Pages - fails its own checksum on install. Three of the
    ten potato files did exactly that, and the installer correctly refused
    the pack it had just published.
    """
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_taxonomy(crop: str) -> dict:
    """Emit the class list from the backend taxonomy, so a pack can never
    disagree with the service that trained and scored it."""
    from app.services import taxonomy as tx

    classes = [c for c in tx.CLASSES if c.crop == crop]
    if not classes:
        raise SystemExit("No classes for crop %r in the backend taxonomy." % crop)
    return {
        "crop": crop,
        # Index order IS the model's output index order. Sorting this would
        # silently relabel every detection.
        "classes": [
            {
                "key": c.key,
                "display": c.display,
                "crop": c.crop,
                "kind": c.kind,
                "pathogen": c.pathogen,
                "severity": c.severity,
                "kb_doc": c.kb_doc,
                "names": c.names,
            }
            for c in classes
        ],
        "non_model_threats": tx.NON_MODEL_THREATS,
    }


def build_strings(crop: str) -> dict:
    """Per-language display names for this pack's classes.

    Kept in the pack rather than the app so a new crop arrives fully named in
    every language, instead of showing an English class key to a Marathi
    farmer until the next app release.
    """
    from app.services import taxonomy as tx

    langs = ("en", "mr", "hi", "bn")
    out: dict[str, dict[str, str]] = {lang: {} for lang in langs}
    for c in tx.CLASSES:
        if c.crop != crop:
            continue
        for lang in langs:
            out[lang][c.key] = c.names.get(lang) or c.display
    for key, names in tx.NON_MODEL_THREATS.items():
        for lang in langs:
            out[lang][key] = names.get(lang) or names.get("en") or key

    # The advisory scaffolding - headings, immediate actions, chemical gating
    # notes, safety bullets - travels with the pack too. The handset composes
    # advisories on-device and has no other source for these, and shipping them
    # here means a farmer reading Marathi gets Marathi advice the moment a new
    # crop installs, without waiting for an app release.
    from app.services.translate import CATALOG

    # `diag.` and `risk.` build the opening paragraph, `action.`/`heading.`/
    # `chemical.` the body, `safety.`/`referral.` the gating text. Miss a
    # prefix and the app renders the raw key at a farmer, which is how
    # `summary.diagnosed` shipped once.
    prefixes = ("action.", "heading.", "chemical.", "note.", "followup.",
                "safety.", "referral.", "diag.", "risk.", "confidence.")
    advisory = {lang: {} for lang in langs}
    for key, entry in CATALOG.items():
        if not key.startswith(prefixes):
            continue
        for lang in langs:
            advisory[lang][key] = entry.get(lang) or entry.get("en") or key

    return {"classes": out, "advisory": advisory}


def build_detector_pack(name: str, version: str, min_app_version: str) -> Path:
    """A detector pack: weights, thresholds and a class list, and nothing else.

    Deliberately no KB and no strings. A crop pack without its treatment pages
    is a bug (it could diagnose but never advise); a detector pack without them
    is correct, because a box around a lettuce is not advice and must not be
    dressed up as any.
    """
    spec = DETECTORS[name]
    out = DIST / name / version
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    model = spec["model"]
    if not model.exists():
        raise SystemExit(
            "No model at %s. Train it (see %s/) and export with its "
            "export_onnx.py before building this pack." % (model, name)
        )
    shutil.copy2(model, out / "model.onnx")

    write_text(
        out / "thresholds.json",
        json.dumps(
            {
                "classes": spec["classes"],
                "per_class": {},
                "default": spec["conf_threshold"],
                "iou_threshold": spec["iou_threshold"],
            },
            indent=2,
        ),
    )
    write_text(
        out / "taxonomy.json",
        json.dumps(
            {
                "crop": name,
                "kind": "detector",
                "title": spec["title"],
                # Index order IS the model output index order.
                "classes": [
                    {"key": c, "display": c.replace("_", " ").title(), "kind": "detector"}
                    for c in spec["classes"]
                ],
                "note": spec["note"],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

    payload = sorted(
        p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"
    )
    manifest = {
        "pack_format": PACK_FORMAT,
        "kind": "detector",
        "crop": name,
        "title": spec["title"],
        "version": version,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_app_version": min_app_version,
        "classes": spec["classes"],
        "files": [
            {
                "path": p.relative_to(out).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": sha256(p),
            }
            for p in payload
        ],
        "signature": None,
    }
    manifest["total_bytes"] = sum(f["bytes"] for f in manifest["files"])
    write_text(
        out / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    print(
        "Built %s@%s (detector): %d files, %.1f MB -> %s"
        % (name, version, len(manifest["files"]), manifest["total_bytes"] / 1e6, out)
    )
    return out


def build_pack(
    crop: str,
    version: str,
    model: Path,
    thresholds: Path,
    kb_dir: Path,
    min_app_version: str,
) -> Path:
    out = DIST / crop / version
    if out.exists():
        shutil.rmtree(out)
    (out / "kb").mkdir(parents=True)

    if not model.exists():
        raise SystemExit(
            "No model at %s. Train on Kaggle (ml/notebooks/) and export with "
            "ml/export_onnx.py before building a pack." % model
        )
    shutil.copy2(model, out / "model.onnx")

    # Thresholds are tuned for THIS quantisation of THIS file. Copying the last
    # release's file onto new weights is a silent accuracy regression that no
    # test catches and no farmer reports, so it is copied here or not at all.
    if not thresholds.exists():
        raise SystemExit(
            "No thresholds at %s; refusing to ship weights without them." % thresholds
        )
    shutil.copy2(thresholds, out / "thresholds.json")

    write_text(
        out / "taxonomy.json",
        json.dumps(build_taxonomy(crop), ensure_ascii=False, indent=2),
    )
    write_text(
        out / "strings.json",
        json.dumps(build_strings(crop), ensure_ascii=False, indent=2),
    )

    tax = json.loads((out / "taxonomy.json").read_text(encoding="utf-8"))
    wanted = {c["kb_doc"] for c in tax["classes"] if c.get("kb_doc")}
    # The cross-cutting pages are what turn a diagnosis into safe advice; a
    # pack without them retrieves a disease page and no dose or safety text.
    wanted |= {"safe_input_usage.md", "referral_and_ipdm.md", "%s_pests.md" % crop}
    copied = 0
    for name in sorted(wanted):
        src = kb_dir / name
        if not src.exists():
            print("  ! missing KB page %s, skipping" % name)
            continue
        shutil.copy2(src, out / "kb" / name)
        copied += 1
    if copied == 0:
        raise SystemExit("Pack has no KB pages; it could diagnose but never advise.")

    payload = sorted(
        p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"
    )
    manifest = {
        "pack_format": PACK_FORMAT,
        "crop": crop,
        "version": version,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_app_version": min_app_version,
        "classes": [c["key"] for c in tax["classes"]],
        "files": [
            {
                "path": p.relative_to(out).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": sha256(p),
            }
            for p in payload
        ],
        # Detached signature over the file list. Left null until a signing key
        # exists; the installer refuses an unsigned pack unless run in dev mode.
        "signature": None,
    }
    manifest["total_bytes"] = sum(f["bytes"] for f in manifest["files"])
    write_text(
        out / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    print(
        "Built %s@%s: %d files, %.1f MB -> %s"
        % (crop, version, len(manifest["files"]), manifest["total_bytes"] / 1e6, out)
    )
    return out


def build_index() -> Path:
    """The catalogue the phone reads first.

    One entry per crop with its versions, so a handset on a metered connection
    fetches a few hundred bytes before deciding whether to pull tens of
    megabytes.
    """
    crops = []
    dirs = sorted(p for p in DIST.iterdir() if p.is_dir()) if DIST.exists() else []
    for crop_dir in dirs:
        versions = []
        kinds: set[str] = set()
        titles: set[str] = set()
        for vdir in sorted(p for p in crop_dir.iterdir() if p.is_dir()):
            mpath = vdir / "manifest.json"
            if not mpath.exists():
                continue
            m = json.loads(mpath.read_text(encoding="utf-8"))
            versions.append(
                {
                    "version": m["version"],
                    "built_at": m["built_at"],
                    "total_bytes": m["total_bytes"],
                    "min_app_version": m["min_app_version"],
                    "classes": m["classes"],
                    "manifest": "%s/%s/manifest.json" % (crop_dir.name, m["version"]),
                }
            )
            kinds.add(m.get("kind", "crop"))
            if m.get("title"):
                titles.add(m["title"])
        if versions:
            versions.sort(key=lambda v: v["built_at"], reverse=True)
            crops.append(
                {
                    "crop": crop_dir.name,
                    # The app treats these differently: a crop pack feeds the
                    # farmer's diagnosis and advisory path, a detector pack
                    # feeds only a lab scanner and advises nothing.
                    "kind": "detector" if kinds == {"detector"} else "crop",
                    "title": sorted(titles)[0] if titles else None,
                    "latest": versions[0]["version"],
                    "versions": versions,
                }
            )
    index = {
        "pack_format": PACK_FORMAT,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "crops": crops,
    }
    DIST.mkdir(parents=True, exist_ok=True)
    path = DIST / "index.json"
    write_text(path, json.dumps(index, ensure_ascii=False, indent=2))
    print("Index: %d crop(s) -> %s" % (len(crops), path))
    return path


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--crop", default="potato")
    ap.add_argument("--version", help="Pack version, e.g. 1.0.0")
    ap.add_argument("--model", type=Path, default=REPO / "ml" / "weights" / "best.onnx")
    ap.add_argument(
        "--thresholds", type=Path, default=REPO / "ml" / "weights" / "thresholds.json"
    )
    ap.add_argument("--kb", type=Path, default=REPO / "backend" / "app" / "data" / "kb")
    ap.add_argument("--min-app-version", default="1.0.0")
    ap.add_argument("--index", action="store_true", help="Only rebuild index.json")
    ap.add_argument(
        "--detector",
        choices=sorted(DETECTORS),
        action="append",
        help="Build a lab detector pack instead of a crop pack (repeatable).",
    )
    args = ap.parse_args()

    if args.index:
        build_index()
        return 0
    if not args.version:
        ap.error("--version is required when building a pack")
    if args.detector:
        for name in args.detector:
            build_detector_pack(name, args.version, args.min_app_version)
        build_index()
        return 0
    build_pack(
        args.crop,
        args.version,
        args.model,
        args.thresholds,
        args.kb,
        args.min_app_version,
    )
    build_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
