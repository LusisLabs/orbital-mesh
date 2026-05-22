#!/usr/bin/env python3
"""Export Mesh handover packages as standalone git repositories."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT.parent / "mesh-handover"
PACKAGES = (
    "mesh-darkharness-sdk",
    "mesh-hardened-arena",
    "mesh-praxis",
    "mesh-centaur-sandbox",
)
SKIP_DIR_NAMES = {".pytest_cache", "__pycache__", "dist", ".git"}
SKIP_SUFFIXES = (".egg-info", ".pyc", ".pyo")
MIT_LICENSE = """MIT License

Copyright (c) 2026 Mesh Intelligence Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
GITIGNORE = """dist/
*.egg-info/
__pycache__/
.pytest_cache/
.venv/
.env
.DS_Store
"""
VERIFY_SH = """#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$ROOT"
if [[ "${{1:-}}" == "--help" || "${{1:-}}" == "-h" ]]; then
  PYTHONPATH=src python3 -m {module} --help
  exit 0
fi
PYTHONPATH=src python3 -m {module} verify-e2e "$@"
"""


def _should_skip(path: Path) -> bool:
    if path.name in SKIP_DIR_NAMES:
        return True
    return any(path.name.endswith(suffix) for suffix in SKIP_SUFFIXES)


def _copy_package(package_name: str, src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in dst.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in src.iterdir():
        if _should_skip(item):
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(*SKIP_DIR_NAMES, "*.egg-info", "__pycache__"))
        else:
            shutil.copy2(item, target)
    (dst / "LICENSE").write_text(MIT_LICENSE, encoding="utf-8")
    (dst / ".gitignore").write_text(GITIGNORE, encoding="utf-8")


def _module_for_package(package_name: str) -> str:
    mapping = {
        "mesh-darkharness-sdk": "mesh_darkharness",
        "mesh-hardened-arena": "mesh_hardened_arena",
        "mesh-praxis": "mesh_praxis",
        "mesh-centaur-sandbox": "mesh_centaur_sandbox",
    }
    return mapping[package_name]


def _write_verify_script(dst: Path, package_name: str) -> None:
    script = dst / "verify-e2e.sh"
    script.write_text(VERIFY_SH.format(module=_module_for_package(package_name)), encoding="utf-8")
    script.chmod(0o755)


def _append_origin_note(dst: Path, package_name: str) -> None:
    note = dst / "ORIGIN.md"
    note.write_text(
        f"""# Origin

This repository was exported from [Orbital Mesh](https://github.com/LusisLabs/orbital-mesh) handover package `{package_name}`.

- Export tool: `scripts/export_handover_repos.py`
- Upstream sync: re-run bootstrap + export from the monorepo after Mesh runtime changes
- Monorepo integration index: `packages/HANDOVER.md`

Exported at: {datetime.now(timezone.utc).isoformat()}
""",
        encoding="utf-8",
    )


def _git_init(repo: Path, *, message: str) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)


def _ensure_git_commit(repo: Path, *, package_name: str, message: str) -> None:
    if not (repo / ".git").exists():
        _git_init(repo, message=message)
        subprocess.run(
            ["git", "remote", "add", "origin", f"https://github.com/LusisLabs/{package_name}.git"],
            cwd=repo,
            check=False,
            capture_output=True,
        )
        return
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True)
    if status.stdout.strip():
        subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)


def _verify_exported_repo(repo: Path, package_name: str) -> dict[str, object]:
    module = _module_for_package(package_name)
    completed = subprocess.run(
        [sys.executable, "-m", f"{module}.cli", "verify-e2e", "--json"],
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(repo / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    result: dict[str, object] = {
        "package": package_name,
        "path": str(repo),
        "returncode": completed.returncode,
        "status": "pass" if completed.returncode == 0 else "fail",
    }
    if completed.stdout.strip():
        try:
            result["verify"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            result["stdout"] = completed.stdout.strip()
    if completed.stderr.strip():
        result["stderr"] = completed.stderr.strip()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Mesh handover packages as standalone git repos")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Directory containing exported repos")
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--skip-git", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    if not args.skip_bootstrap:
        subprocess.run([sys.executable, str(REPO_ROOT / "scripts/bootstrap_handover_packages.py")], check=True)

    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, object]] = []

    for package_name in PACKAGES:
        src = REPO_ROOT / "packages" / package_name
        dst = output_root / package_name
        if not src.exists():
            print(f"missing package source: {src}", file=sys.stderr)
            return 1
        _copy_package(package_name, src, dst)
        _write_verify_script(dst, package_name)
        _append_origin_note(dst, package_name)
        if not args.skip_git:
            _ensure_git_commit(
                dst,
                package_name=package_name,
                message=f"Update {package_name} handover export with expanded CLI and README.",
            )
        verify = {"status": "skipped"} if args.skip_verify else _verify_exported_repo(dst, package_name)
        manifest_entries.append(
            {
                "name": package_name,
                "path": str(dst),
                "git_initialized": not args.skip_git,
                "verify": verify,
            }
        )
        print(f"exported: {dst} ({verify.get('status', 'unknown')})")

    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_repo": str(REPO_ROOT),
        "output_root": str(output_root),
        "packages": manifest_entries,
    }
    (output_root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    readme = output_root / "README.md"
    readme.write_text(
        """# Mesh Handover Repositories

Standalone exports of Orbital Mesh CTO handover packages.

| Repository | Verify |
| --- | --- |
| [mesh-darkharness-sdk](./mesh-darkharness-sdk/) | `./mesh-darkharness-sdk/verify-e2e.sh` |
| [mesh-hardened-arena](./mesh-hardened-arena/) | `./mesh-hardened-arena/verify-e2e.sh` |
| [mesh-praxis](./mesh-praxis/) | `./mesh-praxis/verify-e2e.sh` |
| [mesh-centaur-sandbox](./mesh-centaur-sandbox/) | `./mesh-centaur-sandbox/verify-e2e.sh` |

Each subdirectory is an independent git repository. See `MANIFEST.json` for export metadata.
""",
        encoding="utf-8",
    )
    if not args.skip_git:
        if not (output_root / ".git").exists():
            _git_init(output_root, message="Initial mesh handover export manifest.")
        else:
            _ensure_git_commit(output_root, package_name="mesh-handover", message="Update mesh handover manifest.")

    failed = [entry for entry in manifest_entries if entry.get("verify", {}).get("status") == "fail"]
    if failed:
        print("export verification failed for:", ", ".join(str(entry["name"]) for entry in failed), file=sys.stderr)
        return 1
    print(f"manifest: {output_root / 'MANIFEST.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
