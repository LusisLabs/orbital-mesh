#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = (
    "Dockerfile",
    "Dockerfile.stack.hermes",
    "Dockerfile.latentmas.cpu",
)
_ARG_REFERENCE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Docker image and base-image digest metadata for CI release attestation.")
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--output", required=True, help="Write mesh.release_image_metadata.v1 JSON here.")
    parser.add_argument("--github-env", default="", help="Append MESH_IMAGE_DIGEST to this GitHub env file.")
    parser.add_argument("--base-image-args", default="", help="Write generate_ci_attestation.py base-image args to this file.")
    parser.add_argument(
        "--dockerfile",
        action="append",
        default=[],
        help="Repo-relative Dockerfile whose external FROM materials must be recorded. Repeatable.",
    )
    parser.add_argument("--expected-source", default="", help="Required org.opencontainers.image.source label.")
    parser.add_argument("--expected-revision", default="", help="Required org.opencontainers.image.revision label.")
    parser.add_argument("--expected-version", default="", help="Required org.opencontainers.image.version label.")
    parser.add_argument(
        "--require-complete-base-images",
        action="store_true",
        help="Fail unless every external FROM image resolves to a registry digest.",
    )
    parser.add_argument("--skip-pull", action="store_true", help="Do not pull base images before inspection.")
    args = parser.parse_args()

    try:
        packet = collect_release_image_metadata(
            image_tag=args.image_tag,
            pull_base_images=not args.skip_pull,
            dockerfiles=tuple(args.dockerfile) or DOCKERFILES,
            expected_source=args.expected_source,
            expected_revision=args.expected_revision,
            expected_version=args.expected_version,
            require_complete_base_images=args.require_complete_base_images,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.github_env:
        _write_github_env(Path(args.github_env), packet)
    if args.base_image_args:
        _write_base_image_args(Path(args.base_image_args), packet)

    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


def collect_release_image_metadata(
    *,
    image_tag: str,
    pull_base_images: bool,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    dockerfiles: tuple[str, ...] = DOCKERFILES,
    expected_source: str = "",
    expected_revision: str = "",
    expected_version: str = "",
    require_complete_base_images: bool = False,
) -> dict[str, Any]:
    run = runner or _run
    image = _inspect_image(
        image_tag,
        run=run,
        expected_source=expected_source,
        expected_revision=expected_revision,
        expected_version=expected_version,
    )
    base_images = []
    for record in discover_base_images(dockerfiles=dockerfiles):
        digest = _base_image_digest(record["image"], run=run, pull=pull_base_images)
        if require_complete_base_images and digest is None:
            raise RuntimeError(
                f"could not determine registry digest for base image {record['image']} "
                f"from {record['source']}:{record['line']}"
            )
        base_images.append({**record, "digest": digest, "pinned": bool(digest)})
    return {
        "schema_version": "mesh.release_image_metadata.v1",
        "generated_at": _timestamp(),
        "image": image,
        "base_images": base_images,
    }


def discover_base_images(
    repo_root: Path = REPO_ROOT,
    dockerfiles: tuple[str, ...] = DOCKERFILES,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for rel in dockerfiles:
        relative = Path(rel)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Dockerfile path must be repo-relative: {rel}")
        path = repo_root / rel
        if not path.is_file():
            raise RuntimeError(f"Dockerfile does not exist: {rel}")
        known_stages: set[str] = set()
        global_args: dict[str, str] = {}
        seen_from = False
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            parts = raw.strip().split()
            if not parts:
                continue
            directive = parts[0].upper()
            if directive == "ARG" and not seen_from and len(parts) >= 2:
                name, separator, default = parts[1].partition("=")
                if name and separator:
                    global_args[name] = default
                continue
            if directive != "FROM":
                continue
            seen_from = True
            image_index = 1
            while image_index < len(parts) and parts[image_index].startswith("--"):
                image_index += 1
            if image_index >= len(parts):
                continue
            image_ref = _resolve_arg_references(parts[image_index], global_args, rel, line_number)
            alias = _from_alias(parts)
            if image_ref in known_stages:
                if alias:
                    known_stages.add(alias)
                continue
            image = image_ref.split("@", 1)[0]
            if alias:
                known_stages.add(alias)
            records.append({"image": image, "source": rel, "line": line_number})
    return records


def _inspect_image(
    image_tag: str,
    *,
    run: Callable[[list[str]], subprocess.CompletedProcess[str]],
    expected_source: str,
    expected_revision: str,
    expected_version: str,
) -> dict[str, str | None]:
    payload = _docker_inspect(image_tag, run=run)
    image_id = str(payload.get("Id") or "")
    repo_digests = payload.get("RepoDigests") if isinstance(payload.get("RepoDigests"), list) else []
    repo_digest = next((str(item) for item in repo_digests if isinstance(item, str) and "@sha256:" in item), "")
    digest = repo_digest.split("@", 1)[1] if repo_digest else image_id
    if not _valid_digest(digest):
        raise RuntimeError(f"could not determine sha256 digest for image {image_tag}")
    config = payload.get("Config") if isinstance(payload.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    source = str(labels.get("org.opencontainers.image.source") or "")
    revision = str(labels.get("org.opencontainers.image.revision") or "")
    version = str(labels.get("org.opencontainers.image.version") or "")
    for name, expected, observed in (
        ("source", expected_source, source),
        ("revision", expected_revision, revision),
        ("version", expected_version, version),
    ):
        if expected and observed != expected:
            raise RuntimeError(f"image {name} label mismatch for {image_tag}: expected {expected!r}, got {observed!r}")
    return {
        "tag": image_tag,
        "digest": digest,
        "digest_source": "repo_digest" if repo_digest else "local_image_id",
        "repo_digest": repo_digest or None,
        "image_id": image_id or None,
        "source": source or None,
        "revision": revision or None,
        "version": version or None,
    }


def _resolve_arg_references(value: str, args: dict[str, str], source: str, line: int) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2) or ""
        if name not in args or not args[name]:
            raise RuntimeError(f"unresolved Dockerfile ARG {name!r} in {source}:{line}")
        return args[name]

    return _ARG_REFERENCE.sub(replace, value)


def _base_image_digest(
    image: str,
    *,
    run: Callable[[list[str]], subprocess.CompletedProcess[str]],
    pull: bool,
) -> str | None:
    if pull:
        pulled = run(["docker", "pull", image])
        if pulled.returncode != 0:
            return None
    try:
        payload = _docker_inspect(image, run=run)
    except RuntimeError:
        return None
    repo_digests = payload.get("RepoDigests") if isinstance(payload.get("RepoDigests"), list) else []
    for item in repo_digests:
        if isinstance(item, str) and item.startswith(f"{image.split(':', 1)[0]}@sha256:"):
            return item.split("@", 1)[1]
    for item in repo_digests:
        if isinstance(item, str) and "@sha256:" in item:
            return item.split("@", 1)[1]
    return None


def _docker_inspect(image: str, *, run: Callable[[list[str]], subprocess.CompletedProcess[str]]) -> dict[str, Any]:
    inspected = run(["docker", "image", "inspect", image])
    if inspected.returncode != 0:
        raise RuntimeError(f"docker image inspect failed for {image}: {inspected.stderr.strip()}")
    payload = json.loads(inspected.stdout)
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise RuntimeError(f"docker image inspect returned invalid payload for {image}")
    return payload[0]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO_ROOT, check=False, capture_output=True, text=True)


def _write_github_env(path: Path, packet: dict[str, Any]) -> None:
    image = packet["image"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"MESH_IMAGE_DIGEST={image['digest']}\n")


def _write_base_image_args(path: Path, packet: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for item in packet.get("base_images", []):
        if not isinstance(item, dict) or not item.get("digest"):
            continue
        lines.append("--base-image-digest")
        lines.append(f"{item['image']}={item['digest']}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _from_alias(parts: list[str]) -> str | None:
    lowered = [part.lower() for part in parts]
    if "as" not in lowered:
        return None
    index = lowered.index("as")
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


def _valid_digest(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    tail = value[len("sha256:") :]
    return len(tail) == 64 and all(char in "0123456789abcdefABCDEF" for char in tail)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
