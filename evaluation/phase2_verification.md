# Phase 2 verification

Phase 2 is complete. No affordability decisions, recommendations, payment optimization,
image extraction or language-model calls were implemented. Phase 3 was not started.

## Results

- Final pytest suite: **62 passed** (13 Phase 1 tests and 49 Phase 2 tests).
- Initial standard-library unittest run: 56 passed; subsequent additions are included
  in the final 62-test pytest run.
- Phase 1 validation: PASS, 275 profiles and 25,342 financial events loaded.
- Phase 2 validation: **250/250 requests, 250 users, zero reconstruction failures**.
- 42 confirmed future salary records, 55 pending debits, 20 scheduled debits.
- 167 active derived income patterns, 2,228 active derived expense patterns.
- 557 recurring expenses satisfy adjustment eligibility; no adjustment is proposed.
- Determinism and indexed-access integration checks pass across all evaluation requests.
- Dataset CSV SHA-256 values remain unchanged through reconstruction tests;
  `git diff --exit-code -- dataset` also passes.
- `git diff --check` passes. `log.txt` and local snapshots are ignored.

## Exact verification commands

Executed from the repository root in PowerShell, using the working Python installation
(the machine's `python.exe` WindowsApps alias could not start):

```powershell
& 'C:\Users\Ragav U\AppData\Local\Python\bin\python.exe' -m unittest discover -s tests -v
& 'C:\Users\Ragav U\AppData\Local\Python\bin\python.exe' -m pytest -q
& 'C:\Users\Ragav U\AppData\Local\Python\bin\python.exe' -m code.main --validate
& 'C:\Users\Ragav U\AppData\Local\Python\bin\python.exe' -m code.main --validate-states --snapshots
& 'C:\Users\Ragav U\AppData\Local\Python\bin\python.exe' -m code.main --build-state request_109
git diff --check
git diff --exit-code -- dataset
git check-ignore log.txt evaluation/state_snapshots/request_100.json
```

The final Phase 1 and Phase 2 commands were also executed through Python
`subprocess.run(..., capture_output=True, text=True)` and both returned exit code 0.
This avoids Windows PowerShell treating informational stderr logging as shell errors
when redirecting it to files. Pytest emitted one unrelated, globally installed
pytest-asyncio default-loop-scope deprecation warning; all tests passed.

## Inspected examples

Examples were selected by reconstructed state properties, without evaluation labels.
Full local snapshots are opt-in and ignored; this artifact retains counts only.

| Request | Situation | Future inflows | Pending debits | Missing amounts | Foreign events | Adjustable recurring expenses |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| request_100 | Income, pending payment, flexible expenses | 1 | 1 | 0 | 0 | 2 |
| request_48 | Largest expense history | 0 | 0 | 1 | 6 | 2 |
| request_101 | Unresolved amount and pending payment | 0 | 1 | 1 | 0 | 3 |
| request_109 | Multiple currencies | 1 | 0 | 0 | 6 | 2 |
| request_97 | Lowest balance/reserve ratio | 1 | 0 | 0 | 0 | 2 |

Inspection confirmed that missing amounts remain null, foreign values retain original
currency and dated conversion metadata, actionable recurring expenses are not protected,
and explicit future salary dates are marked as replacements for inferred occurrences.
No evaluation profile was below its minimum; synthetic tests cover negative/below-reserve
balances, empty income, protected-flexible conflicts, failed retries and lifecycle chains.

## Issues and unresolved evidence

**IMPLEMENTATION ISSUE:** No remaining reconstruction failures. The initial pytest
failure from the `code` package shadowing the stdlib module was fixed by exposing its
console API in `code/__init__.py`.

**DATASET ISSUE:** No additional structured-data warning in the full evaluation-state
run. Synthetic tests exercise invalid currencies, missing FX, missing profile/reserve,
status/date contradictions, cycles, unsupported preferences and invalid monetary bounds.

**UNRESOLVED EVIDENCE:** 324 warnings, deliberately preserved:

| Warning | Count |
| --- | ---: |
| Unparsed messages | 198 |
| Unparsed image references | 11 |
| Missing amounts | 11 |
| Stale inferred patterns | 98 |
| Ambiguous linked extra charges | 6 |

The complete participant dataset has 16 missing amounts; 11 belong to evaluation
requests. Warning counts overlap: an image and its unresolved amount each have a warning.
Stale patterns are an inference uncertainty, not proof of a corrupted dataset. Pending
credits and unrealized investment values do not become cash. No recorded-event FX rate
was missing; future recurrence conversions still require exact occurrence-date rates.

## Files created or changed for Phase 2

Created:

- `code/financial_state.py`
- `code/state_builder.py`
- `code/recurrence.py`
- `code/evidence.py`
- `code/state_diagnostics.py`
- `tests/test_phase2.py`
- `docs/phase2.md`
- `evaluation/state_report.md`
- `evaluation/phase2_verification.md`

Changed: `code/main.py`, `code/__init__.py`, `.gitignore`, `README.md`.
Regenerated the existing Phase 1 `evaluation/data_quality_report.md` using its validator.
Appended the required ignored `log.txt` and generated ignored local snapshots.
Existing uncommitted Phase 1 files were preserved; no dataset file was modified.

## Next-phase interfaces

Phase 3 passes typed, scoped, effective-dated `EvidenceUpdate` values into
`apply_evidence_updates(state, updates)`. Missing-value resolutions and explicit checked
amendments rebuild and revalidate the state without rereading CSVs. Recurrence updates
support new salary/rent amounts and inclusive contract end dates.

Phase 5 consumes the starting balance, reserve, confirmed inflows, required future
outflows, recurring patterns and pending obligations. `event_on_date` and
`recurrence_on_date` provide known amendments for an occurrence date; `normalize_money`
uses the rate table retained in the state. Derived income is explicitly separate from
confirmed future income. See `docs/phase2.md` for the complete consumer contract.
