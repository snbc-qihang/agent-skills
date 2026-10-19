"""PEP 517 builds in a temporary source tree, never in the author checkout."""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_DIRECTORIES = ("src", "catalog", "skills", "packs", "schemas", "evals", "config", "native")
SOURCE_FILES = ("pyproject.toml", "setup.py", "ea_build_backend.py", "MANIFEST.in", "VERSIONING.md",
                "LICENSE", "THIRD_PARTY_NOTICES.md")


def _copy_tree(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ValueError("distribution source must not contain symlinks")
    destination.mkdir()
    for path in sorted(source.iterdir()):
        if path.name.startswith(".") or path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"} or path.name.endswith(".egg-info"):
            continue
        if path.is_symlink():
            raise ValueError("distribution source must not contain symlinks")
        if path.is_dir():
            _copy_tree(path, destination / path.name)
        elif path.is_file():
            shutil.copyfile(path, destination / path.name)
        else:
            raise ValueError("distribution source must contain only regular files")


@contextmanager
def _staged_source():
    with tempfile.TemporaryDirectory(prefix="ea-wheel-source-") as temporary:
        stage = Path(temporary)
        for name in SOURCE_FILES:
            source = ROOT / name
            if source.is_symlink() or not source.is_file():
                raise ValueError("distribution build source is missing or unsafe")
            shutil.copyfile(source, stage / name)
        for name in SOURCE_DIRECTORIES:
            _copy_tree(ROOT / name, stage / name)
        previous = Path.cwd()
        try:
            os.chdir(stage)
            yield stage
        finally:
            os.chdir(previous)


def _output_directory(directory: str) -> str:
    path = Path(directory).resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError("distribution output must be outside the author repository")
    return str(path)


def _build(method: str, output: str, config_settings=None, metadata_directory=None, *, editable=False):
    from setuptools import build_meta

    output = _output_directory(output)
    metadata = _output_directory(metadata_directory) if metadata_directory else None
    operation = getattr(build_meta, method)
    if editable:
        # PEP 660 must map the persistent author source, not a disposable copy.
        # dist_info/editable_wheel receive explicit external output directories;
        # no egg_info discovery hook is run against the checkout.
        previous = Path.cwd()
        try:
            os.chdir(ROOT)
            if method == "build_editable":
                return operation(output, config_settings, metadata)
            return operation(output, config_settings)
        finally:
            os.chdir(previous)
    with _staged_source():
        if method in {"build_wheel", "build_editable"}:
            return operation(output, config_settings, metadata)
        return operation(output, config_settings)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    return _build("build_wheel", wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    return _build("build_sdist", sdist_directory, config_settings)


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    return _build("prepare_metadata_for_build_wheel", metadata_directory, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    return _build("build_editable", wheel_directory, config_settings, metadata_directory, editable=True)


def prepare_metadata_for_build_editable(metadata_directory, config_settings=None):
    return _build("prepare_metadata_for_build_editable", metadata_directory, config_settings, editable=True)


def get_requires_for_build_wheel(config_settings=None):
    return []


get_requires_for_build_sdist = get_requires_for_build_wheel
get_requires_for_build_editable = get_requires_for_build_wheel
