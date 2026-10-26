"""Atomically prepare one verified core for multiple native plugin entries."""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

from ..runtime.artifact_io import ArtifactIO, artifact_fs
from ..runtime.shared_core import MAX_CORE_FILE_BYTES, core_sources, read_core_descriptor, verify_core
from ..runtime.validation import ValidationFailure


def prepare_core(package: Path, storage: ArtifactIO, *, repair: bool = False) -> Path:
    descriptor = read_core_descriptor(package / "engineering-assistant")
    if descriptor is None:
        return package / "engineering-assistant"
    key = descriptor["payload_digest"][7:]
    result = storage.path("cores", key)
    with storage.transaction("shared-core", key):
        storage.ensure_directory("cores")
        if storage.entry_exists("cores", key):
            try:
                verify_core(result, descriptor)
                return result
            except (OSError, ValueError):
                if not repair:
                    raise
                retained = key + "-" + secrets.token_hex(12)
                storage.ensure_directory("retained-cores")
                with storage.open_directory("cores") as src, storage.open_directory("retained-cores") as dst:
                    artifact_fs.rename(key, retained, src_dir_fd=src, dst_dir_fd=dst)
        name = "core-" + secrets.token_hex(12)
        staging = storage.ensure_directory("staging", name)
        source = ArtifactIO(package, ".")
        output = ArtifactIO(staging, ".")
        try:
            manifest = source.read_json_limited(1024 * 1024, "package-manifest.json")[0]
            paths = core_sources(manifest["payload_files"])
            if set(paths) != set(descriptor["payload_files"]):
                raise ValidationFailure("core transport differs from its descriptor")
            for relative, original in paths.items():
                payload = source.read_bytes_limited(MAX_CORE_FILE_BYTES, *original.split("/"))
                if "sha256:" + hashlib.sha256(payload).hexdigest() != descriptor["payload_files"][relative]:
                    raise ValidationFailure("core transport changed during preparation")
                output.write_bytes_exclusive(payload, *relative.split("/"))
            output.write_bytes_exclusive((json.dumps(descriptor, sort_keys=True) + "\n").encode(), "core-manifest.json")
            verify_core(staging, descriptor)
            with storage.open_directory("staging") as src, storage.open_directory("cores") as dst:
                artifact_fs.rename(name, key, src_dir_fd=src, dst_dir_fd=dst)
            verify_core(result, descriptor)
        finally:
            output.close()
            source.close()
            # Failed attempts stay outside the active core. Never overwrite a
            # changed core or recursively clean up another process's files.
    return result
