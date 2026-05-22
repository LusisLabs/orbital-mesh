#!/usr/bin/env python3
"""Bootstrap CTO handover packages from shared Mesh runtime modules."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGES = REPO / "packages"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def schema_validation_module() -> str:
    return (REPO / "shared/mesh_runtime/schema_validation.py").read_text(encoding="utf-8")


def rewrite_mesh_imports(text: str, *, package: str) -> str:
    text = text.replace(
        "from shared.mesh_runtime.schema_validation import",
        f"from {package}.schema_validation import",
    )
    text = text.replace("from shared.mesh_runtime.", f"from {package}.")
    text = re.sub(
        r"REPO_ROOT = Path\(__file__\)\.resolve\(\)\.parents\[2\]",
        "PACKAGE_ROOT = Path(__file__).resolve().parents[1]",
        text,
    )
    return text.replace("REPO_ROOT", "PACKAGE_ROOT")


def copy_py(src: Path, dst: Path, *, package: str) -> None:
    write(dst, rewrite_mesh_imports(src.read_text(encoding="utf-8"), package=package))


def copy_tree(src_dir: Path, dst_dir: Path) -> None:
    if not src_dir.exists():
        return
    for src in src_dir.rglob("*"):
        if src.is_file():
            rel = src.relative_to(src_dir)
            dst = dst_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def bootstrap_darkharness() -> None:
    root = PACKAGES / "mesh-darkharness-sdk"
    pkg = root / "src" / "mesh_darkharness"
    if pkg.exists():
        shutil.rmtree(pkg)
    write(pkg / "schema_validation.py", schema_validation_module())
    perennial_dst = pkg / "perennial"
    for src in (REPO / "shared/mesh_runtime/perennial").glob("*.py"):
        text = src.read_text(encoding="utf-8")
        text = text.replace(
            "from shared.mesh_runtime.schema_validation import",
            "from mesh_darkharness.schema_validation import",
        )
        write(perennial_dst / src.name, text)
    write(
        pkg / "__init__.py",
        '"""Mesh Darkharness SDK."""\n\nfrom mesh_darkharness.perennial import *  # noqa: F403\n',
    )
    copy_tree(REPO / "shared/mesh_runtime/schemas/perennial", pkg / "schemas/perennial")
    copy_tree(REPO / "fixtures/perennial", root / "fixtures/perennial")
    patch_darkharness_package(root, pkg)


def bootstrap_hardened_arena() -> None:
    root = PACKAGES / "mesh-hardened-arena"
    pkg = root / "src" / "mesh_hardened_arena"
    config_dir = root / "config"
    if pkg.exists():
        shutil.rmtree(pkg)
    write(pkg / "schema_validation.py", schema_validation_module())
    for name in (
        "hardened_arena.py",
        "hardened_arena_catalog.py",
        "hardened_arena_packet.py",
        "hardened_arena_intent.py",
        "hardened_arena_proof.py",
    ):
        copy_py(REPO / "shared/mesh_runtime" / name, pkg / name, package="mesh_hardened_arena")
    catalog = (pkg / "hardened_arena_catalog.py").read_text(encoding="utf-8")
    catalog = catalog.replace(
        'DEFAULT_DHI_CATALOG_HTML = Path("/Users/shaanp/Downloads/Hardened Images catalog _ Docker Hub.html")',
        "DEFAULT_DHI_CATALOG_HTML = PACKAGE_ROOT / 'examples' / 'dhi-catalog.sample.html'",
    )
    write(pkg / "hardened_arena_catalog.py", catalog)
    for module in (
        "hardened_arena",
        "hardened_arena_catalog",
        "hardened_arena_packet",
        "hardened_arena_intent",
        "hardened_arena_proof",
    ):
        path = pkg / f"{module}.py"
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "PACKAGE_ROOT = Path(__file__).resolve().parents[1]",
            "PACKAGE_ROOT = Path(__file__).resolve().parents[2]",
        )
        write(path, text)
    write(
        pkg / "__init__.py",
        '"""Mesh Hardened Arena toolkit."""\n\nfrom mesh_hardened_arena.hardened_arena import *  # noqa: F403\n'
        'from mesh_hardened_arena.hardened_arena_catalog import *  # noqa: F403\n'
        'from mesh_hardened_arena.hardened_arena_intent import *  # noqa: F403\n'
        'from mesh_hardened_arena.hardened_arena_proof import *  # noqa: F403\n',
    )
    schemas = pkg / "schemas"
    schemas.mkdir(parents=True, exist_ok=True)
    for schema in (REPO / "shared/mesh_runtime/schemas").glob("hardened-arena-*.schema.json"):
        shutil.copy2(schema, schemas / schema.name)
    for cfg in ("hardened-arena.profiles.json", "hardened-arena.catalog.json"):
        dst = root / "config" / cfg
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "config" / cfg, dst)


def bootstrap_praxis() -> None:
    root = PACKAGES / "mesh-praxis"
    pkg = root / "src" / "mesh_praxis"
    fixtures_dir = root / "fixtures" / "praxis"
    if pkg.exists():
        shutil.rmtree(pkg)
    if fixtures_dir.exists():
        shutil.rmtree(fixtures_dir.parent)
    write(pkg / "schema_validation.py", schema_validation_module())
    shutil.copy2(REPO / "shared/mesh_runtime/json_store.py", pkg / "json_store.py")
    copy_py(REPO / "shared/mesh_runtime/praxis.py", pkg / "praxis.py", package="mesh_praxis")
    praxis = (pkg / "praxis.py").read_text(encoding="utf-8")
    praxis = praxis.replace(
        "_REPO_ROOT = Path(__file__).resolve().parents[2]",
        "_PACKAGE_ROOT = Path(__file__).resolve().parents[2]",
    )
    praxis = praxis.replace("_REPO_ROOT", "_PACKAGE_ROOT")
    praxis = praxis.replace("_resolve_repo_path", "_resolve_package_path")
    praxis = praxis.replace(
        "def _resolve_package_path(path: str) -> Path:\n    candidate = Path(path)\n    return candidate if candidate.is_absolute() else _PACKAGE_ROOT / candidate",
        "def _resolve_package_path(path: str) -> Path:\n    candidate = Path(path)\n    if candidate.is_absolute():\n        return candidate\n    package_candidate = _PACKAGE_ROOT / candidate\n    if package_candidate.exists():\n        return package_candidate\n    return Path(__file__).resolve().parents[3] / candidate",
    )
    praxis = praxis.replace(
        "_PACKAGE_ROOT = Path(__file__).resolve().parents[1]",
        "_PACKAGE_ROOT = Path(__file__).resolve().parents[2]",
    )
    write(pkg / "praxis.py", praxis)
    write(pkg / "__init__.py", '"""Mesh Praxis pipeline."""\n\nfrom mesh_praxis.praxis import *  # noqa: F403\n')
    copy_tree(REPO / "shared/mesh_runtime/schemas/praxis", pkg / "schemas/praxis")
    copy_tree(REPO / "fixtures/praxis", root / "fixtures/praxis")


PACKAGE_MODULE_DIRS = {
    "mesh-darkharness-sdk": "mesh_darkharness",
    "mesh-hardened-arena": "mesh_hardened_arena",
    "mesh-praxis": "mesh_praxis",
    "mesh-centaur-sandbox": "mesh_centaur_sandbox",
}


def copy_handover_assets() -> None:
    assets_root = REPO / "scripts" / "handover_assets"
    for package_name, module_name in PACKAGE_MODULE_DIRS.items():
        asset_dir = assets_root / package_name
        if not asset_dir.exists():
            continue
        package_root = PACKAGES / package_name
        module_dir = package_root / "src" / module_name
        module_dir.mkdir(parents=True, exist_ok=True)
        for name in ("pyproject.toml", "README.md", "HANDOVER.md"):
            src = asset_dir / name
            if src.exists():
                shutil.copy2(src, package_root / name)
        src_dir = asset_dir / "src"
        if src_dir.exists():
            for src in src_dir.glob("*.py"):
                shutil.copy2(src, module_dir / src.name)
        for name in ("Makefile",):
            src = asset_dir / name
            if src.exists():
                shutil.copy2(src, package_root / name)


def bootstrap_centaur() -> None:
    root = PACKAGES / "mesh-centaur-sandbox"
    pkg = root / "src" / "mesh_centaur_sandbox"
    manifests_dir = root / "manifests"
    if pkg.exists():
        shutil.rmtree(pkg)
    if manifests_dir.exists():
        shutil.rmtree(manifests_dir)
    pkg.mkdir(parents=True, exist_ok=True)
    for name in ("centaur_deployment.py", "credential_egress.py"):
        shutil.copy2(REPO / "shared/mesh_runtime" / name, pkg / name)
    write(
        pkg / "__init__.py",
        '"""Mesh Centaur sandbox helpers."""\n\nfrom mesh_centaur_sandbox.centaur_deployment import *  # noqa: F403\n'
        'from mesh_centaur_sandbox.credential_egress import *  # noqa: F403\n',
    )
    for cfg in (REPO / "config").glob("centaur*"):
        dst = root / "manifests" / cfg.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cfg, dst)
    adapter_src = REPO / "services/orchestrator"
    for name in ("centaur_runtime_adapter.py", "credential_egress_proxy.py"):
        text = (adapter_src / name).read_text(encoding="utf-8")
        text = text.replace(
            "from shared.mesh_runtime.credential_egress import verify_credential_egress_policy",
            "from mesh_centaur_sandbox.credential_egress import verify_credential_egress_policy",
        )
        write(pkg / "adapter" / name, text)


def patch_darkharness_package(root: Path, pkg: Path) -> None:
    write(
        pkg / "fixtures.py",
        '''from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def load_fixture(domain: str, name: str) -> dict[str, Any]:
    path = PACKAGE_ROOT / "fixtures" / domain / name
    return json.loads(path.read_text(encoding="utf-8"))
''',
    )
    registry = pkg / "perennial" / "registry.py"
    text = registry.read_text(encoding="utf-8")
    text = text.replace(
        "from shared.mesh_runtime.fixtures import load_fixture",
        "from mesh_darkharness.fixtures import load_fixture",
    )
    write(registry, text)


def main() -> int:
    bootstrap_darkharness()
    bootstrap_hardened_arena()
    bootstrap_praxis()
    bootstrap_centaur()
    copy_handover_assets()
    print("Bootstrapped handover packages under packages/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
