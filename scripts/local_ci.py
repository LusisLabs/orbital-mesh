#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "mesh.local_ci_manifest.v1"
DEFAULT_OUTPUT_ROOT = Path("dist/local-ci")
LOCAL_RUNTIME_RELEASE_PROVENANCE_PATH = "/app/.mesh-runtime-state/release-provenance.json"


def main() -> int:
    raw_args = [arg for arg in sys.argv[1:] if arg != "--"]
    args = _parser().parse_args(raw_args)
    manifest = run_local_ci(args)
    output_path = Path(manifest["manifest_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(f"{manifest['status']}: {output_path}")
    return 0 if manifest["status"] == "pass" else 1


def run_local_ci(args: argparse.Namespace) -> dict[str, Any]:
    head = _git_head()
    short_head = head[:7] if head else "unknown"
    output_dir = (REPO_ROOT / args.output_root / short_head).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    image_tag = args.image_tag or f"orbital-mesh:local-{short_head}"
    build_command = (
        f"docker build --build-arg MESH_BUILD_VERSION=local-{short_head} "
        f"--build-arg MESH_BUILD_COMMIT={head} -t {image_tag} ."
    )
    context: dict[str, Any] = {
        "head": head,
        "short_head": short_head,
        "output_dir": str(output_dir),
        "logs_dir": str(logs_dir),
        "image_tag": image_tag,
        "build_command": build_command,
        "docker_available": bool(shutil.which("docker")),
        "syft_available": bool(shutil.which(args.syft_bin)),
        "grype_available": bool(shutil.which(args.grype_bin)),
        "migration_database_url_present": bool(os.getenv("MESH_MIGRATION_REHEARSAL_DATABASE_URL")),
    }
    steps = _planned_steps(args, context)
    executed: list[dict[str, Any]] = []
    for step in steps:
        if args.dry_run:
            executed.append(_dry_step(step, output_dir))
            continue
        executed.append(_execute_step(step, output_dir, logs_dir, context))

    acceptable_statuses = {"pass", "skipped", "planned"} if args.dry_run else {"pass", "skipped"}
    checks = {
        "all_required_steps_passed": all(step["status"] in acceptable_statuses for step in executed),
        "no_failed_required_steps": not any(step["status"] == "fail" for step in executed if step.get("required", True)),
        "local_only_attestation": True,
        "github_actions_attestation": False,
        "production_release_authority": False,
    }
    failed_required = [step["name"] for step in executed if step["status"] == "fail" and step.get("required", True)]
    skipped_required = [step["name"] for step in executed if step["status"] == "skipped" and step.get("required", True)]
    status = "pass" if not failed_required and not skipped_required else "fail"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _timestamp(),
        "status": status,
        "mode": args.mode,
        "head": head,
        "branch": _git_branch(),
        "local_only": True,
        "authority_boundary": (
            "Local CI evidence is developer/operator evidence only. It does not replace "
            "GitHub Actions-backed release artifacts required by production release gates."
        ),
        "checks": checks,
        "missing": failed_required + skipped_required,
        "context": context,
        "steps": executed,
        "manifest_path": str(output_dir / "manifest.json"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the repo-owned local CI/CD ladder.")
    parser.add_argument("--mode", choices=("fast", "full", "release"), default="full")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--image-tag", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Emit the planned manifest without executing commands.")
    parser.add_argument("--skip-scanners", action="store_true", help="Skip Syft/Grype release-image assurance.")
    parser.add_argument("--skip-migration", action="store_true", help="Skip Postgres migration rehearsal.")
    parser.add_argument("--skip-runtime-smoke", action="store_true", help="Skip local container health smoke.")
    parser.add_argument("--syft-bin", default="syft")
    parser.add_argument("--grype-bin", default="grype")
    parser.add_argument("--policy-signing-key", default=os.getenv("MESH_POLICY_SIGNING_KEY") or "local-ci-policy-key")
    return parser


def _planned_steps(args: argparse.Namespace, context: dict[str, Any]) -> list[dict[str, Any]]:
    if args.mode == "fast":
        return [
            _command_step("lint-fast", ["corepack", "pnpm", "run", "lint:fast"]),
        ]
    if args.mode == "full":
        return [
            _command_step("heavy-root-gate", ["corepack", "pnpm", "run", "lint"]),
            _command_step("git-diff-check", ["git", "diff", "--check"]),
        ]

    output_dir = Path(context["output_dir"])
    image_tag = context["image_tag"]
    head = context["head"]
    release_assurance_dir = output_dir / "release-assurance"
    release_assurance_raw_dir = output_dir / "release-assurance-raw"
    release_metadata = output_dir / "release-image-metadata.json"
    base_image_args = output_dir / "base-image-digest.args"
    migration_rehearsal = output_dir / "migration-rehearsal.json"
    ci_attestation = output_dir / "local-ci-attestation.json"
    release_provenance = output_dir / "release-provenance-local-rehearsal.json"
    steps = [
        _command_step("heavy-root-gate", ["corepack", "pnpm", "run", "lint"]),
        _command_step(
            "docker-build",
            [
                "docker",
                "build",
                "--build-arg",
                f"MESH_BUILD_VERSION=local-{context['short_head']}",
                "--build-arg",
                f"MESH_BUILD_COMMIT={head}",
                "-t",
                image_tag,
                ".",
            ],
            precondition=context["docker_available"],
            skip_reason="docker binary missing",
        ),
        _command_step(
            "release-image-metadata",
            [
                sys.executable,
                "scripts/collect_release_image_metadata.py",
                "--image-tag",
                image_tag,
                "--output",
                str(release_metadata),
                "--base-image-args",
                str(base_image_args),
            ],
            precondition=context["docker_available"],
            skip_reason="docker binary missing",
        ),
    ]
    if not args.skip_runtime_smoke:
        steps.append(_local_runtime_smoke_step(image_tag, head))
    if args.skip_migration:
        steps.append(_skipped_step("postgres-migration-rehearsal", "disabled by --skip-migration", required=False))
    elif context["migration_database_url_present"]:
        steps.append(
            _command_step(
                "postgres-migration-rehearsal",
                [
                    sys.executable,
                    "scripts/run_postgres_migration_rehearsal.py",
                    "--output",
                    str(migration_rehearsal),
                    "--operator-id",
                    "local-ci",
                    "--environment",
                    "local-ci",
                    "--rehearsal-id",
                    f"local-ci-{context['short_head']}",
                    "--json",
                ],
            )
        )
    else:
        steps.append(
            _skipped_step(
                "postgres-migration-rehearsal",
                "MESH_MIGRATION_REHEARSAL_DATABASE_URL is not set",
                required=False,
            )
        )
    if args.skip_scanners:
        steps.append(_skipped_step("release-image-assurance", "disabled by --skip-scanners", required=False))
    else:
        steps.append(
            _command_step(
                "release-image-assurance",
                [
                    sys.executable,
                    "scripts/generate_release_image_assurance.py",
                    "--image-tag",
                    image_tag,
                    "--image-digest",
                    "<from-release-image-metadata>",
                    "--raw-output-dir",
                    str(release_assurance_raw_dir),
                    "--output-dir",
                    str(release_assurance_dir),
                    "--exception-policy",
                    "config/release-vulnerability-exceptions.json",
                ],
                runner="release_image_assurance",
                precondition=context["syft_available"] and context["grype_available"],
                skip_reason="syft or grype binary missing",
                extra={
                    "raw_output_dir": str(release_assurance_raw_dir),
                    "output_dir": str(release_assurance_dir),
                    "syft_bin": args.syft_bin,
                    "grype_bin": args.grype_bin,
                },
            )
        )
    steps.extend(
        [
            _command_step(
                "local-ci-attestation",
                [
                    sys.executable,
                    "scripts/generate_ci_attestation.py",
                    "--output",
                    str(ci_attestation),
                    "--check",
                    "python-test",
                    "--check",
                    "web",
                    "--check",
                    "docker-build",
                    "--image-tag",
                    image_tag,
                    "--source-sha",
                    head,
                    "--build-command",
                    context["build_command"],
                ],
                runner="local_ci_attestation",
                extra={"metadata_path": str(release_metadata), "base_image_args_path": str(base_image_args)},
            ),
            _command_step(
                "release-provenance-local-rehearsal",
                [
                    sys.executable,
                    "scripts/generate_release_provenance.py",
                    "--output",
                    str(release_provenance),
                    "--json",
                    "--allow-dirty",
                    "--image-tag",
                    image_tag,
                    "--ci-attestation",
                    str(ci_attestation),
                    "--build-command",
                    context["build_command"],
                    "--policy-signing-key",
                    args.policy_signing_key,
                ],
                runner="release_provenance",
                extra={
                    "metadata_path": str(release_metadata),
                    "base_image_args_path": str(base_image_args),
                    "migration_rehearsal": str(migration_rehearsal),
                    "sbom": str(release_assurance_dir / "sbom.cdx.json"),
                    "vulnerability_scan": str(release_assurance_dir / "vulnerability-scan.json"),
                },
            ),
            _command_step("git-diff-check", ["git", "diff", "--check"]),
        ]
    )
    return steps


def _command_step(
    name: str,
    command: list[str],
    *,
    required: bool = True,
    precondition: bool = True,
    skip_reason: str = "",
    runner: str = "command",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "command": command,
        "required": required,
        "precondition": precondition,
        "skip_reason": skip_reason,
        "runner": runner,
        "extra": extra or {},
    }


def _skipped_step(name: str, reason: str, *, required: bool) -> dict[str, Any]:
    return _command_step(name, [], required=required, precondition=False, skip_reason=reason)


def _local_runtime_smoke_step(image_tag: str, head: str) -> dict[str, Any]:
    return _command_step(
        "local-runtime-health-smoke",
        [],
        runner="local_runtime_smoke",
        extra={"image_tag": image_tag, "head": head},
    )


def _dry_step(step: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    return {
        "name": step["name"],
        "status": "planned" if step.get("precondition", True) else "skipped",
        "required": step.get("required", True),
        "command": step.get("command", []),
        "skip_reason": step.get("skip_reason") if not step.get("precondition", True) else None,
        "log": str(output_dir / "logs" / f"{step['name']}.log"),
    }


def _execute_step(step: dict[str, Any], output_dir: Path, logs_dir: Path, context: dict[str, Any]) -> dict[str, Any]:
    if not step.get("precondition", True):
        return {
            "name": step["name"],
            "status": "skipped",
            "required": step.get("required", True),
            "command": step.get("command", []),
            "skip_reason": step.get("skip_reason") or "precondition failed",
            "duration_seconds": 0.0,
        }
    runner = step.get("runner", "command")
    if runner == "local_runtime_smoke":
        return _run_local_runtime_smoke(step, logs_dir)
    if runner == "release_image_assurance":
        step = _with_release_assurance_command(step)
    if runner == "local_ci_attestation":
        step = _with_attestation_command(step)
    if runner == "release_provenance":
        step = _with_release_provenance_command(step)
    return _run_command_step(step, logs_dir, context)


def _run_command_step(step: dict[str, Any], logs_dir: Path, context: dict[str, Any]) -> dict[str, Any]:
    start = time.time()
    log_path = logs_dir / f"{step['name']}.log"
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(step["command"]) + "\n")
        log.flush()
        completed = subprocess.run(
            step["command"],
            cwd=REPO_ROOT,
            check=False,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "MESH_CI_PROVIDER": "local", "MESH_LOCAL_CI_HEAD": context["head"]},
        )
    return {
        "name": step["name"],
        "status": "pass" if completed.returncode == 0 else "fail",
        "required": step.get("required", True),
        "command": step["command"],
        "returncode": completed.returncode,
        "duration_seconds": round(time.time() - start, 3),
        "log": str(log_path),
    }


def _with_release_assurance_command(step: dict[str, Any]) -> dict[str, Any]:
    metadata = _read_json(Path(step["extra"]["metadata_path"]))
    image_digest = str(metadata.get("image", {}).get("digest") or "")
    command = [
        sys.executable,
        "scripts/generate_release_image_assurance.py",
        "--image-tag",
        step["command"][step["command"].index("--image-tag") + 1],
        "--image-digest",
        image_digest,
        "--raw-output-dir",
        step["extra"]["raw_output_dir"],
        "--output-dir",
        step["extra"]["output_dir"],
        "--syft-bin",
        step["extra"]["syft_bin"],
        "--grype-bin",
        step["extra"]["grype_bin"],
        "--exception-policy",
        "config/release-vulnerability-exceptions.json",
    ]
    return {**step, "command": command}


def _with_attestation_command(step: dict[str, Any]) -> dict[str, Any]:
    command = list(step["command"])
    metadata_path = Path(step["extra"]["metadata_path"])
    base_args_path = Path(step["extra"]["base_image_args_path"])
    if metadata_path.is_file():
        image_digest = str(_read_json(metadata_path).get("image", {}).get("digest") or "")
        if image_digest:
            command.extend(["--image-digest", image_digest])
    if base_args_path.is_file():
        command.extend(base_args_path.read_text(encoding="utf-8").splitlines())
    return {**step, "command": command}


def _with_release_provenance_command(step: dict[str, Any]) -> dict[str, Any]:
    command = list(step["command"])
    metadata_path = Path(step["extra"]["metadata_path"])
    base_args_path = Path(step["extra"]["base_image_args_path"])
    if metadata_path.is_file():
        image_digest = str(_read_json(metadata_path).get("image", {}).get("digest") or "")
        if image_digest:
            command.extend(["--image-digest", image_digest])
    if base_args_path.is_file():
        command.extend(base_args_path.read_text(encoding="utf-8").splitlines())
    for flag, key in (
        ("--migration-rehearsal", "migration_rehearsal"),
        ("--sbom", "sbom"),
        ("--vulnerability-scan", "vulnerability_scan"),
    ):
        path = Path(step["extra"][key])
        if path.is_file():
            command.extend([flag, str(path)])
    return {**step, "command": command}


def _run_local_runtime_smoke(step: dict[str, Any], logs_dir: Path) -> dict[str, Any]:
    start = time.time()
    image_tag = step["extra"]["image_tag"]
    head = step["extra"]["head"]
    name = f"mesh-local-ci-{head[:7]}"
    log_path = logs_dir / f"{step['name']}.log"
    with log_path.open("w", encoding="utf-8") as log:
        def run(command: list[str]) -> subprocess.CompletedProcess[str]:
            log.write("$ " + " ".join(command) + "\n")
            log.flush()
            return subprocess.run(command, cwd=REPO_ROOT, check=False, stdout=log, stderr=subprocess.STDOUT, text=True)

        run(["docker", "rm", "-f", name])
        completed = run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-e",
                "MESH_SERVER_HOST=0.0.0.0",
                "-e",
                "MESH_SERVER_PORT=8787",
                "-e",
                "MESH_ENVIRONMENT=local-ci",
                "-e",
                f"MESH_BUILD_COMMIT={head}",
                "-e",
                "MESH_GITNEXUS_DISABLE_AUTOSTART=1",
                "-p",
                "127.0.0.1::8787",
                image_tag,
            ]
        )
        if completed.returncode != 0:
            return _smoke_result(step, log_path, start, 1, name)
        port = _container_port(name)
        status = 1
        if port:
            for _ in range(30):
                try:
                    with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    log.write(json.dumps(payload, sort_keys=True) + "\n")
                    if payload.get("status") == "ok" and payload.get("commit") == head:
                        status = 0
                        break
                except (OSError, URLError, json.JSONDecodeError):
                    time.sleep(1)
        run(["docker", "logs", name])
        run(["docker", "rm", "-f", name])
    return _smoke_result(step, log_path, start, status, name)


def _smoke_result(step: dict[str, Any], log_path: Path, start: float, returncode: int, container_name: str) -> dict[str, Any]:
    return {
        "name": step["name"],
        "status": "pass" if returncode == 0 else "fail",
        "required": step.get("required", True),
        "command": ["docker", "run", container_name],
        "returncode": returncode,
        "duration_seconds": round(time.time() - start, 3),
        "log": str(log_path),
    }


def _container_port(name: str) -> str:
    completed = subprocess.run(
        ["docker", "port", name, "8787/tcp"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    value = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
    return value.rsplit(":", 1)[-1] if ":" in value else ""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _git_head() -> str:
    return _git(["rev-parse", "--verify", "HEAD"])


def _git_branch() -> str:
    return _git(["branch", "--show-current"])


def _git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
