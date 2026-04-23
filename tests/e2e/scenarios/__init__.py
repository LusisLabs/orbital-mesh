"""E2E scenarios.

Each module here defines one named scenario as a callable that takes a
:class:`tests.e2e.harness.Harness` and returns a dict of fields to
merge into the resulting :class:`tests.e2e.harness.ScenarioRun`.

Adding a scenario:

1. Create ``tests/e2e/scenarios/<name>.py`` with a ``run(harness)``
   function.
2. Register it in ``scripts/run_e2e.sh`` or in the driver script.
3. The harness handles timing, automatic chaos revert, and failure
   capture; the scenario only needs to describe what to break and
   what to assert.
"""
