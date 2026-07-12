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

try:  # pragma: no cover - unavailable on Windows, where execution safely falls back
    import resource
except ImportError:  # pragma: no cover
    resource = None

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
            temporary_parent = "/private/tmp" if platform.system() == "Darwin" else None
            with tempfile.TemporaryDirectory(
                prefix="ea-provider-", dir=temporary_parent
            ) as temporary:
                sandbox_root = Path(temporary)
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
        bootstrap = (
            "import runpy,sys;"
            "entry=sys.argv[2];"
            "sys.path.insert(0,sys.argv[1]);"
            "sys.argv=[entry,*sys.argv[3:]];"
            "runpy.run_path(entry,run_name='__main__')"
        )
        runtime_executable = self._runtime_executable()
        command = [
            str(runtime_executable),
            "-I",
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
            if key in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
        }
        environment.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "LANG": "C.UTF-8",
            }
        )
        sandboxed_command = self._sandbox_command(
            command, bundle, work, denied_roots
        )
        stdout_path = work / "stdout.txt"
        stderr_path = work / "stderr.txt"
        with stdout_path.open("w+b") as stdout, stderr_path.open("w+b") as stderr:
            def limit_output() -> None:
                if resource is not None:
                    resource.setrlimit(
                        resource.RLIMIT_FSIZE,
                        (MAX_OUTPUT_BYTES + 1, MAX_OUTPUT_BYTES + 1),
                    )

            process = subprocess.Popen(
                sandboxed_command,
                cwd=work,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                preexec_fn=limit_output if resource is not None else None,
            )
            try:
                returncode = process.wait(timeout=provider.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                if hasattr(os, "killpg"):
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # pragma: no cover - Windows does not execute providers
                    process.kill()
                process.wait()
                raise ValidationFailure("provider execution timed out") from exc
        if stdout_path.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValidationFailure("provider output exceeds the configured limit")
        if returncode != 0:
            error = stderr_path.read_bytes()[:4096].decode(
                "utf-8", errors="replace"
            ).strip()
            raise ValidationFailure(
                f"provider exited with status {returncode}: {error}"
            )
        output = stdout_path.read_bytes().decode("utf-8", errors="replace").strip()
        self._validate_provider_output(invocation, output)
        return output

    @staticmethod
    def _sandbox_command(
        command: list[str],
        bundle: Path,
        writable_root: Path,
        denied_roots: list[Path | str] | None = None,
    ) -> list[str]:
        system = platform.system()
        if system == "Darwin" and Path("/usr/bin/sandbox-exec").is_file():
            def escaped(path: Path | str) -> str:
                return str(path).replace("\\", "\\\\").replace('"', '\\"')

            del denied_roots  # a denylist cannot strengthen the allowlist below
            runtime_executable = ProviderExecutor._runtime_executable()
            runtime_root = Path(sys.prefix).resolve()
            profile = (
                '(version 1)(deny default)(import "system.sb")'
                '(deny network*)(deny file-write*)(deny process-fork)'
                '(deny process-exec)'
                f'(allow process-exec (literal "{escaped(runtime_executable)}"))'
                f'(allow file-read* (subpath "{escaped(runtime_root)}"))'
                f'(allow file-read* (subpath "{escaped(bundle)}"))'
                f'(allow file-read* (subpath "{escaped(writable_root)}"))'
                f'(allow file-write* (subpath "{escaped(writable_root)}"))'
            )
            return ["/usr/bin/sandbox-exec", "-p", profile, *command]
        raise ValidationFailure(
            "provider least-privilege sandbox is unavailable on this platform"
        )

    @staticmethod
    def _runtime_executable() -> Path:
        """Return the direct Darwin framework executable so the provider cannot fork."""
        executable = Path(sys.executable).resolve()
        if platform.system() != "Darwin":
            return executable
        framework_executable = (
            Path(sys.prefix)
            / "Resources"
            / "Python.app"
            / "Contents"
            / "MacOS"
            / "Python"
        )
        if not framework_executable.is_file():
            raise ValidationFailure(
                "direct Python runtime is unavailable for least-privilege execution"
            )
        return framework_executable.resolve()

    @staticmethod
    def _bundle_root(root: Path) -> Path:
        root = root.expanduser().resolve()
        nested = root / "src/ui-ux-pro-max"
        return nested if nested.is_dir() else root

    @staticmethod
    def _validate_layout(root: Path) -> None:
        script = root / "scripts/search.py"
        data = root / "data"
        if (
            not root.is_dir()
            or root.is_symlink()
            or not script.is_file()
            or script.is_symlink()
            or not data.is_dir()
            or data.is_symlink()
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
        if not root.is_dir() or root.is_symlink():
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
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
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
                if stat.S_ISLNK(metadata.st_mode):
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
                descriptor = os.open(path, flags)
                try:
                    opened = os.fstat(descriptor)
                    if not stat.S_ISREG(opened.st_mode):
                        raise ValidationFailure("provider bundle file changed while reading")
                    chunks = []
                    while True:
                        chunk = os.read(descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    content = b"".join(chunks)
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
