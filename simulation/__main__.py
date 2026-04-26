"""Simulation CLI — drive Mesh through fault scenarios and produce a report.

Default behavior: run the full catalog once with the LLM observer
enabled, since the simulation's purpose is to exercise AI reasoning.
A missing or invalid API key surfaces as a warning, not a fatal — the
deterministic floor still produces results worth reading.

Usage:

    # Sweep the catalog with the Anthropic observer (the common case)
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m simulation

    # Run for 10 minutes, picking faults at random
    python -m simulation --mode cron --duration 600 --interval 15

    # Disable the LLM and just score the deterministic engine
    python -m simulation --no-observer

    # Use OpenAI instead
    OPENAI_API_KEY=... python -m simulation \\
        --observer-provider openai \\
        --observer-base-url https://api.openai.com \\
        --observer-model gpt-4o-mini

The report is written to
``.mesh-runtime-state/simulation/<timestamp>.md`` and also printed to
stdout's tail (the markdown is large but tail-friendly).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from simulation import driver, report
from simulation.fault_catalog import CATALOG


_DEFAULT_OUTPUT_DIR = Path(".mesh-runtime-state") / "simulation"


def _set_env_if_missing(name: str, value: str) -> None:
    """Set an env var only if the user hasn't already set one. Avoids
    silently overriding operator-supplied config when the simulation
    runs inside a configured environment."""
    if not os.environ.get(name):
        os.environ[name] = value


def _configure_observer_env(args: argparse.Namespace) -> bool:
    """Return True if the observer is reachable with current/derived env."""
    if args.no_observer:
        os.environ["MESH_OBSERVER_ENABLED"] = "false"
        return False

    provider = (args.observer_provider or "").lower() or _detect_provider()
    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or args.observer_api_key
        if not api_key:
            print(
                "[sim] WARNING: --no-observer was not set but no ANTHROPIC_API_KEY is "
                "in the environment. The deterministic floor will still run; the "
                "observer will report 'observer disabled' for every fault.",
                file=sys.stderr,
            )
            os.environ["MESH_OBSERVER_ENABLED"] = "false"
            return False
        _set_env_if_missing("MESH_OBSERVER_PROVIDER", "anthropic")
        _set_env_if_missing("MESH_OBSERVER_BASE_URL", "https://api.anthropic.com")
        _set_env_if_missing("MESH_OBSERVER_MODEL", args.observer_model or "claude-sonnet-4-6")
        os.environ["MESH_OBSERVER_API_KEY"] = api_key
        os.environ["MESH_OBSERVER_ENABLED"] = "true"
        return True

    if provider == "openai":
        api_key = (
            os.environ.get("OPENAI_API_KEY")
            or args.observer_api_key
            or os.environ.get("MESH_OBSERVER_API_KEY")
        )
        if not api_key:
            print(
                "[sim] WARNING: OpenAI provider selected but no OPENAI_API_KEY in env. "
                "Running deterministic-only.",
                file=sys.stderr,
            )
            os.environ["MESH_OBSERVER_ENABLED"] = "false"
            return False
        _set_env_if_missing("MESH_OBSERVER_PROVIDER", "openai")
        _set_env_if_missing(
            "MESH_OBSERVER_BASE_URL", args.observer_base_url or "https://api.openai.com"
        )
        _set_env_if_missing("MESH_OBSERVER_MODEL", args.observer_model or "gpt-4o-mini")
        os.environ["MESH_OBSERVER_API_KEY"] = api_key
        os.environ["MESH_OBSERVER_ENABLED"] = "true"
        return True

    print(
        f"[sim] WARNING: unknown observer provider {provider!r}; running "
        "deterministic-only.",
        file=sys.stderr,
    )
    os.environ["MESH_OBSERVER_ENABLED"] = "false"
    return False


def _detect_provider() -> str:
    """Pick a provider when the user didn't specify one. Anthropic wins
    if both keys are present because the simulation was originally
    designed against Claude."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("MESH_OBSERVER_API_KEY"):
        return os.environ.get("MESH_OBSERVER_PROVIDER", "openai").lower()
    return "anthropic"  # default; we'll warn at config time if no key


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m simulation")
    parser.add_argument(
        "--mode",
        choices=("sweep", "cron"),
        default="sweep",
        help="sweep: each fault once. cron: random faults until duration expires.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=300.0,
        help="cron mode: total seconds to run (default 300)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="cron mode: average seconds between fault injections (default 10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="cron mode: RNG seed for fault selection",
    )
    parser.add_argument(
        "--no-observer",
        action="store_true",
        help="run deterministic-only; do not call the LLM",
    )
    parser.add_argument(
        "--observer-provider",
        choices=("anthropic", "openai"),
        default=None,
        help="provider for the LLM observer (auto-detect from env if omitted)",
    )
    parser.add_argument("--observer-base-url", default=None)
    parser.add_argument("--observer-model", default=None)
    parser.add_argument(
        "--observer-api-key",
        default=None,
        help="override the env var; recommended to use ANTHROPIC_API_KEY/OPENAI_API_KEY instead",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_DEFAULT_OUTPUT_DIR),
        help="where to write the markdown report",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="sweep mode: only run the first N faults (debugging)",
    )
    parser.add_argument(
        "--inter-delay",
        type=float,
        default=None,
        help=(
            "seconds to sleep between faults in sweep mode; "
            "defaults to 7s when observer is on (rate-limit safety), 0 otherwise"
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="silence per-run progress lines",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    args = _parse_args(list(argv or sys.argv[1:]))

    observer_active = _configure_observer_env(args)
    print(
        f"[sim] mode={args.mode} observer={'on' if observer_active else 'off'} "
        f"catalog_size={len(CATALOG)}",
        file=sys.stderr,
    )

    engine = driver._build_engine()

    results = []
    if args.mode == "sweep":
        catalog = list(CATALOG)
        if args.limit:
            catalog = catalog[: args.limit]
        # When the observer is on we space requests to stay under the
        # provider's per-minute rate limit. 7s/call ~= 8 RPM, comfortably
        # under Anthropic's tightest tier (10 RPM) and forgiving of any
        # cache-creation requests that count separately.
        inter_delay = (
            args.inter_delay
            if args.inter_delay is not None
            else (7.0 if observer_active else 0.0)
        )
        for i, fault in enumerate(catalog, start=1):
            if not args.quiet:
                print(f"[sim] {i:02d}/{len(catalog):02d} {fault.fault_id}", file=sys.stderr)
            results.append(driver.run_one(engine, fault))
            if inter_delay > 0 and i < len(catalog):
                time.sleep(inter_delay)
    else:
        # Cron mode reuses the same engine for every iteration so any
        # in-process state (active memory, alert store) carries across
        # faults the same way it would in production.
        results = driver.run_cron(
            duration_seconds=args.duration,
            interval_seconds=args.interval,
            seed=args.seed,
            engine=engine,
        )

    output_text = report.render(results, mode=args.mode, observer_active=observer_active)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"sim_{args.mode}_{timestamp}.md"
    report_path.write_text(output_text)

    print(f"[sim] report written to {report_path}", file=sys.stderr)
    # Stream the markdown to stdout so it's easy to pipe or tee.
    sys.stdout.write(output_text)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
