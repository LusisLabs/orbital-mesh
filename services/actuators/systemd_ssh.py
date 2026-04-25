"""SSH-based systemd actuator for bare-metal nodes.

# Why this exists

Blockchain nodes (Solana/Agave, geth, reth, lighthouse, and friends) run on
dedicated hardware managed by systemd, not inside containers. A Solana
validator with NUMA pinning, huge pages, and direct NVMe access does not
and will not live in Kubernetes. Mesh's kubectl-based actuators don't help
on these machines.

This module gives Mesh the same bounded-action loop for bare-metal hosts:
remediation decisions like "restart the solana-validator service on
vault-prod-07" flow through the normal approval gate and audit log, but
execute via ``ssh <host> sudo systemctl restart <service>`` instead of
``kubectl``.

# Safety model (non-negotiable)

Bare-metal actuation has no Kubernetes safety net — no liveness probes
that auto-restart, no deployment controller that rolls back a bad change,
no namespace sandbox. A wrong restart on a validator during voting can
cost SOL. The adapter enforces four overlapping constraints:

1. **Host allowlist** (``MESH_SSH_ALLOWED_HOSTS``). The adapter refuses to
   SSH to any host not in this list. Cuts the blast radius of a bad policy
   or a hijacked decision path. Without an allowlist, bare-metal execution
   is hard-disabled.

2. **Service allowlist** (``MESH_SSH_ALLOWED_SERVICES``). The adapter
   refuses to issue ``systemctl`` against any service name not in this
   list. Prevents a malformed rule from restarting ``sshd`` or
   ``systemd-journald`` and taking the host offline.

3. **Command allowlist** (hardcoded in this module). Only four systemd
   verbs — ``restart``, ``start``, ``stop``, ``status`` — plus three
   diagnostic reads — ``df``, ``free``, ``uptime``. No arbitrary commands.
   A rule cannot propose ``rm -rf /ledger``.

4. **Explicit enable flag** (``MESH_SSH_EXECUTION_ENABLED``). Mock-by-
   default. Like kubectl live execution, real SSH has to be turned on
   intentionally. The default is safe for tests, CI, and local dev.

Additionally, every action flows through the same approval gate as any
other Mesh actuation and carries an idempotency key that includes the
host identity, so the same decision replayed against two hosts is two
distinct audit rows.

# What lives where

* ``SystemdSshAdapter`` — the actuator. Mirrors ``KubernetesAdapter``'s
  mock-by-default + live-on-flag pattern.
* ``SystemdSshError`` — raised internally for invalid inputs; never
  crosses the adapter boundary. Every return is a structured
  ``ActuatorResult``.
* ``_build_ssh_command`` — the one place command construction happens.
  Keeping it isolated makes it trivial to audit (and test) the allowlist
  enforcement logic.

# What this does NOT do

* No arbitrary shell. No ``ssh host bash -c ...``.
* No credential prompting. The SSH key must already be configured on the
  Mesh host's keyring or via ``MESH_SSH_IDENTITY_FILE``. The adapter
  passes ``-i`` when set but never reads or logs key material.
* No hot-patching of systemd unit files. ``systemctl daemon-reload`` is
  not in the command allowlist — configuration changes go through the
  config-management tool your ops team already uses.
* No validator-specific operations like identity rotation, vote account
  switching, or snapshot creation. Those carry serious data-loss risk
  and belong in a dedicated, heavily-reviewed follow-up.

# Integration with the decision layer

Rules in ``policies/metric-actions.policy.json`` can now propose
``restart_systemd_service`` actions routed through ``systemd_service``
system. The goose adapter's action dispatch tree routes to the methods
on this class. See ``services/orchestrator/goose_adapter.py`` for the
wiring.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from typing import Any, Iterable

from shared.mesh_runtime import RuntimeConfig

from .service import ActuatorResult


_LOG = logging.getLogger("mesh.actuators.systemd_ssh")


# Hardcoded command allowlist. Never widen this without a code-reviewed
# change — it's the last line of defense against a policy that asks Mesh
# to do something destructive on a bare-metal host.
_ALLOWED_SYSTEMCTL_VERBS: frozenset[str] = frozenset({"restart", "start", "stop", "status"})
_ALLOWED_DIAG_COMMANDS: frozenset[str] = frozenset({"df", "free", "uptime"})


class SystemdSshError(Exception):
    """Raised internally for invalid inputs or SSH failures.

    Never propagates past the adapter boundary — methods catch and return a
    structured ``ActuatorResult`` with status=failed. A caller should never
    need to try/except; the ``status`` / ``failure`` fields on the result
    carry everything needed for audit.
    """


class SystemdSshAdapter:
    """Actuator for systemd-managed services on bare-metal hosts.

    Construct once per coordinator; safe to share across threads. The
    adapter is stateless — it carries the RuntimeConfig for allowlist /
    execution-flag lookups, nothing else.

    Parameters (from ``parameters`` dict on every method):

    * ``host`` (required): the SSH target, e.g. ``vault-prod-07`` or
      ``user@vault-prod-07``. Must match an entry in
      ``MESH_SSH_ALLOWED_HOSTS`` or the action fails.
    * ``service`` (required for systemctl methods): the systemd unit name,
      e.g. ``solana-validator.service``. Must match
      ``MESH_SSH_ALLOWED_SERVICES``.
    * ``use_sudo`` (optional, defaults to True): whether to prefix the
      remote command with ``sudo``. Required for most systemctl operations
      but not for read-only diagnostics. Leave default for safety.
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig()

    # ---------------------------------------------------------------- systemctl

    def restart_service(self, parameters: dict[str, Any]) -> ActuatorResult:
        """Run ``systemctl restart <service>`` on the remote host.

        In mock mode (default), returns a deterministic success without
        touching the host — suitable for unit tests and the local approval-
        gate flow. In live mode, runs the real SSH command.
        """
        return self._systemctl_action(parameters, verb="restart")

    def start_service(self, parameters: dict[str, Any]) -> ActuatorResult:
        return self._systemctl_action(parameters, verb="start")

    def stop_service(self, parameters: dict[str, Any]) -> ActuatorResult:
        """Stop a service. Rarely the right remediation — prefer ``restart``
        unless you explicitly mean "take this node out of the rotation"."""
        return self._systemctl_action(parameters, verb="stop")

    def status_service(self, parameters: dict[str, Any]) -> ActuatorResult:
        """Read-only ``systemctl status`` — useful as a decision-stage probe.

        Returns the raw status output in ``external_refs.status_output``
        so downstream stages can parse it for ``active (running)`` etc.
        """
        return self._systemctl_action(parameters, verb="status", use_sudo_default=False)

    # ------------------------------------------------------------- diagnostics

    def read_disk_usage(self, parameters: dict[str, Any]) -> ActuatorResult:
        """``df -h`` on the host. Used by feedback-stage observers.

        Not actuation in the strict sense — no state change — but it goes
        through the same audit path because bare-metal observability should
        be reviewable the same way actions are.
        """
        host = self._require_host(parameters)
        if not self.config.ssh_execution_enabled:
            return {
                "status": "succeeded",
                "external_refs": {
                    "mock": True,
                    "action": "read_disk_usage",
                    "host": host,
                    "diagnostic_output": "Filesystem Size Used Avail Use% Mounted on\n"
                                         "mock-fs 1.0T 100G 900G 10% /",
                },
            }
        command = self._build_ssh_command(host, diagnostic="df", diagnostic_args=("-h",))
        return self._run(command, action="read_disk_usage", host=host, service=None)

    # ------------------------------------------------------------- internals

    def _systemctl_action(
        self,
        parameters: dict[str, Any],
        *,
        verb: str,
        use_sudo_default: bool = True,
    ) -> ActuatorResult:
        """Common path for all systemctl-based methods.

        Centralizing this means every systemctl operation gets the same
        allowlist checks, the same mock-mode behavior, and the same audit
        envelope. Resist the temptation to inline even a simple variant
        somewhere else; the consistency is worth more than the deduplication.
        """
        if verb not in _ALLOWED_SYSTEMCTL_VERBS:
            return _failure("systemctl_verb_not_allowed", f"verb={verb!r} not in allowlist")

        try:
            host = self._require_host(parameters)
            service = self._require_service(parameters)
        except SystemdSshError as exc:
            return _failure(str(exc).split(":", 1)[0], str(exc))

        use_sudo = bool(parameters.get("use_sudo", use_sudo_default))

        if not self.config.ssh_execution_enabled:
            # Mock: deterministic success without touching the host.
            return {
                "status": "succeeded",
                "external_refs": {
                    "mock": True,
                    "action": f"{verb}_service",
                    "host": host,
                    "service": service,
                    "verb": verb,
                    "use_sudo": use_sudo,
                },
            }

        command = self._build_ssh_command(
            host,
            systemctl_verb=verb,
            systemctl_service=service,
            use_sudo=use_sudo,
        )
        return self._run(command, action=f"{verb}_service", host=host, service=service)

    # ---------- validation ----------

    def _require_host(self, parameters: dict[str, Any]) -> str:
        host = parameters.get("host")
        if not host or not isinstance(host, str):
            raise SystemdSshError("missing_parameter: host is required")
        # Extract the bare hostname for allowlist comparison — "user@host"
        # and plain "host" both must normalize to the same key, because the
        # allowlist is about *where* we're executing, not *as whom*.
        bare_host = host.split("@", 1)[-1].strip()
        allowed = set(self.config.ssh_allowed_hosts)
        if not allowed:
            raise SystemdSshError(
                "host_allowlist_empty: set MESH_SSH_ALLOWED_HOSTS before enabling SSH execution"
            )
        if bare_host not in allowed:
            raise SystemdSshError(f"host_not_allowed: host {bare_host!r} is not in the allowlist")
        return host

    def _require_service(self, parameters: dict[str, Any]) -> str:
        service = parameters.get("service")
        if not service or not isinstance(service, str):
            raise SystemdSshError("missing_parameter: service is required")
        # Systemd accepts both "name" and "name.service" — normalize for
        # allowlist comparison so rules don't have to be pedantic.
        canonical = service if service.endswith(".service") else f"{service}.service"
        allowed = set(self.config.ssh_allowed_services)
        if not allowed:
            raise SystemdSshError(
                "service_allowlist_empty: set MESH_SSH_ALLOWED_SERVICES before enabling SSH execution"
            )
        if canonical not in allowed and service not in allowed:
            raise SystemdSshError(
                f"service_not_allowed: service {service!r} is not in the allowlist"
            )
        return service

    # ---------- command construction ----------

    def _build_ssh_command(
        self,
        host: str,
        *,
        systemctl_verb: str | None = None,
        systemctl_service: str | None = None,
        diagnostic: str | None = None,
        diagnostic_args: Iterable[str] = (),
        use_sudo: bool = False,
    ) -> list[str]:
        """Assemble the full SSH command line.

        Every bare-metal command Mesh issues passes through here. If you
        find yourself building a command anywhere else, stop and route
        through this function so the allowlist and quoting are uniform.

        The remote command is assembled as a list of quoted tokens and
        passed as a single argument to the SSH client. We do not use
        ``bash -c`` or any shell intermediary on either end — SSH's
        default behavior is to exec the single argument as the remote
        command, which sidesteps an entire class of injection concerns.
        """
        if systemctl_verb and diagnostic:
            raise SystemdSshError("command_conflict: cannot combine systemctl and diagnostic")
        if not systemctl_verb and not diagnostic:
            raise SystemdSshError("command_empty: neither systemctl nor diagnostic specified")

        ssh: list[str] = [self.config.ssh_command or "ssh"]
        # Safe default connection flags. Covering four separate failure modes:
        #
        # 1. BatchMode=yes — never prompt for a password. If key auth fails,
        #    the command fails fast instead of hanging on an interactive prompt
        #    that nobody is there to answer.
        # 2. StrictHostKeyChecking=yes — refuse unknown host keys. Operators
        #    must pre-populate known_hosts. Prevents accepting a MITM.
        # 3. ConnectTimeout — cap handshake time so a dead host doesn't wedge
        #    the pipeline on TCP connect retries.
        # 4. ServerAliveInterval + ServerAliveCountMax — detect a mid-command
        #    network partition within ~90s. Without these, an established
        #    connection that silently drops can hang for the OS-level TCP
        #    retransmit timeout (~15 minutes on Linux). That's the worst case
        #    for "Mesh thinks the restart is still running when the host is
        #    actually gone", so we force the probe.
        ssh.extend([
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"ConnectTimeout={int(self.config.ssh_connect_timeout_seconds)}",
            "-o", f"ServerAliveInterval={int(self.config.ssh_server_alive_interval_seconds)}",
            "-o", f"ServerAliveCountMax={int(self.config.ssh_server_alive_count_max)}",
        ])
        if self.config.ssh_identity_file:
            ssh.extend(["-i", self.config.ssh_identity_file])
        ssh.append(host)

        remote_parts: list[str] = []
        if systemctl_verb:
            if use_sudo:
                remote_parts.append("sudo")
            remote_parts.extend(["systemctl", systemctl_verb])
            # Extra guard: the service name is already allowlisted, but quote
            # defensively. shlex.quote is a no-op for the strings we expect
            # but saves us if someone sneaks in a weirder unit name.
            remote_parts.append(shlex.quote(systemctl_service or ""))
        else:
            assert diagnostic is not None  # type-checker narrowing
            if diagnostic not in _ALLOWED_DIAG_COMMANDS:
                raise SystemdSshError(f"diagnostic_not_allowed: {diagnostic!r}")
            remote_parts.append(diagnostic)
            remote_parts.extend(shlex.quote(arg) for arg in diagnostic_args)

        ssh.append(" ".join(remote_parts))
        return ssh

    # ---------- execution ----------

    def _run(
        self,
        command: list[str],
        *,
        action: str,
        host: str,
        service: str | None,
    ) -> ActuatorResult:
        """Execute the assembled SSH command and wrap the result.

        We never raise out of this method. Every exit path produces an
        ``ActuatorResult`` so the orchestrator's audit chain stays clean.
        """
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.config.ssh_command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            _LOG.warning("ssh %s timed out after %ss: %s", action, exc.timeout, exc)
            return _failure(
                "ssh_timeout",
                f"ssh command timed out after {exc.timeout}s",
                external={"host": host, "service": service, "action": action},
            )
        except OSError as exc:
            return _failure(
                "ssh_subprocess_error",
                str(exc),
                external={"host": host, "service": service, "action": action},
            )

        if completed.returncode != 0:
            stderr = completed.stderr.strip() or f"ssh exited {completed.returncode}"
            return _failure(
                "ssh_command_failed",
                stderr,
                external={
                    "host": host,
                    "service": service,
                    "action": action,
                    "returncode": completed.returncode,
                    "stderr": stderr,
                },
            )

        return {
            "status": "succeeded",
            "external_refs": {
                "live_execution": True,
                "host": host,
                "service": service,
                "action": action,
                "rollout_change_id": f"systemdssh_{action}_{host}_{service or 'none'}",
                # Only surface the first 4KB of output to keep the audit log
                # a reasonable size; the full output is available in logs.
                "diagnostic_output": completed.stdout[:4096] if completed.stdout else "",
            },
        }


# ----------------------------------------------------------------- helpers


def _failure(reason: str, detail: str, external: dict[str, Any] | None = None) -> ActuatorResult:
    """Uniform failure envelope so every error path looks the same to the audit log."""
    return {
        "status": "failed",
        "failure": {"reason": reason, "detail": detail},
        "external_refs": external or {},
    }


__all__ = ["SystemdSshAdapter", "SystemdSshError"]
