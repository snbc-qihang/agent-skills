"""Small safe and revision-aware JSON persistence seam for runtime artifacts."""

from __future__ import annotations

import json
import hashlib
import os
import secrets
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .validation import ValidationFailure

try:  # pragma: no cover - Windows fallback is exercised on Windows CI only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None
    import msvcrt  # type: ignore[import-not-found]
else:  # pragma: no cover - name is only used by the Windows branch
    msvcrt = None


class ArtifactConflict(RuntimeError):
    pass


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _is_directory_at(directory_fd: int, relative: str) -> bool:
    descriptor = os.dup(directory_fd)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        for part in Path(relative).parts:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError:
                return False
            os.close(descriptor)
            descriptor = child
        return stat.S_ISDIR(os.fstat(descriptor).st_mode)
    finally:
        os.close(descriptor)


def _is_regular_file_at(directory_fd: int, relative: str) -> bool:
    parent = str(Path(relative).parent)
    name = Path(relative).name
    descriptor = os.dup(directory_fd)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        if parent != ".":
            for part in Path(parent).parts:
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except OSError:
                    return False
                os.close(descriptor)
                descriptor = child
        try:
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except OSError:
            return False
        return stat.S_ISREG(metadata.st_mode)
    finally:
        os.close(descriptor)


def _layout_kind_fd(directory_fd: int) -> str | None:
    author = all(
        _is_directory_at(directory_fd, relative)
        for relative in ("catalog", "skills", "schemas", "src/engineering_assistant")
    )
    compiled_engine = all(
        _is_directory_at(directory_fd, relative)
        for relative in ("catalog", "schemas", "runtime/engineering_assistant")
    )
    compiled_package = _is_regular_file_at(
        directory_fd, "package-manifest.json"
    ) and _is_directory_at(directory_fd, "engineering-assistant/runtime/engineering_assistant")
    if author:
        return "author"
    if compiled_engine or compiled_package:
        return "installed"
    return None


def _layout_kind_path(root: Path) -> str | None:
    author = all(
        path.is_dir()
        for path in (
            root / "catalog",
            root / "skills",
            root / "schemas",
            root / "src/engineering_assistant",
        )
    )
    compiled_engine = all(
        path.is_dir()
        for path in (
            root / "catalog",
            root / "schemas",
            root / "runtime/engineering_assistant",
        )
    )
    compiled_package = (
        (root / "package-manifest.json").is_file()
        and (root / "engineering-assistant/runtime/engineering_assistant").is_dir()
    )
    if author:
        return "author"
    if compiled_engine or compiled_package:
        return "installed"
    return None


def _protected_layout_fd(directory_fd: int) -> bool:
    return _layout_kind_fd(directory_fd) is not None


def _protected_layout_path(root: Path) -> bool:
    return _layout_kind_path(root) is not None


def assert_runtime_artifact_target(
    project_root: Path | str,
    schema_root: Path | str,
) -> None:
    """Keep mutable run evidence out of author and installed plugin trees."""

    project = Path(project_root).resolve()
    schemas = Path(schema_root).resolve()

    def protected_layout(root: Path) -> bool:
        author = all(
            path.is_dir()
            for path in (
                root / "catalog",
                root / "skills",
                root / "schemas",
                root / "src/engineering_assistant",
            )
        )
        compiled_engine = all(
            path.is_dir()
            for path in (
                root / "catalog",
                root / "schemas",
                root / "runtime/engineering_assistant",
            )
        )
        compiled_package = (
            (root / "package-manifest.json").is_file()
            and (root / "engineering-assistant/runtime/engineering_assistant").is_dir()
        )
        return author or compiled_engine or compiled_package

    project_layouts = (project, *project.parents)
    engine_root = schemas.parent
    protected_schema_roots = tuple(
        root
        for root in (engine_root, engine_root.parent)
        if protected_layout(root)
    )
    project_is_protected = any(protected_layout(root) for root in project_layouts)
    project_uses_schema_tree = any(
        project == root or root in project.parents for root in protected_schema_roots
    )
    if project_is_protected or project_uses_schema_tree:
        raise ValidationFailure(
            "runtime artifacts cannot target the engineering-assistant author or "
            "installed plugin tree"
        )


class ArtifactIO:
    """Keeps artifact writes inside a project root and serializes cooperating writers."""

    def __init__(
        self,
        project_root: Path | str,
        artifact_root: Path | str,
        *,
        lock_timeout_seconds: float | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        root_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            root_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            root_flags |= os.O_NOFOLLOW
        self._root_fd = os.open(self.project_root, root_flags)
        root_metadata = os.fstat(self._root_fd)
        if not stat.S_ISDIR(root_metadata.st_mode):
            os.close(self._root_fd)
            raise ValidationFailure("artifact project root is not a directory")
        root = Path(artifact_root)
        self.artifact_root = root if root.is_absolute() else self.project_root / root
        if lock_timeout_seconds is not None and lock_timeout_seconds <= 0:
            raise ValueError("lock timeout must be positive")
        self.lock_timeout_seconds = lock_timeout_seconds

    @classmethod
    def from_open_directory_fd(
        cls,
        project_root: Path | str,
        directory_fd: int,
        *,
        lock_timeout_seconds: float | None = None,
    ) -> "ArtifactIO":
        """Bind an ArtifactIO instance to an already-open directory identity."""

        metadata = os.fstat(directory_fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValidationFailure("artifact project root is not a directory")
        instance = cls.__new__(cls)
        instance.project_root = Path(project_root).resolve()
        instance.artifact_root = instance.project_root
        instance._root_fd = os.dup(directory_fd)
        instance.lock_timeout_seconds = lock_timeout_seconds
        return instance

    def close(self) -> None:
        descriptor = getattr(self, "_root_fd", None)
        if descriptor is not None:
            os.close(descriptor)
            self._root_fd = None

    def __del__(self) -> None:  # pragma: no cover - interpreter shutdown is nondeterministic
        try:
            self.close()
        except Exception:
            pass

    def path(self, *parts: str) -> Path:
        target = self.artifact_root.joinpath(*parts)
        self._assert_safe(target)
        return target

    def assert_runtime_target(
        self,
        schema_root: Path | str,
        *,
        allow_author_repository: bool = False,
    ) -> None:
        """Validate the already-opened project root instead of a mutable path."""

        schemas = Path(schema_root).resolve()
        protected_inodes: set[tuple[int, int]] = set()
        for candidate in (schemas.parent, schemas.parent.parent):
            if not candidate.exists() or not _protected_layout_path(candidate):
                continue
            metadata = candidate.stat()
            protected_inodes.add((metadata.st_dev, metadata.st_ino))

        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.dup(self._root_fd)
        try:
            while True:
                metadata = os.fstat(descriptor)
                layout_kind = _layout_kind_fd(descriptor)
                protected_schema = (metadata.st_dev, metadata.st_ino) in protected_inodes
                if (
                    layout_kind == "installed"
                    or (layout_kind == "author" and not allow_author_repository)
                    or (protected_schema and not allow_author_repository)
                ):
                    raise ValidationFailure(
                        "runtime artifacts cannot target the engineering-assistant "
                        "author or installed plugin tree"
                    )
                parent = os.open("..", flags, dir_fd=descriptor)
                parent_metadata = os.fstat(parent)
                if (
                    parent_metadata.st_dev,
                    parent_metadata.st_ino,
                ) == (metadata.st_dev, metadata.st_ino):
                    os.close(parent)
                    break
                os.close(descriptor)
                descriptor = parent
        finally:
            os.close(descriptor)

    def regular_file_exists(self, *parts: str) -> bool:
        """Check existence through the anchored project root without following links."""

        path = self.path(*parts)
        try:
            parent_fd = self._open_directory_fd(path.parent)
        except FileNotFoundError:
            return False
        try:
            try:
                metadata = os.stat(
                    path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return False
            return stat.S_ISREG(metadata.st_mode)
        finally:
            os.close(parent_fd)

    def entry_exists(self, *parts: str) -> bool:
        """Check for any non-followed directory entry through the anchored root."""

        path = self.path(*parts)
        try:
            parent_fd = self._open_directory_fd(path.parent)
        except FileNotFoundError:
            return False
        try:
            try:
                os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            return True
        finally:
            os.close(parent_fd)

    @contextmanager
    def open_directory(self, *parts: str) -> Iterator[int]:
        """Yield an anchored descriptor for a real directory."""

        descriptor = self._open_directory_fd(self.path(*parts))
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    def create_directory_exclusive(self, *parts: str) -> Path:
        path = self.path(*parts)
        parent_fd = self._ensure_directory_fd(path.parent)
        try:
            os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
            return path
        finally:
            os.close(parent_fd)

    def ensure_directory(self, *parts: str) -> Path:
        """Create a directory path through the anchored root if needed."""

        path = self.path(*parts)
        descriptor = self._ensure_directory_fd(path)
        os.close(descriptor)
        return path

    def create_directory_exclusive_open(
        self, *parts: str
    ) -> tuple[Path, int, os.stat_result]:
        """Create a directory and return a descriptor retained by the caller."""

        path = self.path(*parts)
        parent_fd = self._ensure_directory_fd(path.parent)
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
            descriptor = os.open(path.name, flags, dir_fd=parent_fd)
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(descriptor)
                raise ValidationFailure("created artifact directory changed identity")
            os.fsync(parent_fd)
            return path, descriptor, metadata
        finally:
            os.close(parent_fd)

    def write_bytes_exclusive(
        self,
        payload: bytes,
        *parts: str,
        mode: int = 0o600,
    ) -> Path:
        path = self.path(*parts)
        parent_fd = self._ensure_directory_fd(path.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path.name, flags, mode, dir_fd=parent_fd)
            try:
                offset = 0
                while offset < len(payload):
                    offset += os.write(descriptor, payload[offset:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(parent_fd)
            return path
        finally:
            os.close(parent_fd)

    def chmod_regular_file(self, mode: int, *parts: str) -> None:
        """Change one anchored regular file mode without following links."""

        path = self.path(*parts)
        parent_fd = self._open_directory_fd(path.parent)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent_fd)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ValidationFailure("artifact is not a regular file")
                os.fchmod(descriptor, mode)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def copy_contents_to(
        self,
        destination: "ArtifactIO",
        *,
        max_file_bytes: int,
        max_entries: int | None = None,
        max_total_bytes: int | None = None,
        ignored_names: frozenset[str] = frozenset(),
        ignored_suffixes: tuple[str, ...] = (),
    ) -> None:
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if max_entries is not None and max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if max_total_bytes is not None and max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        budget = {"entries": 0, "bytes": 0}
        self._copy_directory_contents(
            self._root_fd,
            destination,
            (),
            max_file_bytes,
            max_entries,
            max_total_bytes,
            budget,
            ignored_names,
            ignored_suffixes,
        )

    def sha256_file_digests(
        self,
        *,
        exclude: frozenset[str] = frozenset(),
        max_file_bytes: int,
        max_entries: int | None = None,
        max_total_bytes: int | None = None,
    ) -> dict[str, str]:
        """Hash a bounded regular-file tree through the anchored root FD."""

        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if max_entries is not None and max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if max_total_bytes is not None and max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        result: dict[str, str] = {}
        budget = {"entries": 0, "bytes": 0}
        self._sha256_directory_contents(
            self._root_fd,
            (),
            result,
            exclude,
            max_file_bytes,
            max_entries,
            max_total_bytes,
            budget,
        )
        return result

    def child_directory_matches(
        self,
        name: str,
        expected_metadata: os.stat_result,
    ) -> bool:
        if Path(name).name != name:
            raise ValidationFailure("directory identity check requires a simple child name")
        root_fd = self._open_directory_fd(self.artifact_root)
        try:
            try:
                current = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            return stat.S_ISDIR(current.st_mode) and _same_identity(
                current,
                expected_metadata,
            )
        finally:
            os.close(root_fd)

    def rename_child_directory(self, source_name: str, target_name: str) -> Path:
        if Path(source_name).name != source_name or Path(target_name).name != target_name:
            raise ValidationFailure("directory rename requires simple child names")
        source = self.path(source_name)
        target = self.path(target_name)
        root_fd = self._open_directory_fd(self.artifact_root)
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            child_fd = os.open(source.name, flags, dir_fd=root_fd)
            os.close(child_fd)
            try:
                os.stat(target.name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(target)
            os.rename(
                source.name,
                target.name,
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
            os.fsync(root_fd)
            return target
        finally:
            os.close(root_fd)

    def rename_child_directory_if_matches(
        self,
        source_name: str,
        target_name: str,
        expected_metadata: os.stat_result,
    ) -> Path:
        if Path(source_name).name != source_name or Path(target_name).name != target_name:
            raise ValidationFailure("directory rename requires simple child names")
        root_fd = self._open_directory_fd(self.artifact_root)
        try:
            current = os.stat(source_name, dir_fd=root_fd, follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or not _same_identity(
                current, expected_metadata
            ):
                raise ValidationFailure("staging directory identity changed")
            try:
                os.stat(target_name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(self.path(target_name))
            os.rename(
                source_name,
                target_name,
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
            published = os.stat(target_name, dir_fd=root_fd, follow_symlinks=False)
            if not _same_identity(published, expected_metadata):
                raise ValidationFailure("published directory identity changed")
            os.fsync(root_fd)
            return self.path(target_name)
        finally:
            os.close(root_fd)

    def remove_all_contents(self) -> None:
        """Remove only entries reachable from this instance's anchored root FD."""

        self._remove_directory_contents(self._root_fd)
        os.fsync(self._root_fd)

    def remove_child_directory_if_matches(
        self,
        name: str,
        expected_metadata: os.stat_result,
    ) -> bool:
        if Path(name).name != name:
            raise ValidationFailure("directory removal requires a simple child name")
        root_fd = self._open_directory_fd(self.artifact_root)
        try:
            try:
                current = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            if not stat.S_ISDIR(current.st_mode) or not _same_identity(
                current, expected_metadata
            ):
                return False
            try:
                os.rmdir(name, dir_fd=root_fd)
            except OSError:
                return False
            os.fsync(root_fd)
            return True
        finally:
            os.close(root_fd)

    def remove_tree(self, *parts: str) -> bool:
        """Remove one anchored directory tree without following any links."""

        path = self.path(*parts)
        parent_fd = self._open_directory_fd(path.parent)
        try:
            try:
                self._remove_tree_at(parent_fd, path.name)
            except FileNotFoundError:
                return False
            os.fsync(parent_fd)
            return True
        finally:
            os.close(parent_fd)

    def read_json(self, *parts: str) -> dict:
        path = self.path(*parts)
        parent_fd = self._open_directory_fd(path.parent)
        try:
            return self._read_json_at(parent_fd, path.name)
        finally:
            os.close(parent_fd)

    def read_bytes_limited(self, max_bytes: int, *parts: str) -> bytes:
        """Read one regular file through an anchored directory descriptor."""

        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        path = self.path(*parts)
        parent_fd = self._open_directory_fd(path.parent)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            try:
                descriptor = os.open(path.name, flags, dir_fd=parent_fd)
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise ValidationFailure("artifact is not a safe regular file") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValidationFailure("artifact is not a regular file")
                if metadata.st_size > max_bytes:
                    raise ValidationFailure("artifact exceeds its size limit")
                chunks = []
                remaining = max_bytes + 1
                while remaining:
                    chunk = os.read(descriptor, min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                payload = b"".join(chunks)
                if len(payload) > max_bytes:
                    raise ValidationFailure("artifact exceeds its size limit")
                return payload
            finally:
                os.close(descriptor)
        finally:
            os.close(parent_fd)

    def read_json_limited(
        self,
        max_bytes: int,
        *parts: str,
    ) -> tuple[dict, bytes]:
        """Read and decode one bounded JSON object from the same anchored bytes."""

        raw = self.read_bytes_limited(max_bytes, *parts)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationFailure("artifact contains invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValidationFailure("artifact JSON must be an object")
        return payload, raw

    @staticmethod
    def canonical_json_bytes(payload: dict) -> bytes:
        """Return the exact byte representation used for artifact writes."""

        return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )

    def create_immutable_json(
        self,
        payload: dict,
        *parts: str,
        existing_max_bytes: int | None = None,
    ) -> Path:
        return self.create_immutable_json_with_status(
            payload,
            *parts,
            existing_max_bytes=existing_max_bytes,
        )[0]

    def create_immutable_json_with_status(
        self,
        payload: dict,
        *parts: str,
        existing_max_bytes: int | None = None,
    ) -> tuple[Path, bool]:
        if existing_max_bytes is not None and existing_max_bytes <= 0:
            raise ValueError("existing_max_bytes must be positive")
        path = self.path(*parts)
        parent_fd = self._ensure_directory_fd(path.parent)
        try:
            with self._lock_fd(parent_fd):
                try:
                    current = self._read_json_at(
                        parent_fd,
                        path.name,
                        max_bytes=existing_max_bytes,
                    )
                except FileNotFoundError:
                    current = None
                if current is not None:
                    if current != payload:
                        raise ArtifactConflict(
                            f"immutable artifact already exists with different content: {path}"
                        )
                    return path, False
                temporary = self._write_temporary_at(parent_fd, payload)
                try:
                    try:
                        os.link(
                            temporary,
                            path.name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                        created = True
                    except FileExistsError:
                        created = False
                        if self._read_json_at(
                            parent_fd,
                            path.name,
                            max_bytes=existing_max_bytes,
                        ) != payload:
                            raise ArtifactConflict(
                                "immutable artifact already exists with different "
                                f"content: {path}"
                            )
                    os.fsync(parent_fd)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                return path, created
        finally:
            os.close(parent_fd)

    def replace_json_cas(
        self,
        payload: dict,
        *parts: str,
        expected_revision: int,
        revision_key: str = "revision",
    ) -> Path:
        path = self.path(*parts)
        parent_fd = self._ensure_directory_fd(path.parent)
        try:
            with self._lock_fd(parent_fd):
                current = self._read_json_at(parent_fd, path.name)
                if current.get(revision_key) != expected_revision:
                    raise ArtifactConflict(
                        f"artifact revision changed: expected {expected_revision}, "
                        f"found {current.get(revision_key)}"
                    )
                temporary = self._write_temporary_at(parent_fd, payload)
                try:
                    os.replace(
                        temporary,
                        path.name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                    os.fsync(parent_fd)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                return path
        finally:
            os.close(parent_fd)

    @contextmanager
    def transaction(self, *parts: str) -> Iterator[None]:
        directory = self.path(*parts)
        directory_fd = self._ensure_directory_fd(directory)
        try:
            with self._lock_fd(directory_fd):
                yield
        finally:
            os.close(directory_fd)

    def delete_regular_file(self, *parts: str) -> bool:
        path = self.path(*parts)
        parent_fd = self._open_directory_fd(path.parent)
        try:
            with self._lock_fd(parent_fd):
                try:
                    metadata = os.stat(
                        path.name,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    return False
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValidationFailure("artifact is not a regular file")
                os.unlink(path.name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                return True
        finally:
            os.close(parent_fd)

    def delete_regular_file_if_unchanged(
        self,
        *parts: str,
        expected_metadata: os.stat_result,
        older_than: float,
    ) -> bool:
        """Delete a stale file only if it is still the file that was inspected."""

        path = self.path(*parts)
        parent_fd = self._open_directory_fd(path.parent)
        expected_identity = (
            expected_metadata.st_dev,
            expected_metadata.st_ino,
            expected_metadata.st_mtime_ns,
            expected_metadata.st_size,
        )
        try:
            with self._lock_fd(parent_fd):
                try:
                    current = os.stat(
                        path.name,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    return False
                if not stat.S_ISREG(current.st_mode):
                    raise ValidationFailure("artifact is not a regular file")
                current_identity = (
                    current.st_dev,
                    current.st_ino,
                    current.st_mtime_ns,
                    current.st_size,
                )
                if current_identity != expected_identity or current.st_mtime >= older_than:
                    return False
                os.unlink(path.name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                return True
        finally:
            os.close(parent_fd)

    def remove_empty_directory(self, *parts: str) -> bool:
        """Remove an artifact directory containing no data files.

        Callers that create files in this directory must hold a shared parent
        lifecycle lock while invoking this operation.
        """

        path = self.path(*parts)
        parent_fd = self._open_directory_fd(path.parent)
        try:
            try:
                directory_fd = self._open_directory_fd(path)
            except FileNotFoundError:
                return False
            try:
                with self._lock_fd(directory_fd):
                    entries = os.listdir(directory_fd)
                    if any(name != ".artifact.lock" for name in entries):
                        return False
                    try:
                        os.unlink(".artifact.lock", dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
                    os.fsync(directory_fd)
                    try:
                        os.rmdir(path.name, dir_fd=parent_fd)
                    except (FileNotFoundError, OSError):
                        return False
                    os.fsync(parent_fd)
                    return True
            finally:
                os.close(directory_fd)
        finally:
            os.close(parent_fd)

    def _open_directory_fd(self, directory: Path) -> int:
        self._assert_safe(directory)
        relative = Path(os.path.abspath(directory)).relative_to(self.project_root)
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.dup(self._root_fd)
        try:
            for part in relative.parts:
                child = os.open(part, flags, dir_fd=descriptor)
                metadata = os.fstat(child)
                if not stat.S_ISDIR(metadata.st_mode):
                    os.close(child)
                    raise ValidationFailure("artifact directory is not a real directory")
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def _ensure_directory_fd(self, directory: Path) -> int:
        self._assert_safe(directory)
        relative = Path(os.path.abspath(directory)).relative_to(self.project_root)
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.dup(self._root_fd)
        try:
            for part in relative.parts:
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(part, flags, dir_fd=descriptor)
                metadata = os.fstat(child)
                if not stat.S_ISDIR(metadata.st_mode):
                    os.close(child)
                    raise ValidationFailure("artifact directory is not a real directory")
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    @classmethod
    def _remove_tree_at(cls, parent_fd: int, name: str) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        directory_fd = os.open(name, flags, dir_fd=parent_fd)
        try:
            for child_name in os.listdir(directory_fd):
                metadata = os.stat(
                    child_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if stat.S_ISDIR(metadata.st_mode):
                    cls._remove_tree_at(directory_fd, child_name)
                elif stat.S_ISREG(metadata.st_mode):
                    os.unlink(child_name, dir_fd=directory_fd)
                else:
                    raise ValidationFailure("artifact tree contains an unsafe entry")
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.rmdir(name, dir_fd=parent_fd)

    @classmethod
    def _remove_directory_contents(cls, directory_fd: int) -> None:
        for child_name in os.listdir(directory_fd):
            metadata = os.stat(
                child_name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            if stat.S_ISDIR(metadata.st_mode):
                flags = os.O_RDONLY
                if hasattr(os, "O_DIRECTORY"):
                    flags |= os.O_DIRECTORY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                child_fd = os.open(child_name, flags, dir_fd=directory_fd)
                try:
                    cls._remove_directory_contents(child_fd)
                finally:
                    os.close(child_fd)
                current = os.stat(
                    child_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if not _same_identity(current, metadata):
                    raise ValidationFailure("artifact child directory identity changed")
                os.rmdir(child_name, dir_fd=directory_fd)
            elif stat.S_ISREG(metadata.st_mode):
                os.unlink(child_name, dir_fd=directory_fd)
            else:
                raise ValidationFailure("artifact tree contains an unsafe entry")

    @classmethod
    def _copy_directory_contents(
        cls,
        source_fd: int,
        destination: "ArtifactIO",
        relative: tuple[str, ...],
        max_file_bytes: int,
        max_entries: int | None,
        max_total_bytes: int | None,
        budget: dict[str, int],
        ignored_names: frozenset[str],
        ignored_suffixes: tuple[str, ...],
    ) -> None:
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        file_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            file_flags |= os.O_NONBLOCK
        child_names: list[str] = []
        with os.scandir(source_fd) as entries:
            for entry in entries:
                budget["entries"] += 1
                if max_entries is not None and budget["entries"] > max_entries:
                    raise ValidationFailure("artifact copy source exceeds its entry limit")
                child_names.append(entry.name)
        for child_name in sorted(child_names):
            if child_name in ignored_names or child_name.endswith(ignored_suffixes):
                continue
            metadata = os.stat(
                child_name,
                dir_fd=source_fd,
                follow_symlinks=False,
            )
            child_relative = (*relative, child_name)
            if stat.S_ISDIR(metadata.st_mode):
                child_fd = os.open(child_name, directory_flags, dir_fd=source_fd)
                try:
                    cls._copy_directory_contents(
                        child_fd,
                        destination,
                        child_relative,
                        max_file_bytes,
                        max_entries,
                        max_total_bytes,
                        budget,
                        ignored_names,
                        ignored_suffixes,
                    )
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(metadata.st_mode):
                remaining_total = (
                    max_file_bytes
                    if max_total_bytes is None
                    else max_total_bytes - budget["bytes"]
                )
                allowed_bytes = min(max_file_bytes, remaining_total)
                if allowed_bytes < 0 or metadata.st_size > allowed_bytes:
                    raise ValidationFailure("artifact copy source exceeds its size limit")
                descriptor = os.open(child_name, file_flags, dir_fd=source_fd)
                try:
                    opened_metadata = os.fstat(descriptor)
                    if not stat.S_ISREG(opened_metadata.st_mode) or not _same_identity(
                        metadata,
                        opened_metadata,
                    ):
                        raise ValidationFailure("artifact copy source is unsafe")
                    chunks = []
                    remaining = allowed_bytes + 1
                    while remaining:
                        chunk = os.read(descriptor, min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    payload = b"".join(chunks)
                    if len(payload) > allowed_bytes:
                        raise ValidationFailure(
                            "artifact copy source exceeds its size limit"
                        )
                finally:
                    os.close(descriptor)
                destination.write_bytes_exclusive(
                    payload,
                    *child_relative,
                    mode=stat.S_IMODE(metadata.st_mode),
                )
                budget["bytes"] += len(payload)
            else:
                raise ValidationFailure("artifact copy source is unsafe")

    @classmethod
    def _sha256_directory_contents(
        cls,
        source_fd: int,
        relative: tuple[str, ...],
        result: dict[str, str],
        exclude: frozenset[str],
        max_file_bytes: int,
        max_entries: int | None,
        max_total_bytes: int | None,
        budget: dict[str, int],
    ) -> None:
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        file_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            file_flags |= os.O_NONBLOCK
        child_names: list[str] = []
        with os.scandir(source_fd) as entries:
            for entry in entries:
                budget["entries"] += 1
                if max_entries is not None and budget["entries"] > max_entries:
                    raise ValidationFailure("artifact hash source exceeds its entry limit")
                child_names.append(entry.name)
        for child_name in sorted(child_names):
            metadata = os.stat(
                child_name,
                dir_fd=source_fd,
                follow_symlinks=False,
            )
            child_relative = (*relative, child_name)
            relative_name = "/".join(child_relative)
            if stat.S_ISDIR(metadata.st_mode):
                child_fd = os.open(child_name, directory_flags, dir_fd=source_fd)
                try:
                    cls._sha256_directory_contents(
                        child_fd,
                        child_relative,
                        result,
                        exclude,
                        max_file_bytes,
                        max_entries,
                        max_total_bytes,
                        budget,
                    )
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(metadata.st_mode):
                remaining_total = (
                    max_file_bytes
                    if max_total_bytes is None
                    else max_total_bytes - budget["bytes"]
                )
                allowed_bytes = min(max_file_bytes, remaining_total)
                if (
                    relative_name in exclude
                    or allowed_bytes < 0
                    or metadata.st_size > allowed_bytes
                ):
                    if relative_name in exclude:
                        continue
                    raise ValidationFailure("artifact hash source exceeds its size limit")
                descriptor = os.open(child_name, file_flags, dir_fd=source_fd)
                digest = hashlib.sha256()
                total = 0
                try:
                    opened_metadata = os.fstat(descriptor)
                    if not stat.S_ISREG(opened_metadata.st_mode) or not _same_identity(
                        metadata,
                        opened_metadata,
                    ):
                        raise ValidationFailure("artifact hash source is unsafe")
                    while True:
                        chunk = os.read(descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > allowed_bytes:
                            raise ValidationFailure(
                                "artifact hash source exceeds its size limit"
                            )
                        digest.update(chunk)
                finally:
                    os.close(descriptor)
                budget["bytes"] += total
                result[relative_name] = "sha256:" + digest.hexdigest()
            else:
                raise ValidationFailure("artifact hash source is unsafe")

    def _assert_safe(self, target: Path) -> None:
        lexical = Path(os.path.abspath(target))
        if not lexical.is_relative_to(self.project_root):
            raise ValidationFailure("artifact path escapes the target project")
        current = self.project_root
        relative = lexical.relative_to(self.project_root)
        for part in relative.parts:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise ValidationFailure(f"artifact path contains symlink component: {current}")

    @staticmethod
    def _read_json_at(
        directory_fd: int,
        name: str,
        *,
        max_bytes: int | None = None,
    ) -> dict:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ValidationFailure("artifact is not a safe regular file") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValidationFailure("artifact is not a regular file")
            if max_bytes is not None and metadata.st_size > max_bytes:
                raise ValidationFailure("artifact exceeds its size limit")
            chunks = []
            remaining = None if max_bytes is None else max_bytes + 1
            while True:
                if remaining == 0:
                    break
                chunk = os.read(
                    descriptor,
                    1024 * 1024 if remaining is None else min(1024 * 1024, remaining),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
            raw = b"".join(chunks)
            if max_bytes is not None and len(raw) > max_bytes:
                raise ValidationFailure("artifact exceeds its size limit")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationFailure("artifact contains invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ValidationFailure("artifact JSON must be an object")
            return payload
        finally:
            os.close(descriptor)

    @staticmethod
    def _write_temporary_at(directory_fd: int, payload: dict) -> str:
        encoded = ArtifactIO.canonical_json_bytes(payload)
        for _attempt in range(16):
            name = f".artifact-{secrets.token_hex(12)}.json"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
                break
            except FileExistsError:
                continue
        else:
            raise ValidationFailure("could not allocate artifact staging file")
        try:
            offset = 0
            while offset < len(encoded):
                offset += os.write(descriptor, encoded[offset:])
            os.fsync(descriptor)
            return name
        except BaseException:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(descriptor)

    @contextmanager
    def _lock_fd(self, directory_fd: int) -> Iterator[None]:
        flags = os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(".artifact.lock", flags, dir_fd=directory_fd)
        except FileNotFoundError:
            try:
                descriptor = os.open(
                    ".artifact.lock",
                    os.O_RDWR | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                descriptor = os.open(".artifact.lock", flags, dir_fd=directory_fd)
        except OSError as exc:
            raise ValidationFailure("artifact lock is not a safe regular file") from exc
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValidationFailure("artifact lock is not a regular file")
        acquired = False
        try:
            self._acquire_lock(descriptor)
            acquired = True
            yield
        finally:
            if acquired and fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif acquired and msvcrt is not None:  # pragma: no cover - Windows only
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            os.close(descriptor)

    def _acquire_lock(self, descriptor: int) -> None:
        if self.lock_timeout_seconds is None:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            elif msvcrt is not None:  # pragma: no cover - Windows only
                self._prepare_windows_lock(descriptor)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            return

        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt is not None:  # pragma: no cover - Windows only
                    self._prepare_windows_lock(descriptor)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                return
            except (BlockingIOError, OSError) as exc:
                if time.monotonic() >= deadline:
                    raise ValidationFailure("artifact lock is busy") from exc
                time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))

    @staticmethod
    def _prepare_windows_lock(descriptor: int) -> None:  # pragma: no cover - Windows only
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)
