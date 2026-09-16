# Golden-vector fixture format

These files are the shared definition of correct behaviour for the domain
logic, consumed by **two** implementations:

* `backend/app/services/*.py` — the Python original, which generates them.
* `mobileapp/cropguard_domain/` — the Dart port that runs on the handset.

Neither is allowed to drift from the other. That is the whole point.

## Why this exists

The repo already learned this lesson once. `frontend/src/lib/yoloDecode.js`
duplicates `backend/app/services/detector.py`, and the Python decoder shipped
two real bugs — a squeeze that collapsed the anchor axis, and an ambiguous
output orientation — that were caught because `yoloDecode.test.js` mirrors
`test_detector.py` case for case with the same numeric expectations.

Porting the risk engine, triage and advisory to Dart creates the same
duplication across a much larger surface, and with a worse failure mode: a
wrong box on screen is visible, a wrong fungicide dose is not. So the parity
discipline is generalised here instead of being re-invented per module.

## File shape

```jsonc
{
  "suite": "triage",
  "source": "backend/app/services/triage.py",
  "description": "...",
  "constants": { "low_confidence_threshold": 0.55 },
  "cases": [
    {
      "id": "confidence_exactly_at_threshold",
      "why": "Exactly 0.55 is NOT low confidence - the rule is '<', so this passes.",
      "fn": "evaluate",
      "input":  { /* plain JSON, no language-specific types */ },
      "expect": { /* the full return value, serialised */ }
    }
  ]
}
```

`constants` is not decoration: the Dart port asserts its own constants against
this block, so a threshold changed on one side and not the other fails loudly
instead of silently diverging.

`why` states what the case defends. A case whose `why` cannot be written is
usually not pinning anything.

## Comparison rules

Both the Python `--check` guard and the Dart test suite apply the same rules:

| | |
|---|---|
| **Hard fields** | Everything not listed below. A difference is a **failure** — a decision changed. |
| **Prose fields** | `explanation`, `message`, `action`, `note`, `display`, `why`. A difference is a **warning** — someone copy-edited a string. |
| **Floats** | Compared with absolute tolerance `1e-6`. Every value in these services is already rounded to ≤ 3 dp; the tolerance exists so a language's last-bit rounding cannot fail a suite. |
| **Booleans** | Compared strictly, never coerced. `0` is not `false`. |
| **Key sets** | Compared in both directions. An extra key fails as loudly as a missing one. |

The hard/soft split is deliberate. A suite that breaks every time somebody
improves the wording of a farmer-facing message is a suite people switch off.

## Regenerating

```bash
python mobileapp/tools/export_fixtures.py --write    # regenerate
python mobileapp/tools/export_fixtures.py --check    # CI guard
```

`--check` re-runs the live Python services against the committed fixtures.
It is the guard for the *Python* side; the Dart test suite is the guard for
the other.

**If `--check` fails, the fixture diff is the point.** Do not regenerate to
make the build green. That diff is the record of what the handset will now do
differently — read it, and land it in the same commit as the change that
caused it, so the behavioural change is reviewable rather than implied.

## Adding a case

1. Add the scenario to the relevant `mobileapp/tools/suite_*.py`.
2. Run `--write`.
3. **Read the generated `expect` block.** It records what the code does, not
   what it should do. A fixture written without reading its output pins a bug
   in place and makes it permanent.

## Determinism

Fixtures must regenerate byte-for-byte on any machine. Nothing in
`fixture_lib.py` touches a clock, a random source, a locale or the network;
timestamps are built from a fixed `BASE_DAY` in UTC. If `--write` produces a
diff on an unchanged tree, that is a bug in the generator.

## Coverage today

| Suite | Cases | Covers |
|---|---|---|
| `geo` | 18 | Grid-cell bucketing incl. negative coordinates, great-circle distance |
| `risk_models` | 40 | Smith, Beaumont, TOMCAST, degree-days, and `summarise_days` |
| `triage` | 25 | All 9 reason codes, every threshold boundary, compound cases |

Not yet pinned — these need their own suites before the matching Dart module
is written: **advisory composition**, **BM25 ranking**, **translation catalog
completeness**, **risk engine** (needs a DB fixture for nearby cases),
**home overview**.
