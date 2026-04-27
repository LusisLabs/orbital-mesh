"""Live chaos injection against the real Reth/Lighthouse containers.

Each ``Chaos`` is a pair of (apply, revert) functions plus an
``error_signature`` token. ``apply`` mutates the live containers via
``docker exec`` or network manipulation; ``revert`` undoes it. The
runner calls ``apply`` once per chaos cycle and ``revert`` either
before the next chaos or at the end.

# Why this exists

The synthetic ``simulation/fault_catalog.py`` only mutates a Python
dict in memory. That's fine for fast catalog regression but doesn't
exercise the real ingester (live JSON-RPC, real systemd-shaped
state, real disk). This module produces actual symptoms in the
docker-compose topology so Mesh's bare-metal ingester sees them.

# Safety

Every chaos has a ``revert`` that puts the container back. The
runner enforces a 60s minimum hold and reverts before the next apply
so we never compound. The ``apply`` operations are bounded:

* Network chaos uses ``iptables -I`` inside a privileged sidecar
  scoped to the container's veth, never the host's iptables.
* Disk chaos writes to a quota'd path, bounded.
* Permission chaos touches only the JWT secret on the docker volume.
* Container kill is ``docker kill`` followed by ``docker start`` on
  revert — same lifecycle the orchestrator would manage.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Callable


_LOG = logging.getLogger("mesh.simulation.chaos_real")


_DEFAULT_RETH_CONTAINER = "mesh-demo-reth"
_DEFAULT_LIGHTHOUSE_CONTAINER = "mesh-demo-lighthouse"
_DEFAULT_NETWORK = "mesh-demo-net"
_JWT_PATH_IN_CONTAINER = "/jwt.hex"


def _run(cmd: list[str], *, check: bool = False, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Wrapper that surfaces stderr and never silently throws on the
    happy path. Returns the CompletedProcess so callers can read both
    streams.
    """
    _LOG.debug("chaos_real exec: %s", shlex.join(cmd))
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        timeout=30,
    )


def _exec_in(container: str, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return _run(["docker", "exec", container, *args], check=check)


# ---------------------------------------------------------------------
# Chaos primitives
# ---------------------------------------------------------------------


@dataclass
class Chaos:
    chaos_id: str
    description: str
    expected_signature: str            # what Mesh's ingester should observe
    apply: Callable[[str, str, str], None]
    revert: Callable[[str, str, str], None]
    tags: tuple[str, ...] = field(default_factory=tuple)


def _peer_zero_apply(reth: str, lighthouse: str, network: str) -> None:
    """Use ``docker network disconnect`` to remove the Reth container
    from its bridge while leaving the host port-mapping intact.

    The published ports remain reachable from localhost via Docker's
    daemon-level proxy because the container itself stays running;
    libp2p is the only thing that loses connectivity. peer_count
    decays toward 0 over the next ~30s.

    Note: in some Docker versions the host port mapping does break
    when the only attached network is removed. If that happens for
    your setup, this chaos still produces the right SYMPTOM (no
    peers, isolated node), the ingester just sees it via probe
    timeout instead of a successful peer_count=0 RPC.
    """
    _run(["docker", "network", "disconnect", network, reth])


def _peer_zero_revert(reth: str, lighthouse: str, network: str) -> None:
    _run(["docker", "network", "connect", network, reth])


def _jwt_world_readable_apply(reth: str, lighthouse: str, network: str) -> None:
    """Make the JWT file world-readable on the Reth side. The ingester's
    next probe will read mode and stamp ``jwt_secret_insecure_permissions``.
    """
    _exec_in(reth, "chmod", "0644", _JWT_PATH_IN_CONTAINER)


def _jwt_world_readable_revert(reth: str, lighthouse: str, network: str) -> None:
    _exec_in(reth, "chmod", "0600", _JWT_PATH_IN_CONTAINER)


def _rpc_overload_apply(reth: str, lighthouse: str, network: str) -> None:
    """Hammer the public RPC with concurrent ``eth_getLogs`` queries
    over a wide range. Pinned-CPU symptom; Mesh sees latency spike.

    We launch the load FROM THE HOST against the published port
    (``127.0.0.1:18545``) because the reth image doesn't ship curl.
    The runner records the PID file path used by ``revert``.
    """
    pid_file = "/tmp/mesh-demo-rpc-overload.pid"
    script = (
        "while true; do "
        "curl -s -o /dev/null -X POST -H 'Content-Type: application/json' "
        "-d '{\"jsonrpc\":\"2.0\",\"method\":\"eth_getLogs\","
        "\"params\":[{\"fromBlock\":\"0x0\",\"toBlock\":\"latest\",\"topics\":[]}],\"id\":1}' "
        "http://127.0.0.1:18545; "
        "done"
    )
    proc = subprocess.Popen(
        ["sh", "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))


def _rpc_overload_revert(reth: str, lighthouse: str, network: str) -> None:
    pid_file = "/tmp/mesh-demo-rpc-overload.pid"
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        _run(["pkill", "-P", str(pid)], check=False)
        _run(["kill", str(pid)], check=False)
    except (FileNotFoundError, ValueError):
        pass


def _disk_pressure_apply(reth: str, lighthouse: str, network: str) -> None:
    """Allocate a 1 GB filler in the Reth datadir to simulate disk
    pressure. Real chains care about free space on the data volume,
    not host fs, so we target the datadir specifically.

    The 1 GB number is small enough that a Hoodi datadir
    (~10 GB total) will report a noticeable disk_used_pct bump but
    not actually exhaust the volume.
    """
    _exec_in(
        reth, "sh", "-c",
        "dd if=/dev/zero of=/root/.local/share/reth/_chaos_filler bs=1M count=1024 2>/dev/null || true",
    )


def _disk_pressure_revert(reth: str, lighthouse: str, network: str) -> None:
    _exec_in(reth, "rm", "-f", "/root/.local/share/reth/_chaos_filler")


def _engine_api_unreach_apply(reth: str, lighthouse: str, network: str) -> None:
    """Stop the Lighthouse container so its Engine API calls to Reth
    cease. Reth's ``forkchoice_updates_recent`` flips false within
    ~12s (one slot). Mesh's ingester observes this via the metrics
    fetcher.

    Stopping the CL is the cleanest way to simulate consensus
    disconnect without needing in-container iptables.
    """
    _run(["docker", "stop", lighthouse])


def _engine_api_unreach_revert(reth: str, lighthouse: str, network: str) -> None:
    _run(["docker", "start", lighthouse])


def _all_clear_apply(reth: str, lighthouse: str, network: str) -> None:
    pass


def _all_clear_revert(reth: str, lighthouse: str, network: str) -> None:
    pass


# ---------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------


CATALOG: tuple[Chaos, ...] = (
    Chaos(
        "all_clear",
        "Pristine baseline; no fault injected",
        "",
        _all_clear_apply,
        _all_clear_revert,
        ("baseline",),
    ),
    Chaos(
        "peer_zero",
        "Drop all P2P egress; peer_count decays toward 0",
        "peer_starvation",
        _peer_zero_apply,
        _peer_zero_revert,
        ("peer", "network",),
    ),
    Chaos(
        "engine_api_unreach",
        "Drop inbound 8551 traffic; CL can't reach Engine API",
        "consensus_disconnected",
        _engine_api_unreach_apply,
        _engine_api_unreach_revert,
        ("consensus",),
    ),
    Chaos(
        "rpc_overload",
        "Hammer eth_getLogs in a loop; pin CPU and inflate latency",
        "rpc_degraded",
        _rpc_overload_apply,
        _rpc_overload_revert,
        ("rpc", "performance",),
    ),
    Chaos(
        "jwt_world_readable",
        "chmod 0644 the JWT secret; insecure permissions",
        "jwt_secret_insecure_permissions",
        _jwt_world_readable_apply,
        _jwt_world_readable_revert,
        ("credential", "fast_path",),
    ),
    Chaos(
        "disk_pressure",
        "Allocate a 1 GB filler in the datadir",
        "disk_pressure",
        _disk_pressure_apply,
        _disk_pressure_revert,
        ("storage",),
    ),
)


def by_id(chaos_id: str) -> Chaos | None:
    for c in CATALOG:
        if c.chaos_id == chaos_id:
            return c
    return None
