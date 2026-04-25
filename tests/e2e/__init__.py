"""End-to-end test harness for Mesh.

Brings up a kind cluster, injects deterministic failures, runs Mesh's
full remediation loop against the live cluster, and produces a structured
report showing capture → decide → execute → verify.

Entry point: ``scripts/run_e2e.sh``.

Not part of the default unittest discovery — the scenarios in this
package hit a real cluster and take tens of seconds each. The
``test_e2e_harness.py`` module at the top of ``tests/`` covers the
harness plumbing with mocks; that one runs in CI.
"""
