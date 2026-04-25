"""Chaos injection primitives for the e2e harness.

Each primitive is a deterministic kubectl-driven mutation that produces a
specific failure mode (CrashLoopBackOff, ImagePullBackOff, OOMKilled,
readiness failure). No dependency on chaos-mesh or any other operator —
the primitives compose into scenarios the harness can run start-to-finish
in CI without extra install steps.

If you need richer failure modes later (network partition, disk IO fault,
kernel panic), adding ``chaos-mesh`` alongside these primitives is the
right follow-up. The scenarios don't care which backend produces the
failure.
"""
