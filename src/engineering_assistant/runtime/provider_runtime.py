"""Pinned, read-only execution seam for optional capability providers."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .catalog import Catalog
from .model import CapabilityProviderSpec, ProviderInvocation, ProviderResult
from .validation import ValidationFailure, load_json, validate_instance


MAX_PROVIDER_FILES = 1000
MAX_PROVIDER_ENTRIES = 1500
MAX_PROVIDER_BYTES = 64 * 1024 * 1024
MAX_PROVIDER_DEPTH = 12
MAX_OUTPUT_BYTES = 128 * 1024
PROVIDER_ROOT_ENV = "ENGINEERING_ASSISTANT_UI_UX_PRO_MAX_ROOT"


class ProviderExecutor:
    """Selects one provider, verifies its pinned bundle, and contains failures."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.input_schema = load_json(
            catalog.root / "schemas/provider-invocation.schema.json"
        )
        self.output_schema = load_json(
            catalog.root / "schemas/provider-result.schema.json"
        )

    def invoke(
        self,
        invocation: ProviderInvocation,
        *,
        provider_root: Path | str | None,
        denied_roots: list[Path | str] | None = None,
    ) -> ProviderResult:
        validate_instance(invocation.to_dict(), self.input_schema, "provider-invocation")
        provider = self.catalog.provider_for_capability(invocation.capability_id)
        if provider is None:
            raise ValidationFailure(
                f"no provider supplies capability {invocation.capability_id}"
            )
        if provider.mode != "external_cli":
            return self._fallback(
                invocation, provider, "selected capability has no external provider"
            )
        if provider.id != "ui-ux-pro-max":
            return self._fallback(
                invocation, provider, f"no runtime adapter is registered for {provider.id}"
            )
        provider_root = provider_root or os.environ.get(PROVIDER_ROOT_ENV)
        if provider_root is None:
            return self._fallback(
                invocation,
                provider,
                "optional provider bundle is not configured; use the native provider",
            )
        actual_integrity = None
        expected_integrity = provider.source.integrity if provider.source else None
        try:
            bundle = self._bundle_root(Path(provider_root))
            self._validate_layout(bundle)
            with tempfile.TemporaryDirectory(prefix="ea-provider-") as temporary:
                sandbox_root = Path(temporary).resolve()
                snapshot = sandbox_root / "bundle"
                work = sandbox_root / "work"
                snapshot.mkdir()
                work.mkdir()
                actual_integrity = self._snapshot_integrity(bundle, snapshot)
                if actual_integrity != expected_integrity:
                    raise ValidationFailure(
                        "provider bundle integrity does not match the pinned catalog source"
                    )
                output = self._run_ui_ux_pro_max(
                    provider, invocation, snapshot, work, denied_roots or []
                )
            result = ProviderResult(
                invocation_id=invocation.invocation_id,
                invocation_digest=self.invocation_digest(invocation),
                requested_provider_id=provider.id,
                provider_id=provider.id,
                capability_id=invocation.capability_id,
                status="completed",
                output=output,
                trust_level="untrusted_advisory",
                source_revision=provider.source.revision if provider.source else None,
                expected_source_integrity=expected_integrity,
                observed_source_integrity=actual_integrity,
                observed_at=datetime.now(timezone.utc).isoformat(),
                next_action="review_advisory",
                warning=None,
                fallback_provider_id=provider.fallback_provider_id,
            )
        except (OSError, subprocess.SubprocessError, ValidationFailure) as exc:
            result = self._fallback(
                invocation, provider, str(exc), observed_integrity=actual_integrity
            )
        validate_instance(result.to_dict(), self.output_schema, "provider-result")
        return result

    def _run_ui_ux_pro_max(
        self,
        provider: CapabilityProviderSpec,
        invocation: ProviderInvocation,
        bundle: Path,
        work: Path,
        denied_roots: list[Path | str],
    ) -> str:
        script = bundle / "scripts/search.py"
        if not script.is_file() or script.is_symlink():
            raise ValidationFailure("provider search entrypoint is missing or unsafe")
        bootstrap = "import runpy,sys;"
        if platform.system() != "Windows":
            bootstrap += (
                "import resource;"
                f"resource.setrlimit(resource.RLIMIT_FSIZE,({MAX_OUTPUT_BYTES + 1},{MAX_OUTPUT_BYTES + 1}));"
                f"resource.setrlimit(resource.RLIMIT_CPU,({provider.timeout_seconds + 1},{provider.timeout_seconds + 1}));"
                "resource.setrlimit(resource.RLIMIT_NOFILE,(64,64));"
            )
        if platform.system() == "Linux":
            sandbox_module = Path(__file__).resolve().parents[1] / "platforms/provider_sandbox_linux.py"
            bootstrap += (
                f"boundary=runpy.run_path({str(sandbox_module)!r});"
                f"boundary['restrict']({str(bundle)!r},{str(work)!r});"
            )
        elif platform.system() == "Darwin":
            sandbox_module = Path(__file__).resolve().parents[1] / "platforms/provider_sandbox_macos.py"
            bootstrap += (
                f"boundary=runpy.run_path({str(sandbox_module)!r});"
                f"boundary['restrict']({str(self._runtime_root())!r},{str(bundle)!r},{str(work)!r});"
            )
        elif platform.system() == "Windows":
            # CreateProcessW may redirect AppContainer directory options into
            # its profile. Restore only the private cwd after LPAC/Job setup
            # and before loading any Provider code; the profile stays closed.
            bootstrap += (
                "import os;"
                "os.environ.update(dict.fromkeys("
                "('LOCALAPPDATA','APPDATA','USERPROFILE','TEMP','TMP','TMPDIR'),os.getcwd()));"
            )
        bootstrap += (
            "entry=sys.argv[2];"
            "sys.path.insert(0,sys.argv[1]);"
            "sys.argv=[entry,*sys.argv[3:]];"
            "runpy.run_path(entry,run_name='__main__')"
        )
        runtime_executable = self._runtime_executable()
        command = [
            str(runtime_executable),
            "-I",
            "-B",
            "-S",
            "-c",
            bootstrap,
            str(script.parent),
            str(script),
            invocation.query,
        ]
        if invocation.operation == "design_system":
            command.extend(["--design-system", "--format", "markdown"])
            if invocation.project_name:
                command.extend(["--project-name", invocation.project_name])
            for option in ("variance", "motion", "density"):
                value = getattr(invocation, option)
                if value is not None:
                    command.extend([f"--{option}", str(value)])
        else:
            command.append("--json")
            if invocation.stack:
                command.extend(["--stack", invocation.stack])
            else:
                domain = invocation.domain
                if domain is None and invocation.capability_id == "product-prototype-review":
                    domain = "ux"
                if domain:
                    command.extend(["--domain", domain])
            command.extend(["--max-results", "5"])
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR"}
        }
        environment.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "LANG": "C.UTF-8",
                "TEMP": str(work),
                "TMP": str(work),
                "TMPDIR": str(work),
            }
        )
        sandboxed_command = self._sandbox_command(
            command, bundle, work, denied_roots
        )
        if platform.system() == "Windows":
            from ..platforms.provider_sandbox_windows import run

            returncode, output, error = run(
                sandboxed_command, bundle, work, environment,
                provider.timeout_seconds, MAX_OUTPUT_BYTES,
            )
            return self._execution_output(invocation, returncode, output, error)
        stdout_path = work / "stdout.txt"
        stderr_path = work / "stderr.txt"
        with stdout_path.open("w+b") as stdout, stderr_path.open("w+b") as stderr:
            process = subprocess.Popen(
                sandboxed_command,
                cwd=work,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                returncode = process.wait(timeout=provider.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                if hasattr(os, "killpg"):
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # pragma: no cover - non-POSIX platform fallback
                    process.kill()
                process.wait()
                raise ValidationFailure("provider execution timed out") from exc
            output, error = self._read_output_handles(stdout, stderr)
        return self._execution_output(invocation, returncode, output, error)

    @staticmethod
    def _read_output_handles(stdout, stderr) -> tuple[bytes, bytes]:
        # Read the opened files, never provider-controlled pathnames after
        # execution. An output path may have been replaced by a symlink.
        if os.fstat(stdout.fileno()).st_size > MAX_OUTPUT_BYTES:
            raise ValidationFailure("provider output exceeds the configured limit")
        stdout.seek(0)
        stderr.seek(0)
        return stdout.read(MAX_OUTPUT_BYTES + 1), stderr.read(4096)

    @classmethod
    def _execution_output(
        cls, invocation: ProviderInvocation, returncode: int, output: bytes, error: bytes
    ) -> str:
        if len(output) > MAX_OUTPUT_BYTES:
            raise ValidationFailure("provider output exceeds the configured limit")
        if returncode != 0:
            description = error[:4096].decode(
                "utf-8", errors="replace"
            ).strip()
            raise ValidationFailure(
                f"provider exited with status {returncode}: {description}"
            )
        decoded = output.decode("utf-8", errors="replace").strip()
        cls._validate_provider_output(invocation, decoded)
        return decoded

    @staticmethod
    def sandbox_capability() -> dict:
        """Read-only preflight; supported does not mean execution qualified."""
        system = platform.system()
        if system == "Linux":
            from ..platforms.provider_sandbox_linux import capability

            return capability()
        if system == "Windows":
            from ..platforms.provider_sandbox_windows import capability

            return capability()
        if system == "Darwin":
            from ..platforms.provider_sandbox_macos import capability

            return capability()
        return {"supported": False, "backend": None, "reason": "unsupported operating system"}

    @staticmethod
    def _sandbox_command(
        command: list[str],
        bundle: Path,
        writable_root: Path,
        denied_roots: list[Path | str] | None = None,
    ) -> list[str]:
        system = platform.system()
        if system in {"Darwin", "Linux", "Windows"}:
            capability = ProviderExecutor.sandbox_capability()
            if not capability["supported"]:
                raise ValidationFailure(
                    "provider least-privilege sandbox is unavailable: " + capability["reason"]
                )
            # POSIX restricts the already-started trusted interpreter before
            # Provider loading. Windows launches this command through LPAC.
            return command
        raise ValidationFailure(
            "provider least-privilege sandbox is unavailable on this platform"
        )

    @staticmethod
    def _runtime_root() -> Path:
        if platform.system() == "Darwin":
            return Path(sys.base_prefix).resolve()
        return Path(sys.prefix).resolve()

    @classmethod
    def _runtime_executable(cls) -> Path:
        """Return a direct Darwin runtime inside the sandbox read allowlist."""
        executable = Path(sys.executable).resolve()
        if platform.system() != "Darwin":
            return executable
        runtime_root = cls._runtime_root()
        framework_executable = (
            runtime_root
            / "Resources"
            / "Python.app"
            / "Contents"
            / "MacOS"
            / "Python"
        )
        if framework_executable.is_file():
            return framework_executable.resolve()
        try:
            executable.relative_to(runtime_root)
        except ValueError as exc:
            raise ValidationFailure(
                "direct Python runtime is unavailable for least-privilege execution"
            ) from exc
        if not executable.is_file():
            raise ValidationFailure(
                "direct Python runtime is unavailable for least-privilege execution"
            )
        return executable

    @staticmethod
    def _bundle_root(root: Path) -> Path:
        root = root.expanduser()
        if ProviderExecutor._unsafe_link(root):
            raise ValidationFailure("provider root is a symlink or reparse point")
        root = root.resolve()
        nested = root / "src/ui-ux-pro-max"
        return nested if nested.is_dir() else root

    @staticmethod
    def _validate_layout(root: Path) -> None:
        script = root / "scripts/search.py"
        data = root / "data"
        if (
            not root.is_dir()
            or ProviderExecutor._unsafe_link(root)
            or not script.is_file()
            or ProviderExecutor._unsafe_link(script)
            or not data.is_dir()
            or ProviderExecutor._unsafe_link(data)
        ):
            raise ValidationFailure("provider bundle layout is missing or unsafe")

    @staticmethod
    def _tree_integrity(root: Path) -> str:
        return ProviderExecutor._scan_bundle(root, None)

    @staticmethod
    def _snapshot_integrity(root: Path, destination: Path) -> str:
        return ProviderExecutor._scan_bundle(root, destination)

    @staticmethod
    def _scan_bundle(root: Path, destination: Path | None) -> str:
        if not root.is_dir() or ProviderExecutor._unsafe_link(root):
            raise ValidationFailure("provider root is not a safe directory")
        digest = hashlib.sha256()
        count = 0
        entries = 0
        total = 0
        for directory, names, files in os.walk(root, topdown=True, followlinks=False):
            directory_path = Path(directory)
            depth = len(directory_path.relative_to(root).parts)
            if depth > MAX_PROVIDER_DEPTH:
                raise ValidationFailure("provider bundle exceeds the directory depth limit")
            names.sort()
            files.sort()
            for name in list(names):
                path = directory_path / name
                metadata = path.lstat()
                entries += 1
                if name == "__pycache__":
                    raise ValidationFailure("provider bundle contains Python bytecode cache")
                if ProviderExecutor._unsafe_link(path) or not stat.S_ISDIR(metadata.st_mode):
                    raise ValidationFailure("provider bundle contains an unsafe directory entry")
                if entries > MAX_PROVIDER_ENTRIES:
                    raise ValidationFailure("provider bundle exceeds the entry limit")
                if destination is not None:
                    (destination / path.relative_to(root)).mkdir()
            for name in files:
                path = directory_path / name
                metadata = path.lstat()
                entries += 1
                if path.suffix == ".pyc":
                    raise ValidationFailure("provider bundle contains Python bytecode")
                if ProviderExecutor._unsafe_link(path):
                    raise ValidationFailure("provider bundle contains a symlink")
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValidationFailure("provider bundle contains a special file")
                count += 1
                total += metadata.st_size
                if (
                    count > MAX_PROVIDER_FILES
                    or entries > MAX_PROVIDER_ENTRIES
                    or total > MAX_PROVIDER_BYTES
                ):
                    raise ValidationFailure("provider bundle exceeds verification limits")
                relative = path.relative_to(root).as_posix().encode("utf-8")
                flags = os.O_RDONLY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                if hasattr(os, "O_NONBLOCK"):
                    flags |= os.O_NONBLOCK
                descriptor = os.open(path, flags)
                try:
                    opened = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
                    ):
                        raise ValidationFailure("provider bundle file changed while reading")
                    chunks = []
                    read_bytes = 0
                    while True:
                        chunk = os.read(descriptor, min(1024 * 1024, MAX_PROVIDER_BYTES - total + metadata.st_size - read_bytes + 1))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        read_bytes += len(chunk)
                        if total - metadata.st_size + read_bytes > MAX_PROVIDER_BYTES:
                            raise ValidationFailure("provider bundle exceeds verification limits while reading")
                    content = b"".join(chunks)
                    total += read_bytes - metadata.st_size
                finally:
                    os.close(descriptor)
                digest.update(len(relative).to_bytes(4, "big"))
                digest.update(relative)
                digest.update(len(content).to_bytes(8, "big"))
                digest.update(content)
                if destination is not None:
                    target = destination / path.relative_to(root)
                    with target.open("xb") as handle:
                        handle.write(content)
        if count == 0:
            raise ValidationFailure("provider bundle is empty")
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _unsafe_link(path: Path) -> bool:
        metadata = path.lstat()
        return stat.S_ISLNK(metadata.st_mode) or bool(
            getattr(metadata, "st_file_attributes", 0) & 0x400
        )

    @staticmethod
    def invocation_digest(invocation: ProviderInvocation) -> str:
        payload = json.dumps(
            invocation.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _validate_provider_output(
        invocation: ProviderInvocation, output: str
    ) -> None:
        if not output:
            raise ValidationFailure("provider returned empty output")
        if invocation.operation == "design_system":
            if not output.startswith("## Design System:"):
                raise ValidationFailure("provider returned malformed design-system output")
            return
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ValidationFailure("provider returned malformed JSON output") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ValidationFailure("provider search output lacks a results array")

    def _fallback(
        self,
        invocation: ProviderInvocation,
        provider: CapabilityProviderSpec,
        warning: str,
        *,
        observed_integrity: str | None = None,
    ) -> ProviderResult:
        fallback_id = provider.fallback_provider_id or "native-engineering"
        result = ProviderResult(
            invocation_id=invocation.invocation_id,
            invocation_digest=self.invocation_digest(invocation),
            requested_provider_id=provider.id,
            provider_id=fallback_id,
            capability_id=invocation.capability_id,
            status="fallback",
            output=(
                "外部 UI/UX Provider 未产生可用结果。请按 frontend-product pack "
                "执行原生设计审计、方向选择、状态覆盖和真实渲染验证。"
            ),
            trust_level="untrusted_advisory",
            source_revision=provider.source.revision if provider.source else None,
            expected_source_integrity=(
                provider.source.integrity if provider.source else None
            ),
            observed_source_integrity=observed_integrity,
            observed_at=datetime.now(timezone.utc).isoformat(),
            next_action="execute_native_provider",
            warning=warning[:1000],
            fallback_provider_id=fallback_id,
        )
        validate_instance(result.to_dict(), self.output_schema, "provider-result")
        return result
