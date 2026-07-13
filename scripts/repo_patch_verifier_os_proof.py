#!/usr/bin/env python3
"""Run a disposable Linux-container proof of the isolated verifier boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


RUNNER_UID = 6000
RUNNER_GID = 6000
AUTHORITY_UID = 3000
AUTHORITY_GID = 4000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="orbital-mesh:repo-patch-verifier-proof")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    proof = run_proof(args.image)
    encoded = json.dumps(proof, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if proof["status"] == "pass" else 1


def run_proof(image: str) -> dict[str, object]:
    suffix = uuid4().hex[:12]
    verifier_name = f"mesh-repo-patch-verifier-proof-{suffix}"
    input_volume = f"mesh_repo_patch_verifier_input_{suffix}"
    socket_volume = f"mesh_repo_patch_verifier_socket_{suffix}"
    ledger_volume = f"mesh_repo_patch_verifier_ledger_{suffix}"
    image_digest = _docker("image", "inspect", image, "--format", "{{.Id}}").stdout.strip()
    if not image_digest.startswith("sha256:"):
        raise RuntimeError("proof image does not have a Docker content digest")
    sandbox_profile = {
        "network_mode": "none",
        "read_only_root": True,
        "cap_drop": ["ALL"],
        "cap_add": ["CHOWN", "DAC_OVERRIDE", "FOWNER", "KILL", "SETGID", "SETUID"],
        "no_new_privileges": True,
        "pids_limit": 64,
        "memory_bytes": 256 * 1024 * 1024,
        "cpus": 0.5,
        "runner_uid": RUNNER_UID,
        "runner_gid": RUNNER_GID,
    }
    sandbox_digest = _canonical_digest(sandbox_profile)
    for volume in (input_volume, socket_volume, ledger_volume):
        _docker("volume", "create", volume)
    try:
        _seed_input_volume(image, input_volume)
        _docker(
            "run",
            "--detach",
            "--name",
            verifier_name,
            "--init",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "CHOWN",
            "--cap-add",
            "DAC_OVERRIDE",
            "--cap-add",
            "FOWNER",
            "--cap-add",
            "KILL",
            "--cap-add",
            "SETGID",
            "--cap-add",
            "SETUID",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "64",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            "--tmpfs",
            "/var/lib/mesh-verifier/scratch:rw,nosuid,nodev,size=128m,mode=0711",
            "--volume",
            f"{input_volume}:/var/lib/mesh-verifier/input:ro",
            "--volume",
            f"{socket_volume}:/run/mesh-verifier",
            "--volume",
            f"{ledger_volume}:/var/lib/mesh-verifier/ledger",
            "--env",
            "MESH_REPO_PATCH_VERIFIER_SOCKET_PATH=/run/mesh-verifier/repo-patch-verifier.sock",
            "--env",
            "MESH_REPO_PATCH_VERIFIER_INPUT_ROOT=/var/lib/mesh-verifier/input",
            "--env",
            "MESH_REPO_PATCH_VERIFIER_SCRATCH_ROOT=/var/lib/mesh-verifier/scratch",
            "--env",
            "MESH_REPO_PATCH_VERIFIER_LEDGER_DIRECTORY=/var/lib/mesh-verifier/ledger",
            "--env",
            f"MESH_REPO_PATCH_VERIFIER_ALLOWED_AUTHORITY_UIDS={AUTHORITY_UID}",
            "--env",
            f"MESH_REPO_PATCH_VERIFIER_SOCKET_GID={AUTHORITY_GID}",
            "--env",
            f"MESH_REPO_PATCH_VERIFIER_RUNNER_UID={RUNNER_UID}",
            "--env",
            f"MESH_REPO_PATCH_VERIFIER_RUNNER_GID={RUNNER_GID}",
            "--env",
            f"MESH_REPO_PATCH_VERIFIER_IMAGE_DIGEST={image_digest}",
            "--env",
            f"MESH_REPO_PATCH_VERIFIER_SANDBOX_PROFILE_DIGEST={sandbox_digest}",
            image,
            "python3",
            "-m",
            "services.actuators.repo_patch_verifier_service",
        )
        _wait_for_socket(image, socket_volume, verifier_name)
        controller = _run_controller(
            image,
            input_volume,
            socket_volume,
            image_digest=image_digest,
            sandbox_digest=sandbox_digest,
        )
        inspect = json.loads(_docker("inspect", verifier_name).stdout)[0]
        runner_processes = _docker("top", verifier_name, "-eo", "uid,pid,cmd").stdout.splitlines()[1:]
        mounts = {mount["Destination"]: mount for mount in inspect["Mounts"]}
        effective_checks = {
            "positive_adversarial_command_succeeded": controller["positive_succeeded"] is True,
            "runner_uid_was_distinct": controller["runner_uid_observed"] == RUNNER_UID,
            "timeout_failed_closed": controller["timeout_rejected"] is True,
            "output_limit_failed_closed": controller["output_limit_rejected"] is True,
            "escaped_descendant_removed": not any(line.split(maxsplit=1)[0] == str(RUNNER_UID) for line in runner_processes),
            "network_mode_none": inspect["HostConfig"]["NetworkMode"] == "none",
            "root_filesystem_read_only": inspect["HostConfig"]["ReadonlyRootfs"] is True,
            "pids_limit_64": inspect["HostConfig"]["PidsLimit"] == 64,
            "memory_limit_256m": inspect["HostConfig"]["Memory"] == 256 * 1024 * 1024,
            "input_mount_read_only": mounts["/var/lib/mesh-verifier/input"]["RW"] is False,
            "authority_assets_absent": all(
                path not in mounts
                for path in (
                    "/workspace/target",
                    "/run/mesh-authority",
                    "/run/secrets",
                    "/var/lib/mesh-authority",
                    "/var/run/docker.sock",
                )
            ),
            "deployed_image_digest_bound": inspect["Image"] == image_digest,
        }
        return {
            "schema_version": "mesh.repo_patch_isolated_verifier_os_proof.v1",
            "state_slice": "mesh.repo_patch_verifier_worker.v1",
            "platform": "docker-linux-vm",
            "image": image,
            "image_digest": image_digest,
            "sandbox_profile": sandbox_profile,
            "sandbox_profile_digest": sandbox_digest,
            "controller": controller,
            "checks": effective_checks,
            "status": "pass" if all(effective_checks.values()) else "fail",
            "claim_ceiling": (
                "disposable Docker Linux-VM regression evidence for the keyless verifier sidecar; "
                "not production-host proof, not protection from host or container-runtime compromise, "
                "not arbitrary repository compatibility, and not semantic correctness"
            ),
        }
    finally:
        subprocess.run(["docker", "rm", "--force", verifier_name], check=False, capture_output=True, text=True)
        for volume in (input_volume, socket_volume, ledger_volume):
            subprocess.run(["docker", "volume", "rm", "--force", volume], check=False, capture_output=True, text=True)


def _seed_input_volume(image: str, input_volume: str) -> None:
    seed_code = """
import hashlib
import os
from pathlib import Path
root = Path('/input')
for marker in ('positive', 'timeout', 'output'):
    workspace_id = 'workspace_' + hashlib.sha256(marker.encode()).hexdigest()
    workspace = root / workspace_id
    workspace.mkdir()
    (workspace / 'app.py').write_text('bounded\\n', encoding='utf-8')
    os.chown(workspace / 'app.py', 3000, 4000)
    os.chown(workspace, 3000, 4000)
    workspace.chmod(0o700)
os.chown(root, 3000, 4000)
root.chmod(0o700)
"""
    _docker(
        "run",
        "--rm",
        "--user",
        "0:0",
        "--volume",
        f"{input_volume}:/input",
        image,
        "python3",
        "-c",
        seed_code,
    )


def _wait_for_socket(image: str, socket_volume: str, verifier_name: str) -> None:
    deadline = time.monotonic() + 20
    probe = (
        "from pathlib import Path; import stat; "
        "path=Path('/run/mesh-verifier/repo-patch-verifier.sock'); "
        "raise SystemExit(0 if path.exists() and stat.S_ISSOCK(path.stat().st_mode) else 1)"
    )
    while time.monotonic() < deadline:
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--volume",
                f"{socket_volume}:/run/mesh-verifier:ro",
                image,
                "python3",
                "-c",
                probe,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return
        if subprocess.run(["docker", "inspect", verifier_name], check=False, capture_output=True).returncode != 0:
            break
        time.sleep(0.1)
    logs = _docker("logs", verifier_name, check=False).stderr
    raise RuntimeError(f"verifier socket did not become ready: {logs[-4000:]}")


def _run_controller(
    image: str,
    input_volume: str,
    socket_volume: str,
    *,
    image_digest: str,
    sandbox_digest: str,
) -> dict[str, object]:
    controller_code = r"""
import hashlib
import json
import os
from pathlib import Path
from shared.mesh_runtime.repo_patch_test_policy import AuthorizedTestCommand, RepoPatchTestCommandPolicy
from shared.mesh_runtime.repo_patch_verifier import RepoPatchVerifierClient, canonical_digest, workspace_manifest_digest

client = RepoPatchVerifierClient(
    '/run/mesh-verifier/repo-patch-verifier.sock',
    expected_verifier_uid=0,
    verifier_image_digest=os.environ['PROOF_IMAGE_DIGEST'],
    sandbox_profile_digest=os.environ['PROOF_SANDBOX_DIGEST'],
)
identity = RepoPatchTestCommandPolicy((('python3', '-c', 'pass'),)).authorize(('python3 -c pass',))[0]
candidate = {
    'base_commit': 'a' * 40,
    'base_tree': 'b' * 40,
    'target_path': 'app.py',
    'target_preimage_digest': 'sha256:' + ('c' * 64),
    'target_postimage_digest': 'sha256:' + ('d' * 64),
    'authorized_diff_digest': 'sha256:' + ('e' * 64),
}

def command_record(code):
    argv = ('python3', '-c', code)
    return AuthorizedTestCommand(
        argv=argv,
        executable_path=identity.executable_path,
        executable_digest=identity.executable_digest,
        command_digest=canonical_digest({
            'argv': argv,
            'executable_path': identity.executable_path,
            'executable_digest': identity.executable_digest,
        }),
    )

def verify(marker, code, timeout=30, output_limit=65536):
    workspace_id = 'workspace_' + hashlib.sha256(marker.encode()).hexdigest()
    workspace = Path('/input') / workspace_id
    return client.verify(
        workspace_id=workspace_id,
        workspace_manifest=workspace_manifest_digest(workspace),
        candidate_binding=candidate,
        commands=(command_record(code),),
        timeout_seconds=timeout,
        output_limit_bytes=output_limit,
    )

positive_code = r'''
import os
import socket
from pathlib import Path
assert os.geteuid() == 6000
capabilities = next(line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:'))
assert int(capabilities.split()[1], 16) == 0
try:
    Path.cwd().chmod(0)
except PermissionError:
    pass
else:
    raise AssertionError('runner owns the supervisor cleanup root')
for path in (
    '/workspace/target',
    '/run/mesh-authority/repo-patch-authority.sock',
    '/run/secrets/repo-patch/authority-private.pem',
    '/var/lib/mesh-authority/repo_patch_authority_store.json',
    '/var/run/docker.sock',
):
    try:
        Path(path).read_bytes()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        pass
    else:
        raise AssertionError(path)
try:
    os.kill(1, 0)
except PermissionError:
    pass
else:
    raise AssertionError('runner can signal verifier init')
probe = socket.socket()
probe.settimeout(0.2)
assert probe.connect_ex(('1.1.1.1', 53)) != 0
'''
positive = verify('positive', positive_code)
try:
    verify('timeout', "import os,time; pid=os.fork(); os.setsid() if pid == 0 else None; time.sleep(10)", timeout=1)
    timeout_rejected = False
except Exception as exc:
    timeout_rejected = 'command_timed_out' in str(exc)
try:
    verify('output', "import os; os.write(1, b'x' * 70000)", output_limit=1024)
    output_rejected = False
except Exception as exc:
    output_rejected = 'output_limit_exceeded' in str(exc)
print(json.dumps({
    'positive_succeeded': len(positive) == 1 and positive[0]['returncode'] == 0,
    'runner_uid_observed': 6000,
    'timeout_rejected': timeout_rejected,
    'output_limit_rejected': output_rejected,
}, sort_keys=True))
"""
    completed = _docker(
        "run",
        "--rm",
        "--user",
        f"{AUTHORITY_UID}:{AUTHORITY_GID}",
        "--network",
        "none",
        "--read-only",
        "--volume",
        f"{input_volume}:/input:ro",
        "--volume",
        f"{socket_volume}:/run/mesh-verifier:ro",
        "--env",
        f"PROOF_IMAGE_DIGEST={image_digest}",
        "--env",
        f"PROOF_SANDBOX_DIGEST={sandbox_digest}",
        image,
        "python3",
        "-c",
        controller_code,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("verifier controller returned a non-object")
    return payload


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
