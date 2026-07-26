"""DocFlow evaluation harness (T11).

Loads the Goldsmith golden dataset, runs the real extraction pipeline over each
example, and computes quality metrics (field accuracy, schema validity,
review-flag rate and — most importantly — false-confidence rate) grouped by
document category. Entry point: `scripts/docflow_eval/run.py` (invoked by
`make eval`).

The pure scoring logic (`scoring.py`) is unit-tested with mocked inputs
(`tests/test_evals_scoring.py`); the live end-to-end run is itself the
integration test, per the T11 task brief.
"""
