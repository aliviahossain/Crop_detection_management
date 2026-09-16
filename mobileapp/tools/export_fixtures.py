"""Generate (and re-verify) the golden-vector fixtures.

    python mobileapp/tools/export_fixtures.py --write    # regenerate
    python mobileapp/tools/export_fixtures.py --check    # CI guard

`--check` re-runs the Python services against the committed fixtures and fails
on any behavioural difference. Prose differences (an edited message) are
reported as warnings, so a copy edit does not break the build while a changed
decision does.

The same JSON is consumed by the Dart implementation's test suite, which is
the point: two languages, one definition of correct.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIXTURES = HERE.parent / "fixtures"

# `app.*` lives under backend/, and the suite modules import each other flatly.
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(HERE))

from fixture_lib import compare, write_suite  # noqa: E402
import suite_geo  # noqa: E402
import suite_risk_models  # noqa: E402
import suite_triage  # noqa: E402

SUITES = {
    "geo": suite_geo,
    "risk_models": suite_risk_models,
    "triage": suite_triage,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="regenerate fixture files")
    g.add_argument("--check", action="store_true", help="verify committed fixtures still hold")
    ap.add_argument("--suite", action="append", choices=sorted(SUITES), help="limit to one suite")
    args = ap.parse_args()

    names = args.suite or sorted(SUITES)
    failed = False

    for name in names:
        built = SUITES[name].build()
        path = FIXTURES / f"{name}.json"

        if args.write:
            write_suite(path, built)
            print(f"  wrote  {path.relative_to(REPO)}  ({len(built['cases'])} cases)")
            continue

        if not path.exists():
            print(f"  MISSING  {path.relative_to(REPO)} - run with --write")
            failed = True
            continue

        committed = json.loads(path.read_text(encoding="utf-8"))
        by_id = {c["id"]: c for c in committed["cases"]}
        hard_total, soft_total = 0, 0

        for c in built["cases"]:
            prev = by_id.get(c["id"])
            if prev is None:
                print(f"  [{name}] NEW CASE not in fixtures: {c['id']}")
                hard_total += 1
                continue
            hard, soft = compare(prev["expect"], c["expect"], path=c["id"])
            for d in hard:
                print(f"  [{name}] BEHAVIOUR CHANGED  {d}")
            for d in soft:
                print(f"  [{name}] prose changed      {d}")
            hard_total += len(hard)
            soft_total += len(soft)

        for missing in sorted(set(by_id) - {c["id"] for c in built["cases"]}):
            print(f"  [{name}] CASE REMOVED from generator: {missing}")
            hard_total += 1

        status = "FAIL" if hard_total else "ok"
        extra = f", {soft_total} prose" if soft_total else ""
        print(f"  {status:4}  {name:12} {len(built['cases'])} cases, {hard_total} behaviour diffs{extra}")
        failed = failed or hard_total > 0

    if args.check and failed:
        print(
            "\nBehaviour changed. If the change is intentional, re-run with --write "
            "and review the fixture diff as part of the commit - that diff IS the "
            "record of what the handset will now do differently."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
