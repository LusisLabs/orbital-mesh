"""Durable permit-enforced local repo patch transaction executor."""

from __future__ import annotations

import hashlib
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence, cast

from shared.mesh_runtime import Decision, RuntimeConfig
from shared.mesh_runtime.hsai_bridge import HSAI_EXECUTION_CONTEXT_KEY, repo_patch_admission_failure
from shared.mesh_runtime.repo_patch_permits import (
    RepoPatchPermitStore,
    atomic_replace_bytes,
    file_digest,
    repo_patch_postimage,
    repo_patch_target_binding,
    write_immutable_backup,
)


class RepoPatchAdapter:
    def __init__(
        self,
        state_directory: str | Path | None = None,
        *,
        config: RuntimeConfig | None = None,
        allowed_test_commands: Sequence[Sequence[str]] | None = None,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        resolved_config = config or RuntimeConfig.from_env()
        resolved_state_directory = state_directory or resolved_config.state_directory
        self.permit_store = RepoPatchPermitStore(
            resolved_state_directory,
            signing_key=resolved_config.repo_patch_permit_signing_key,
            signing_key_id=resolved_config.repo_patch_permit_signing_key_id,
            issuer=resolved_config.repo_patch_permit_issuer,
            executor_audience=resolved_config.repo_patch_permit_executor_audience,
        )
        configured_commands: Sequence[Sequence[str]]
        if allowed_test_commands is None:
            configured_commands = tuple(
                tuple(shlex.split(command)) for command in resolved_config.repo_patch_authority_allowed_test_commands
            )
        else:
            configured_commands = allowed_test_commands
        self.allowed_test_commands = frozenset(tuple(str(argument) for argument in command) for command in configured_commands)
        if any(not command or any(not argument for argument in command) for command in self.allowed_test_commands):
            raise ValueError("repo patch verification allowlist contains an empty command or argument")
        self.failpoint = failpoint

    def execute_patch(
        self,
        decision: Decision,
        idempotency_key: str,
        *,
        resolved_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(decision, Decision):
            return self._authority_failure("repo patch actuator requires a Decision carrying an execution permit")
        context_failure = repo_patch_admission_failure(decision)
        if context_failure is not None:
            return cast(dict[str, Any], context_failure)
        context = decision.execution_plan["parameters"].get(HSAI_EXECUTION_CONTEXT_KEY)
        permit = context.get("execution_permit") if isinstance(context, dict) else None
        if not isinstance(permit, dict):
            return self._authority_failure("repo patch execution permit is missing")
        if permit.get("idempotency_key") != idempotency_key:
            return self._authority_failure("repo patch execution permit idempotency key mismatch")

        try:
            terminal_result = self.permit_store.terminal_result_for_idempotency(idempotency_key)
        except (OSError, TypeError, ValueError) as exc:
            return self._authority_failure(f"repo patch terminal-result lookup rejected: {exc}")
        if terminal_result is not None:
            return terminal_result

        parameters = dict(resolved_parameters or decision.execution_plan["parameters"])
        try:
            repo_path, target_path, current_preimage_digest = repo_patch_target_binding(parameters)
            if permit.get("target_preimage_digest") != current_preimage_digest:
                return self._authority_failure("repo patch execution permit rejected: target preimage mismatch")
            postimage, current_postimage_digest = repo_patch_postimage(parameters, target_path)
            if permit.get("target_postimage_digest") != current_postimage_digest:
                return self._authority_failure("repo patch execution permit rejected: target postimage mismatch")
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return self._authority_failure(f"repo patch target binding rejected: {exc}")
        try:
            self.permit_store.backup_directory.relative_to(repo_path)
        except ValueError:
            pass
        else:
            return self._authority_failure("repo patch authority state must be outside the target repository")

        try:
            authorized_commands = self._authorize_test_commands(parameters.get("test_commands", []))
        except (TypeError, ValueError) as exc:
            return self._authority_failure(f"repo patch verification policy rejected: {exc}")

        try:
            original = target_path.read_bytes()
        except OSError as exc:
            return self._authority_failure(f"repo patch preflight failed: {exc}")
        if file_digest(target_path) != permit["target_preimage_digest"]:
            return self._authority_failure("repo patch execution permit rejected: target preimage changed")

        backup_name = hashlib.sha256(permit["permit_id"].encode("utf-8")).hexdigest() + ".bak"
        backup_path = self.permit_store.backup_directory / backup_name
        try:
            write_immutable_backup(backup_path, original)
            self.permit_store.record_transition(
                permit["permit_id"],
                "issued",
                "prepared",
                details={
                    "backup_path": str(backup_path),
                    "repo_path": str(repo_path),
                    "target_path": str(target_path),
                },
                failpoint=self.failpoint,
            )
        except (OSError, TypeError, ValueError) as exc:
            return self._authority_failure(f"repo patch durable preparation rejected: {exc}")

        try:
            authority_receipt = self.permit_store.consume(
                permit,
                decision,
                idempotency_key,
                parameters,
                failpoint=self.failpoint,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return self._authority_failure(f"repo patch execution permit rejected: {exc}")

        self.permit_store.record_transition(permit["permit_id"], "claimed", "applying", failpoint=self.failpoint)
        try:
            if target_path.is_symlink() or file_digest(target_path) != permit["target_preimage_digest"]:
                return self.permit_store.abort_with_restoration(
                    permit,
                    "applying",
                    "repo patch target changed after authority claim",
                    failpoint=self.failpoint,
                )
        except OSError:
            return self.permit_store.abort_with_restoration(
                permit,
                "applying",
                "repo patch target became unavailable after authority claim",
                failpoint=self.failpoint,
            )
        try:
            atomic_replace_bytes(target_path, postimage)
        except OSError as exc:
            return self.permit_store.abort_with_restoration(
                permit,
                "applying",
                f"repo patch atomic replacement failed: {exc}",
                failpoint=self.failpoint,
            )
        self.permit_store.record_transition(permit["permit_id"], "applying", "applied", failpoint=self.failpoint)
        if file_digest(target_path) != permit["target_postimage_digest"]:
            return self.permit_store.abort_with_restoration(
                permit,
                "applied",
                "repo patch target postimage verification failed",
                failpoint=self.failpoint,
            )
        self.permit_store.record_transition(permit["permit_id"], "applied", "verifying", failpoint=self.failpoint)

        test_results: list[dict[str, object]] = []
        for arguments in authorized_commands:
            command = shlex.join(arguments)
            try:
                completed = self._run_test_command(arguments, repo_path)
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                return self.permit_store.abort_with_restoration(
                    permit,
                    "verifying",
                    f"bounded verification failed: {exc}",
                    test_results=test_results,
                    failpoint=self.failpoint,
                )
            test_result = {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
            test_results.append(test_result)
            if completed.returncode != 0:
                return self.permit_store.abort_with_restoration(
                    permit,
                    "verifying",
                    "bounded verification failed",
                    test_results=test_results,
                    failpoint=self.failpoint,
                )

        try:
            target_verified = not target_path.is_symlink() and file_digest(target_path) == permit["target_postimage_digest"]
        except OSError:
            target_verified = False
        if not target_verified:
            return self.permit_store.abort_with_restoration(
                permit,
                "verifying",
                "repo patch target drifted during bounded verification",
                test_results=test_results,
                failpoint=self.failpoint,
            )
        target_file = target_path.relative_to(repo_path)
        authority_receipt["target_postimage_digest"] = file_digest(target_path)
        result = {
            "status": "succeeded",
            "external_refs": {
                "authority_receipt": authority_receipt,
                "backup_path": str(backup_path),
                "patched_files": [str(target_file)],
                "test_results": test_results,
            },
            "retryable": False,
        }
        self.permit_store.record_transition(
            permit["permit_id"],
            "verifying",
            "committed",
            details={"committed_postimage_digest": authority_receipt["target_postimage_digest"]},
            terminal_result=result,
            failpoint=self.failpoint,
        )
        return result

    def recover_incomplete_actions(self) -> list[dict[str, Any]]:
        return self.permit_store.recover_incomplete_actions(failpoint=self.failpoint)

    def _authorize_test_commands(self, commands: Any) -> tuple[tuple[str, ...], ...]:
        if not isinstance(commands, list) or any(not isinstance(command, str) for command in commands):
            raise ValueError("repo patch verification commands must be a list of strings")
        authorized: list[tuple[str, ...]] = []
        for command in commands:
            if self._uses_shell_syntax(command):
                raise ValueError("repo patch verification command contains prohibited shell syntax")
            arguments = tuple(shlex.split(command))
            if not arguments:
                raise ValueError("empty repo patch verification command")
            if arguments not in self.allowed_test_commands:
                raise ValueError("repo patch verification command is not explicitly allowlisted")
            authorized.append(arguments)
        return tuple(authorized)

    def _run_test_command(self, arguments: tuple[str, ...], repo_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            arguments,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def _uses_shell_syntax(self, command: str) -> bool:
        stripped = command.strip()
        return stripped.startswith("cd ") or any(token in command for token in ("&&", "||", ";", "|", ">", "<", "$(", "`"))

    def _authority_failure(self, reason: str) -> dict[str, Any]:
        return {
            "status": "failed",
            "external_refs": {},
            "failure": {"reason": reason},
            "retryable": False,
        }
