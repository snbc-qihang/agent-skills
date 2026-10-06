"""Exercise the built setup wheel in an isolated, fixed Python environment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.artifact_io import ArtifactIO
from engineering_assistant.installation import PYTHON_VERSION, _protocol_run, _uv


def _output_directory(output: Path) -> ArtifactIO:
    raw = output.absolute()
    author = ROOT.resolve()
    if ".." in raw.parts or raw.resolve() == author or author in raw.resolve().parents:
        raise ValueError("wheel verification output must be outside author source")
    anchor = ArtifactIO(Path(raw.anchor), ".")
    parent = raw.parent
    missing = []
    retained = None
    result = None
    try:
        while True:
            try:
                with anchor.open_directory(*parent.relative_to(raw.anchor).parts) as descriptor:
                    retained = ArtifactIO.from_open_directory_fd(parent, descriptor)
                break
            except FileNotFoundError:
                missing.insert(0, parent.name)
                parent = parent.parent
        retained.assert_runtime_target(ROOT / "schemas")
        retained.ensure_directory(*missing)
        with retained.open_directory(*missing) as descriptor:
            result = ArtifactIO.from_open_directory_fd(raw.parent, descriptor)
        result.assert_runtime_target(ROOT / "schemas")
        return result
    except Exception:
        if result is not None:
            result.close()
        raise
    finally:
        if retained is not None:
            retained.close()
        anchor.close()


def _verify_wheel(wheel: Path) -> dict:
    wheel = wheel.absolute()
    storage = ArtifactIO(wheel.parent, ".")
    try:
        payload = storage.read_bytes_limited(64 * 1024 * 1024, wheel.name)
    finally:
        storage.close()
    from zipfile import ZipFile
    from email.parser import Parser
    import io
    with ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1 or archive.getinfo(names[0]).file_size > 65536:
            raise ValueError("setup wheel metadata is missing or oversized")
        metadata = Parser().parsestr(archive.read(names[0]).decode("utf-8"))
    import tomllib
    canonical = json.loads((ROOT / "catalog/skills/public.json").read_text())["version"]
    expected_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if metadata["Version"] != expected_version:
        raise ValueError("setup wheel version differs from the author source")
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    with tempfile.TemporaryDirectory(prefix="ea-wheel-qualification-") as temporary:
        root = Path(temporary).resolve()
        # Execute exactly the bytes hashed above, rather than a mutable caller path.
        selected = root / wheel.name
        selected.write_bytes(payload)
        uv = _uv(None)
        _protocol_run([str(uv), "venv", "--no-project", "--managed-python", "--python", PYTHON_VERSION,
                       str(root / "environment")], cwd=root, environment=environment, timeout=120)
        binary = root / "environment" / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        _protocol_run([str(uv), "pip", "sync", "--python", str(python), "--require-hashes", "--only-binary=:all:",
                       str(ROOT / "config/runtime-requirements.txt")], cwd=root, environment=environment, timeout=120)
        _protocol_run([str(uv), "pip", "install", "--python", str(python), "--no-deps", str(selected)],
                      cwd=root, environment=environment, timeout=120)
        environment["PATH"] = ""
        exact = _protocol_run([str(python), "-I", "-c", "import platform; print(platform.python_version())"],
                              cwd=root, environment=environment).decode().strip()
        if exact != PYTHON_VERSION:
            raise ValueError("wheel smoke interpreter is not the fixed Python")
        entry = binary / ("ea-setup.exe" if os.name == "nt" else "ea-setup")
        _protocol_run([str(entry), "--help"], cwd=root, environment=environment)
        diagnosed = _protocol_run([str(entry), "doctor", "--agent", "codex", "--target", "unknown", "--json"],
                                  cwd=root, environment=environment, expected_exit_code=2)
        if json.loads(diagnosed).get("status") != "unsupported":
            raise ValueError("wheel doctor did not report unsupported without mutation")
        _protocol_run([str(python), "-I", "-m", "engineering_assistant.cli", "validate", "--require-sources"],
                      cwd=root, environment=environment)
        _protocol_run([str(python), "-I", "-m", "engineering_assistant.cli", "eval"],
                      cwd=root, environment=environment)
    report = {"schema_version": "1", "status": "passed", "python_version": PYTHON_VERSION,
              "canonical_version": canonical, "wheel_filename": wheel.name,
              "wheel_digest": "sha256:" + hashlib.sha256(payload).hexdigest(), "wheel_version": metadata["Version"],
              "checks": {"help": "passed", "doctor": "passed", "source_validation": "passed", "eval": "passed"}}
    return report


def verify(wheel: Path, output: Path) -> dict:
    # Retain the output directory before setup; later path replacement cannot
    # redirect publication into the author tree or another directory identity.
    artifact = _output_directory(output)
    try:
        report = _verify_wheel(wheel)
        artifact.create_immutable_json(report, output.name)
        return report
    finally:
        artifact.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = verify(arguments.wheel, arguments.output)
    print(json.dumps({"status": report["status"], "checks": report["checks"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
