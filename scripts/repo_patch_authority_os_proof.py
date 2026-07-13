#!/usr/bin/env python3
"""Prove the repo-patch authority boundary with three distinct Linux UIDs."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.orchestrator.hsai_bridge_adapter import RustEvidenceV2HsaiAdmissionAdapter
from shared.mesh_runtime import Decision, EvaluationResult
from shared.mesh_runtime.hsai_bridge import (
    build_hsai_admission_request_v2,
    evaluate_hsai_gate,
)
from shared.mesh_runtime.repo_patch_authority import RepoPatchAuthorityClient


AGENT_UID = 1000
ORCHESTRATOR_UID = 2000
AUTHORITY_UID = 3000
AUTHORITY_GID = 4000
CLIENT_KEY_ID = "mesh-os-proof-client"
AUTHORITY_KEY_ID = "mesh-os-proof-authority"
HSAI_EXECUTABLE_PATH = Path("/opt/hsai/bin/hsai-mesh-admission")
POLICY_ID = "mesh_policy://repo-patch/os-boundary-proof"


def main() -> int:
    mode = os.environ.get("MESH_OS_PROOF_MODE", "root")
    if mode == "client":
        return _client_mode()
    if mode == "write_probe":
        return _write_probe()
    if mode == "socket_probe":
        return _socket_probe()
    return _root_mode()


def _root_mode() -> int:
    if os.geteuid() != 0:
        raise PermissionError("OS-boundary proof setup requires root inside the disposable container")
    root = Path("/proof")
    repo = root / "repo"
    state = root / "authority-state"
    socket_dir = root / "authority-socket"
    socket_path = socket_dir / "repo-patch-authority.sock"
    keys = root / "keys"
    hsai_executable = Path(
        os.environ.get("MESH_OS_PROOF_HSAI_EXECUTABLE", str(HSAI_EXECUTABLE_PATH))
    )
    hsai_executable_sha256 = _mounted_executable_sha256(hsai_executable)
    hsai_policy_id = os.environ.get("MESH_OS_PROOF_HSAI_POLICY_ID", POLICY_ID).strip()
    if hsai_policy_id != POLICY_ID:
        raise ValueError("OS-boundary proof HSAI policy id must match the decision policy")
    for directory in (root, repo, state, socket_dir, keys):
        directory.mkdir(parents=True, exist_ok=True)

    target = repo / "app/search.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 'old'\n", encoding="utf-8")
    _run(["git", "init", "-q", str(repo)])
    _run(["git", "-C", str(repo), "config", "user.name", "Mesh OS Proof"])
    _run(["git", "-C", str(repo), "config", "user.email", "mesh-os-proof@example.invalid"])
    _run(["git", "-C", str(repo), "add", "app/search.py"])
    _run(["git", "-C", str(repo), "commit", "-qm", "fixture"])

    client_private, client_public = _write_key_pair(keys, "client")
    authority_private, authority_public = _write_key_pair(keys, "authority")
    permit_key = keys / "permit.key"
    permit_key.write_text("mesh-os-proof-permit-hmac-key", encoding="utf-8")
    client_registry = keys / "clients.json"
    client_registry.write_text(json.dumps({CLIENT_KEY_ID: str(client_public)}), encoding="utf-8")

    _chown_tree(repo, AUTHORITY_UID, AUTHORITY_GID)
    _chown_tree(state, AUTHORITY_UID, AUTHORITY_GID)
    _chown_tree(socket_dir, AUTHORITY_UID, AUTHORITY_GID)
    _chown_tree(keys, AUTHORITY_UID, AUTHORITY_GID)
    os.chown(client_private, ORCHESTRATOR_UID, AUTHORITY_GID)
    client_private.chmod(0o600)
    authority_private.chmod(0o600)
    permit_key.chmod(0o600)
    client_registry.chmod(0o600)
    client_public.chmod(0o644)
    authority_public.chmod(0o644)
    state.chmod(0o700)
    socket_dir.chmod(0o750)

    common_environment = {
        **os.environ,
        "PYTHONPATH": "/workspace",
        "MESH_OS_PROOF_TARGET": str(target),
        "MESH_REPO_PATCH_AUTHORITY_SOCKET_PATH": str(socket_path),
        "MESH_OS_PROOF_HSAI_EXECUTABLE": str(hsai_executable),
        "MESH_OS_PROOF_HSAI_EXECUTABLE_SHA256": hsai_executable_sha256,
        "MESH_OS_PROOF_HSAI_POLICY_ID": hsai_policy_id,
    }
    agent_write = _run_as(
        [sys.executable, __file__],
        uid=AGENT_UID,
        gid=AGENT_UID,
        groups=(),
        environment={**common_environment, "MESH_OS_PROOF_MODE": "write_probe"},
    )
    orchestrator_write = _run_as(
        [sys.executable, __file__],
        uid=ORCHESTRATOR_UID,
        gid=AUTHORITY_GID,
        groups=(AUTHORITY_GID,),
        environment={**common_environment, "MESH_OS_PROOF_MODE": "write_probe"},
    )

    service_environment = {
        **common_environment,
        "MESH_REPO_PATCH_AUTHORITY_STORE_BACKEND": "file",
        "MESH_REPO_PATCH_AUTHORITY_STATE_DIRECTORY": str(state),
        "MESH_REPO_PATCH_AUTHORITY_PRIVATE_KEY_PATH": str(authority_private),
        "MESH_REPO_PATCH_AUTHORITY_CLIENT_KEYS_PATH": str(client_registry),
        "MESH_REPO_PATCH_AUTHORITY_PERMIT_KEY_PATH": str(permit_key),
        "MESH_REPO_PATCH_AUTHORITY_KEY_ID": AUTHORITY_KEY_ID,
        "MESH_REPO_PATCH_AUTHORITY_ALLOWED_UIDS": str(ORCHESTRATOR_UID),
        "MESH_REPO_PATCH_AUTHORITY_SOCKET_GID": str(AUTHORITY_GID),
        "MESH_REPO_PATCH_ALLOWED_TEST_COMMANDS_JSON": json.dumps([["python3", "-c", "pass"]]),
        "MESH_HSAI_ADMISSION_COMMAND": (
            f"{shlex.quote(str(hsai_executable))} "
            f"--current-policy-id {shlex.quote(hsai_policy_id)}"
        ),
        "MESH_HSAI_ADMISSION_AUTHORITY_MODE": "rust_evidence_v2",
        "MESH_HSAI_ADMISSION_EXECUTABLE_SHA256": hsai_executable_sha256,
    }
    service = subprocess.Popen(
        [sys.executable, "-m", "services.actuators.repo_patch_authority_service"],
        cwd="/workspace",
        env=service_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=_identity_preexec(AUTHORITY_UID, AUTHORITY_GID, (AUTHORITY_GID,)),
    )
    try:
        _wait_for_socket(socket_path, service)
        agent_socket = _run_as(
            [sys.executable, __file__],
            uid=AGENT_UID,
            gid=AGENT_UID,
            groups=(),
            environment={**common_environment, "MESH_OS_PROOF_MODE": "socket_probe"},
        )
        client_environment = {
            **common_environment,
            "MESH_OS_PROOF_MODE": "client",
            "MESH_OS_PROOF_REPO": str(repo),
            "MESH_OS_PROOF_CLIENT_PRIVATE_KEY": str(client_private),
            "MESH_OS_PROOF_AUTHORITY_PUBLIC_KEY": str(authority_public),
        }
        client = _run_as(
            [sys.executable, __file__],
            uid=ORCHESTRATOR_UID,
            gid=AUTHORITY_GID,
            groups=(AUTHORITY_GID,),
            environment=client_environment,
        )
        if client.returncode != 0 or not client.stdout.strip():
            authority_stderr = ""
            if service.poll() is not None:
                _, authority_stderr = service.communicate()
            raise RuntimeError(
                "OS-boundary proof client failed: "
                f"returncode={client.returncode}; "
                f"client_stderr={client.stderr[-4000:]!r}; "
                f"authority_stderr={authority_stderr[-4000:]!r}"
            )
        client_result = json.loads(client.stdout)
        if not isinstance(client_result, dict):
            raise RuntimeError("OS-boundary proof client returned non-object JSON")
        service_uid = _process_uid(service.pid)
        proof: dict[str, Any] = {
            "schema_version": "mesh.repo_patch_authority_os_boundary_proof.v1",
            "state_slice": "mesh.repo_patch_authority_os_identity_boundary.v1",
            "platform": "linux-container",
            "identities": {
                "agent_uid": AGENT_UID,
                "orchestrator_uid": ORCHESTRATOR_UID,
                "authority_uid": AUTHORITY_UID,
                "authority_service_observed_uid": service_uid,
                "authority_socket_gid": AUTHORITY_GID,
            },
            "checks": {
                "agent_direct_write_denied": agent_write.returncode == 0,
                "orchestrator_direct_write_denied": orchestrator_write.returncode == 0,
                "agent_socket_connect_denied": agent_socket.returncode == 0,
                "signed_orchestrator_request_succeeded": client_result["status"] == "succeeded",
                "authority_observed_orchestrator_peer_uid": client_result["peer_uid"] == ORCHESTRATOR_UID,
                "authority_process_has_distinct_uid": service_uid == AUTHORITY_UID,
                "real_pinned_hsai_evidence_v2_allowed": (
                    client_result["hsai_gate_allowed"] is True
                    and client_result["hsai_authority_eligible"] is True
                    and client_result["hsai_executable_sha256"] == hsai_executable_sha256
                ),
                "target_mutated_only_after_authority_request": target.read_text(encoding="utf-8") == "VALUE = 'new'\n",
            },
            "authority_receipt": client_result,
            "claim_ceiling": (
                "disposable Linux-container kernel-UID enforcement proof; not production deployment, "
                "not semantic correctness, and not proof against a compromised root or authority process"
            ),
        }
        proof["status"] = "pass" if all(proof["checks"].values()) else "fail"
        print(json.dumps(proof, sort_keys=True))
        return 0 if proof["status"] == "pass" else 1
    finally:
        service.terminate()
        try:
            service.wait(timeout=5)
        except subprocess.TimeoutExpired:
            service.kill()
            service.wait(timeout=5)


def _client_mode() -> int:
    repo = Path(os.environ["MESH_OS_PROOF_REPO"])
    socket_path = Path(os.environ["MESH_REPO_PATCH_AUTHORITY_SOCKET_PATH"])
    decision = _decision(repo)
    evaluation = _evaluation(decision.decision_id)
    client = RepoPatchAuthorityClient(
        socket_path,
        client_private_key_pem=Path(os.environ["MESH_OS_PROOF_CLIENT_PRIVATE_KEY"]).read_text(encoding="utf-8"),
        client_key_id=CLIENT_KEY_ID,
        authority_public_key_pem=Path(os.environ["MESH_OS_PROOF_AUTHORITY_PUBLIC_KEY"]).read_text(encoding="utf-8"),
        authority_key_id=AUTHORITY_KEY_ID,
    )
    idempotency_key = f"{decision.decision_id}:{decision.execution_plan['action']}"
    preflight_receipt = client.preflight(decision, evaluation, idempotency_key)
    request = build_hsai_admission_request_v2(decision, evaluation, preflight_receipt)
    hsai_executable = Path(os.environ["MESH_OS_PROOF_HSAI_EXECUTABLE"])
    hsai_executable_sha256 = os.environ["MESH_OS_PROOF_HSAI_EXECUTABLE_SHA256"]
    hsai_policy_id = os.environ["MESH_OS_PROOF_HSAI_POLICY_ID"]
    if request["mesh_policy_id"] != hsai_policy_id:
        raise ValueError("real HSAI CLI policy id does not match the bound request")
    hsai_adapter = RustEvidenceV2HsaiAdmissionAdapter(
        (
            f"{shlex.quote(str(hsai_executable))} "
            f"--current-policy-id {shlex.quote(hsai_policy_id)}"
        ),
        executable_sha256=hsai_executable_sha256,
    )
    gate = evaluate_hsai_gate(request, hsai_adapter)
    if gate.get("allowed") is not True or gate.get("authority_eligible") is not True:
        raise RuntimeError(f"real pinned HSAI evidence-v2 admission rejected: {gate.get('reason_codes')}")
    response = client.execute(decision, evaluation, gate, idempotency_key, preflight_receipt)
    receipt = response["receipt"]
    print(
        json.dumps(
            {
                "status": response["execution_result"]["status"],
                "peer_uid": receipt["peer_uid"],
                "peer_gid": receipt["peer_gid"],
                "authenticated_client_key_id": receipt["authenticated_client_key_id"],
                "authority_key_id": receipt["authority_key_id"],
                "request_digest": receipt["request_digest"],
                "execution_result_digest": receipt["execution_result_digest"],
                "preflight_receipt": preflight_receipt,
                "hsai_gate_allowed": gate["allowed"],
                "hsai_authority_eligible": gate["authority_eligible"],
                "hsai_adapter_identity": hsai_adapter.adapter_identity,
                "hsai_executable_sha256": hsai_adapter.executable_sha256,
                "hsai_policy_id": hsai_adapter.current_policy_id,
            },
            sort_keys=True,
        )
    )
    return 0


def _write_probe() -> int:
    try:
        Path(os.environ["MESH_OS_PROOF_TARGET"]).write_text("UNAUTHORIZED\n", encoding="utf-8")
    except PermissionError:
        return 0
    return 1


def _socket_probe() -> int:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(os.environ["MESH_REPO_PATCH_AUTHORITY_SOCKET_PATH"])
    except PermissionError:
        return 0
    finally:
        probe.close()
    return 1


def _decision(repo: Path) -> Decision:
    return Decision(
        decision_id="decision-os-boundary-proof",
        trigger_id="trigger-os-boundary-proof",
        summary="Patch a disposable UID-isolated repository",
        decision_type="investigate_and_patch",
        autonomy_tier="approval_required",
        reasoning={
            "primary_hypothesis": "fixture value needs replacement",
            "evidence": ["disposable Linux UID proof"],
            "alternatives_considered": ["leave unchanged"],
        },
        expected_outcome={
            "target_metrics": {
                "p95_latency_ms": "unchanged",
                "error_rate": "unchanged",
            },
            "time_to_effect": "local",
        },
        risk={
            "level": "medium",
            "blast_radius": "disposable container repository",
            "customer_impact_if_wrong": "none",
        },
        confidence=0.99,
        execution_plan={
            "system": "repo_patch_service",
            "action": "investigate_and_patch",
            "parameters": {
                "repo_path": str(repo),
                "allowed_paths": ["app/search.py"],
                "patch_template": {
                    "target_file": "app/search.py",
                    "find": "old",
                    "replace": "new",
                },
                "test_commands": ["python3 -c pass"],
                "mesh_run_id": "run-os-boundary-proof",
                "mesh_policy_id": POLICY_ID,
                "actor_ref": {"actor_id": "orchestrator.uid.2000", "team_id": "mesh.proof"},
            },
            "rollback_plan": "restore the immutable authority backup",
        },
    )


def _evaluation(decision_id: str) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id="evaluation-os-boundary-proof",
        decision_id=decision_id,
        passed=True,
        final_recommendation="execute",
        stage_results={
            "policy_validation": {
                "passed": True,
                "policy_id": POLICY_ID,
            }
        },
        blocking_reasons=[],
        review_route=None,
    )


def _write_key_pair(root: Path, name: str) -> tuple[Path, Path]:
    key = Ed25519PrivateKey.generate()
    private_path = root / f"{name}-private.pem"
    public_path = root / f"{name}-public.pem"
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def _run_as(
    command: list[str],
    *,
    uid: int,
    gid: int,
    groups: tuple[int, ...],
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        preexec_fn=_identity_preexec(uid, gid, groups),
    )


def _identity_preexec(uid: int, gid: int, groups: tuple[int, ...]) -> Callable[[], None]:
    def apply_identity() -> None:
        os.setgroups(list(groups))
        os.setgid(gid)
        os.setuid(uid)

    return apply_identity


def _chown_tree(root: Path, uid: int, gid: int) -> None:
    for path in [root, *root.rglob("*")]:
        os.chown(path, uid, gid, follow_symlinks=False)


def _wait_for_socket(socket_path: Path, service: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if socket_path.exists():
            return
        if service.poll() is not None:
            _, stderr = service.communicate()
            raise RuntimeError(f"authority service exited before socket creation: {stderr}")
        time.sleep(0.05)
    raise TimeoutError("authority service socket was not created")


def _process_uid(pid: int) -> int:
    for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("Uid:"):
            return int(line.split()[1])
    raise ValueError("authority process UID is unavailable")


def _mounted_executable_sha256(executable: Path) -> str:
    if not executable.is_absolute():
        raise ValueError("OS-boundary proof HSAI executable path must be absolute")
    try:
        metadata = executable.stat(follow_symlinks=False)
    except OSError as exc:
        raise RuntimeError(f"mounted Phase 747 HSAI executable is unavailable: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise RuntimeError("mounted Phase 747 HSAI executable must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode) or not os.access(executable, os.X_OK):
        raise RuntimeError("mounted Phase 747 HSAI executable must be a regular executable file")
    digest = hashlib.sha256()
    with executable.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


if __name__ == "__main__":
    raise SystemExit(main())
