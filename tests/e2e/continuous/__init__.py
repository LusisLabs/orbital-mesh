"""Continuous chaos session runner for Mesh.

Wraps the existing per-scenario harness in a long-running loop that
picks experiments from a weighted portfolio, interleaves steady-state
probes, and produces a session-level report aligned with the
Principles of Chaos (hypothesis → experiment → observation → verdict).

Entry point: ``scripts/run_chaos_session.sh``.
"""
