"""Small safe and revision-aware JSON persistence seam for runtime artifacts."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .validation import ValidationFailure, load_json

try:  # pragma: no cover - Windows fallback is exercised on Windows CI only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None
    import msvcrt  # type: ignore[import-not-found]
else:  # pragma: no cover - name is only used by the Windows branch
    msvcrt = None


class ArtifactConflict(RuntimeError):
    pass


class ArtifactIO:
    """Keeps artifact writes inside a project root and serializes cooperating writers."""

    def __init__(self, project_root: Path | str, artifact_root: Path | str) -> None:
        self.project_root = Path(project_root).resolve()
        root = Path(artifact_root)
        self.artifact_root = root if root.is_absolute() else self.project_root / root

    def path(self, *parts: str) -> Path:
        target = self.artifact_root.joinpath(*parts)
        self._assert_safe(target)
        return target

    def read_json(self, *parts: str) -> dict:
        path = self.path(*parts)
        self._assert_regular_file(path)
        return load_json(path)

    def create_immutable_json(self, payload: dict, *parts: str) -> Path:
        return self.create_immutable_json_with_status(payload, *parts)[0]

    def create_immutable_json_with_status(
        self, payload: dict, *parts: str
    ) -> tuple[Path, bool]:
        path = self.path(*parts)
        self._ensure_safe_directory(path.parent)
        with self._lock(path.parent):
            self._assert_safe(path)
            if path.exists():
                self._assert_regular_file(path)
                if load_json(path) != payload:
                    raise ArtifactConflict(f"immutable artifact already exists with different content: {path}")
                return path, False
            temporary = self._write_temporary(path.parent, payload)
            try:
                try:
                    os.link(temporary, path, follow_symlinks=False)
                    created = True
                except FileExistsError:
                    created = False
                    self._assert_regular_file(path)
                    if load_json(path) != payload:
                        raise ArtifactConflict(
                            f"immutable artifact already exists with different content: {path}"
                        )
                self._fsync_directory(path.parent)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            return path, created

    def replace_json_cas(
        self,
        payload: dict,
        *parts: str,
        expected_revision: int,
        revision_key: str = "revision",
    ) -> Path:
        path = self.path(*parts)
        self._ensure_safe_directory(path.parent)
        with self._lock(path.parent):
            self._assert_safe(path)
            self._assert_regular_file(path)
            current = load_json(path)
            if current.get(revision_key) != expected_revision:
                raise ArtifactConflict(
                    f"artifact revision changed: expected {expected_revision}, "
                    f"found {current.get(revision_key)}"
                )
            temporary = self._write_temporary(path.parent, payload)
            try:
                os.replace(temporary, path)
                self._fsync_directory(path.parent)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            return path

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

    def _ensure_safe_directory(self, directory: Path) -> None:
        self._assert_safe(directory)
        relative = Path(os.path.abspath(directory)).relative_to(self.project_root)
        current = self.project_root
        for part in relative.parts:
            current = current / part
            try:
                current.mkdir()
            except FileExistsError:
                pass
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ValidationFailure(f"artifact directory is not a real directory: {current}")

    @staticmethod
    def _assert_regular_file(path: Path) -> None:
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise FileNotFoundError(path) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValidationFailure(f"artifact is not a regular file: {path}")

    @contextmanager
    def _lock(self, directory: Path) -> Iterator[None]:
        lock_path = directory / ".artifact.lock"
        try:
            lock_metadata = lock_path.lstat()
        except FileNotFoundError:
            lock_metadata = None
        if lock_metadata is not None and (
            stat.S_ISLNK(lock_metadata.st_mode)
            or not stat.S_ISREG(lock_metadata.st_mode)
        ):
            raise ValidationFailure(
                f"artifact lock is not a safe regular file: {lock_path}"
            )
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise ValidationFailure(f"artifact lock is not a safe regular file: {lock_path}") from exc
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(descriptor)
            raise ValidationFailure(f"artifact lock is not a regular file: {lock_path}")
        try:
            opened_metadata = lock_path.lstat()
        except FileNotFoundError:
            os.close(descriptor)
            raise ValidationFailure(f"artifact lock disappeared while opening: {lock_path}")
        if stat.S_ISLNK(opened_metadata.st_mode) or (
            opened_metadata.st_dev,
            opened_metadata.st_ino,
        ) != (metadata.st_dev, metadata.st_ino):
            os.close(descriptor)
            raise ValidationFailure(f"artifact lock changed while opening: {lock_path}")
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            elif msvcrt is not None:  # pragma: no cover - Windows only
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows only
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            os.close(descriptor)

    @staticmethod
    def _write_temporary(directory: Path, payload: dict) -> Path:
        descriptor, temporary = tempfile.mkstemp(prefix=".artifact-", suffix=".json", dir=directory)
        path = Path(temporary)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            return path
        except BaseException:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError:  # pragma: no cover - unsupported platform/filesystem
            return
        try:
            os.fsync(descriptor)
        except OSError:  # pragma: no cover
            pass
        finally:
            os.close(descriptor)
