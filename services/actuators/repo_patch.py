"""Bounded local repo patch executor for investigate-and-patch actions."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


class RepoPatchAdapter:
    def execute_patch(self, parameters: dict, idempotency_key: str) -> dict:
        repo_path = Path(parameters["repo_path"]).resolve()
        allowed_paths = {str(Path(path)) for path in parameters.get("allowed_paths", [])}
        patch_template = parameters.get("patch_template", {})
        raw_target_file = Path(patch_template["target_file"])
        target_path = raw_target_file.resolve() if raw_target_file.is_absolute() else (repo_path / raw_target_file).resolve()
        if not str(target_path).startswith(str(repo_path)):
            return {
                "status": "failed",
                "external_refs": {},
                "failure": {"reason": "target file escapes repo scope"},
                "retryable": False,
            }
        target_file = target_path.relative_to(repo_path)
        if str(target_file) not in allowed_paths:
            return {
                "status": "failed",
                "external_refs": {},
                "failure": {"reason": "target file falls outside allowed patch scope"},
                "retryable": False,
            }
        if not target_path.exists():
            return {
                "status": "failed",
                "external_refs": {},
                "failure": {"reason": "target file does not exist"},
                "retryable": False,
            }

        original = target_path.read_text()
        find_text = patch_template["find"]
        replace_text = patch_template["replace"]
        if find_text not in original:
            return {
                "status": "failed",
                "external_refs": {},
                "failure": {"reason": "patch anchor not found in target file"},
                "retryable": False,
            }

        updated = original.replace(find_text, replace_text, 1)
        backup_dir = repo_path / ".mesh-patch-backups"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"{idempotency_key.replace(':', '_')}.bak"
        backup_path.write_text(original)
        target_path.write_text(updated)

        test_results: list[dict[str, object]] = []
        for command in parameters.get("test_commands", []):
            completed = self._run_test_command(str(command), repo_path)
            test_result = {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
            test_results.append(test_result)
            if completed.returncode != 0:
                target_path.write_text(original)
                return {
                    "status": "failed",
                    "external_refs": {
                        "backup_path": str(backup_path),
                        "patched_files": [str(target_file)],
                        "test_results": test_results,
                    },
                    "failure": {"reason": "bounded verification failed"},
                    "retryable": False,
                }

        return {
            "status": "succeeded",
            "external_refs": {
                "backup_path": str(backup_path),
                "patched_files": [str(target_file)],
                "test_results": test_results,
            },
            "retryable": False,
        }

    def _run_test_command(self, command: str, repo_path: Path) -> subprocess.CompletedProcess[str]:
        if self._uses_shell_syntax(command):
            return subprocess.run(
                command,
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                shell=True,
                executable="/bin/sh",
            )
        return subprocess.run(
            shlex.split(command),
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def _uses_shell_syntax(self, command: str) -> bool:
        stripped = command.strip()
        return stripped.startswith("cd ") or any(token in command for token in ("&&", "||", ";", "|", ">", "<", "$("))
