"""Mesh fault-injection simulation.

Drives a synthetic Reth node through the Mesh decision pipeline by
generating ``reth_node`` signals matching the production schema. Faults
are injected over simulated time; results are scored against expected
outcomes; a markdown report summarizes how Mesh handled each scenario.

Entry point: ``python -m simulation``.
"""

__all__ = []
