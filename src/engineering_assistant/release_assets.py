"""Assemble bounded, verified CI inputs into reviewable prerelease candidates."""
from __future__ import annotations

import hashlib
import base64
import csv
import io
import json
import re
import tempfile
import zipfile
from contextlib import ExitStack
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Mapping

from .artifact_io import ArtifactIO, artifact_fs
from .compiler import verify_package
from .installation import AGENTS, PYTHON_VERSION, TARGETS, _package_lock
from .validation import ValidationFailure
from .version import CanonicalVersion, platform_version

MAX_CONTROL_BYTES = 1_048_576
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TREE_BYTES = 512 * 1024 * 1024
MAX_TREE_ENTRIES = 16_384
REQUIRED_PROVIDER_CHECKS = frozenset({
    "positive_execution", "snapshot_read", "private_work_write", "network_ipv4", "network_ipv6",
    "outside_read", "outside_write", "snapshot_write", "child_process", "same_python_exec", "extra_exec",
})
_PROVIDER_TESTS = frozenset(
    "test_provider_runtime.ProviderRuntimeTests." + name for name in (
        "test_production_sandbox_runs_provider_and_allows_only_private_work_writes",
        "test_production_sandbox_denies_network_processes_exec_and_outside_writes",
        "test_production_sandbox_enforces_timeout_and_output_limit",
    )
)
_WINDOWS_TESTS = frozenset(
    "test_windows_artifact_fs.WindowsArtifactIntegrationTests." + name for name in (
        "test_concurrent_immutable_and_cas_have_exactly_one_winner",
        "test_lock_timeout_and_empty_directory_removal",
        "test_created_file_and_chmod_preserve_private_owner_dacl",
        "test_parent_rename_keeps_reads_and_writes_on_opened_identity",
        "test_directory_fd_copy_hash_rename_and_delete_contract",
        "test_junction_is_rejected_without_reading_or_writing_its_target",
        "test_private_directory_validation_accepts_path_and_retained_handle",
        "test_private_directory_validation_rejects_broad_and_null_dacls",
        "test_plain_created_descendants_inherit_private_directory_dacl",
        "test_new_staging_owner_assignment_preserves_rejected_broad_dacl",
    )
) | frozenset(
    "test_windows_process.WindowsProcessTests." + name for name in (
        "test_unicode_arguments_and_space_paths_round_trip",
        "test_bounded_stdin_reaches_eof_without_pipe_deadlock",
        "test_output_limit_terminates_the_operation",
        "test_timeout_terminates_parent_and_descendant",
        "test_parent_exit_also_cleans_descendants",
    )
) | frozenset(
    "test_windows_hooks.WindowsHookExecutionTests." + name for name in (
        "test_cmd_manifest_bridge_preserves_protocol_bytes",
        "test_powershell_manifest_bridge_preserves_protocol_bytes",
        "test_git_bash_manifest_bridge_preserves_protocol_bytes",
        "test_bridge_preserves_native_failure_exit_status",
        "test_unprepared_hook_remains_nonblocking",
        "test_bridge_timeout_terminates_runtime_descendants",
    )
) | frozenset(
    "test_native_launcher.NativeLauncherTests." + name for name in (
        "test_windows_launcher_accepts_inherited_private_runtime_acl",
        "test_windows_launcher_rejects_broad_runtime_path_acl",
        "test_windows_launcher_rejects_null_control_dacl",
    )
)


def required_native_tests(target: str) -> frozenset[str]:
    required = _PROVIDER_TESTS
    if target.startswith("macos-"):
        required |= {"test_provider_runtime.ProviderRuntimeTests.test_production_sandbox_denies_shared_temp_and_child_processes"}
    if target == "windows-x64":
        required |= _WINDOWS_TESTS | {
            "test_provider_runtime.ProviderRuntimeTests."
            "test_windows_lpac_keeps_temporary_and_profile_options_in_private_work"
        }
    return frozenset(required)


def _safe_root(path: Path | str) -> ArtifactIO:
    raw = Path(path).absolute()
    if ".." in raw.parts:
        raise ValidationFailure("发行输入路径不能包含父目录遍历")
    anchor = ArtifactIO(Path(raw.anchor), ".")
    try:
        with anchor.open_directory(*raw.relative_to(raw.anchor).parts) as descriptor:
            return ArtifactIO.from_open_directory_fd(raw, descriptor)
    finally:
        anchor.close()


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _tree_digest(files: dict) -> str:
    return _digest("\n".join(f"{name}:{digest}" for name, digest in sorted(files.items())).encode())


def _file_hashes(storage: ArtifactIO) -> dict:
    return storage.sha256_file_digests(max_file_bytes=MAX_FILE_BYTES, max_entries=MAX_TREE_ENTRIES,
                                     max_total_bytes=MAX_TREE_BYTES)


def _record(storage: ArtifactIO, name: str) -> tuple[dict, str]:
    raw = storage.read_bytes_limited(MAX_CONTROL_BYTES, name)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationFailure(f"发行验证记录不是有效 JSON：{name}") from exc
    if not isinstance(value, dict):
        raise ValidationFailure(f"发行验证记录必须是对象：{name}")
    return value, _digest(raw)


def _validate_records(storage: ArtifactIO, target: str) -> tuple[dict, dict]:
    records, hashes = {}, {}
    for name in ("host.json", "native-tests.json", "runtime-qualification.json"):
        records[name], hashes[name] = _record(storage, name)
        if records[name].get("target") != target:
            raise ValidationFailure(f"CI 验证记录 target 不一致：{target}/{name}")
    host, native, runtime = (records[name] for name in records)
    if host.get("python") != PYTHON_VERSION:
        raise ValidationFailure("CI 宿主没有使用固定 Python")
    required = required_native_tests(target)
    reported = native.get("native_tests")
    capability = native.get("provider_capability")
    if (not isinstance(reported, list) or any(not isinstance(item, str) for item in reported)
            or len(set(reported)) != len(reported) or not required <= set(reported)
            or type(native.get("required_native_skips")) is not int or native["required_native_skips"] != 0
            or type(native.get("test_count")) is not int or native["test_count"] < len(required)
            or not isinstance(capability, dict) or capability.get("supported") is not True):
        raise ValidationFailure(f"原生必需测试缺失、跳过或 Provider 不受支持：{target}")
    if runtime.get("schema_version") != "1" or runtime.get("status") != "runtime_qualified":
        raise ValidationFailure(f"Runtime 资格未通过：{target}")
    results = runtime.get("results")
    if not isinstance(results, list) or len(results) != len(AGENTS):
        raise ValidationFailure("Runtime 资格必须覆盖三个 Agent")
    by_agent = {}
    for result in results:
        if not isinstance(result, dict) or result.get("agent") not in AGENTS or result["agent"] in by_agent:
            raise ValidationFailure("Runtime 资格 Agent 重复或无效")
        if (result.get("target") != target or result.get("python_version") != PYTHON_VERSION
                or result.get("persistent_run") != "passed" or result.get("feedback_hook") != "passed"):
            raise ValidationFailure("Runtime 资格 target、Python、持久化或真实反馈 Hook 检查未通过")
        if (not isinstance(result.get("python_build"), str)
                or re.fullmatch(r"[0-9]{8}", result["python_build"]) is None
                or not isinstance(result.get("python_artifact_digest"), str)
                or re.fullmatch(r"[0-9a-f]{64}", result["python_artifact_digest"]) is None):
            raise ValidationFailure("Runtime 资格缺少固定 Python 构建记录")
        checks = result.get("checks", {})
        if (not isinstance(checks, dict) or set(checks) != {"mcp", "tools_call", "hook", "windows_hook_bridge", "hermes_bridge", "provider"}
                or any(checks.get(name) != "passed" for name in ("mcp", "tools_call", "hook"))):
            raise ValidationFailure("Runtime MCP、工具或 Hook 检查未通过")
        expected_windows_bridge = "passed" if target == "windows-x64" and result["agent"] == "codex" else "not_applicable"
        if checks.get("windows_hook_bridge") != expected_windows_bridge:
            raise ValidationFailure("Windows Hook manifest bridge 未通过或未声明不适用")
        if result["agent"] == "hermes" and checks.get("hermes_bridge") != "passed":
            raise ValidationFailure("Hermes native bridge 未通过")
        if result["agent"] != "hermes" and checks.get("hermes_bridge") != "not_applicable":
            raise ValidationFailure("非 Hermes 包的 bridge 检查必须明确不适用")
        provider = checks.get("provider", {})
        boundaries = provider.get("checks", {}) if isinstance(provider, dict) else {}
        baselines = provider.get("baselines", {}) if isinstance(provider, dict) else {}
        if (not isinstance(provider, dict) or provider.get("supported") is not True or provider.get("qualified") is not True
                or not isinstance(boundaries, dict) or set(boundaries) != REQUIRED_PROVIDER_CHECKS
                or any(value is not True for value in boundaries.values())
                or not isinstance(baselines, dict)
                or any(baselines.get(name) is not True for name in ("network_ipv4", "network_ipv6"))):
            raise ValidationFailure("Provider 十一项执行边界及网络基线必须全部通过")
        by_agent[result["agent"]] = result
    return by_agent, hashes


def _portable_member(name: str, *, directory: bool = False) -> None:
    body = name[:-1] if directory and name.endswith("/") else name
    parts = body.split("/")
    for part in parts:
        if (not part or part in {".", ".."} or part.endswith((".", " "))
                or any(ord(character) < 32 or character in '<>:"\\|?*' for character in part)
                or re.fullmatch(r"(?i)(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?", part)):
            raise ValidationFailure("发行归档包含非便携或不安全路径")


def _required_wheel_files(repository_root: Path) -> set[str]:
    """Require the complete authored module and resource layout, including lazy imports."""
    modules = repository_root / "src/engineering_assistant"
    if not modules.is_dir():
        modules = Path(__file__).resolve().parent
    module_io = _safe_root(modules)
    try:
        required = {"engineering_assistant/" + name for name in _file_hashes(module_io)
                    if name.endswith(".py") and not any(part.startswith(".") for part in PurePosixPath(name).parts)}
    finally:
        module_io.close()
    for directory in ("catalog", "skills", "packs", "schemas", "evals", "config"):
        resources = _safe_root(repository_root / directory)
        try:
            required.update("engineering_assistant/_assets/" + directory + "/" + name
                for name in _file_hashes(resources) if not any(part.startswith(".") for part in PurePosixPath(name).parts))
        finally:
            resources.close()
    required.add("engineering_assistant/_assets/VERSIONING.md")
    return required


def _wheel_record(archive: zipfile.ZipFile, names: set[str], prefix: str) -> None:
    record_name = prefix + "RECORD"
    try:
        metadata = archive.getinfo(record_name)
        if metadata.file_size > MAX_CONTROL_BYTES:
            raise ValidationFailure("setup wheel RECORD 超出安全上限")
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"), newline="")))
        files = {name for name in names if not name.endswith("/")}
        observed = set()
        for row in rows:
            if len(row) != 3 or row[0] not in files or row[0] in observed:
                raise ValidationFailure("setup wheel RECORD 条目重复、未知或不完整")
            name, digest, size = row
            observed.add(name)
            if name == record_name:
                if digest or size:
                    raise ValidationFailure("setup wheel RECORD 自身必须使用空摘要和长度")
                continue
            payload = archive.read(name)
            expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode("ascii")
            if digest != expected or size != str(len(payload)):
                raise ValidationFailure("setup wheel RECORD 摘要或长度不一致")
        if observed != files:
            raise ValidationFailure("setup wheel RECORD 没有覆盖全部文件")
    except ValidationFailure:
        raise
    except (KeyError, ValueError, UnicodeDecodeError, csv.Error, zipfile.BadZipFile):
        raise ValidationFailure("setup wheel RECORD 缺失或无法验证") from None


def _wheel_version(raw: bytes, canonical_version: str,
                   repository_root: Path = Path(__file__).resolve().parents[2]) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_TREE_ENTRIES or sum(entry.file_size for entry in entries) > MAX_TREE_BYTES:
            raise ValidationFailure("setup wheel 超出安全上限")
        names = set()
        portable_names = set()
        for entry in entries:
            _portable_member(entry.orig_filename, directory=entry.is_dir())
            path = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if (entry.filename.casefold() in portable_names or path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                    or entry.file_size > MAX_FILE_BYTES or (mode & 0o170000) not in {0, 0o040000, 0o100000}):
                raise ValidationFailure("setup wheel 包含不安全或重复条目")
            names.add(entry.filename)
            portable_names.add(entry.filename.casefold())
        if not _required_wheel_files(repository_root) <= names:
            raise ValidationFailure("setup wheel 缺少完整安装模块或运行资源")
        def read(name):
            metadata = archive.getinfo(name)
            if metadata.file_size > MAX_CONTROL_BYTES:
                raise ValidationFailure("setup wheel 元数据超出安全上限")
            return archive.read(name).decode("utf-8")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValidationFailure("setup wheel 必须只有一个 distribution")
        metadata_name = metadata_names[0]
        prefix = metadata_name.removesuffix("METADATA")
        _wheel_record(archive, names, prefix)
        metadata = Parser().parsestr(read(metadata_name))
        if metadata.get("Name", "").replace("_", "-").lower() != "engineering-assistant-kernel":
            raise ValidationFailure("setup wheel 身份不匹配")
        wheel = Parser().parsestr(read(prefix + "WHEEL"))
        if wheel.get("Root-Is-Purelib") != "true" or wheel.get_all("Tag") != ["py3-none-any"]:
            raise ValidationFailure("setup wheel 必须与操作系统无关")
        public = json.loads(read("engineering_assistant/_assets/catalog/skills/public.json"))
        if public.get("version") != canonical_version:
            raise ValidationFailure("setup wheel 与原生包版本混合")
        if not re.search(r"(?m)^ea-setup\s*=\s*engineering_assistant\.setup_cli:main\s*$", read(prefix + "entry_points.txt")):
            raise ValidationFailure("setup wheel 没有 ea-setup 入口")
        version = CanonicalVersion.parse(canonical_version)
        base = f"{version.major}.{version.minor}.{version.patch}"
        pre = version.prerelease.replace(".", "").replace("-", "")
        expected = {base + pre, base + "." + str(version.build) + pre} if version.build == 0 else {base + "." + str(version.build) + pre}
        if metadata.get("Version") not in expected:
            raise ValidationFailure("setup wheel distribution 与作者源版本不一致")
        return metadata["Version"]


def _wheel_verification(storage: ArtifactIO, raw: bytes, filename: str, wheel_version: str,
                        canonical_version: str) -> tuple[bytes, str]:
    try:
        receipt_raw = storage.read_bytes_limited(MAX_CONTROL_BYTES, "setup", "wheel-verification.json")
        receipt = json.loads(receipt_raw)
        required = {"schema_version", "status", "python_version", "canonical_version", "wheel_filename",
                    "wheel_digest", "wheel_version", "checks"}
        checks = receipt.get("checks") if isinstance(receipt, dict) else None
        if (not isinstance(receipt, dict) or set(receipt) != required
                or receipt.get("schema_version") != "1" or receipt.get("status") != "passed"
                or receipt.get("python_version") != PYTHON_VERSION or receipt.get("canonical_version") != canonical_version
                or receipt.get("wheel_filename") != filename or receipt.get("wheel_version") != wheel_version
                or receipt.get("wheel_digest") != _digest(raw) or not isinstance(checks, dict)
                or set(checks) != {"help", "doctor", "source_validation", "eval"}
                or any(value != "passed" for value in checks.values())
                or _digest(storage.read_bytes_limited(MAX_FILE_BYTES, "setup", filename)) != _digest(raw)):
            raise ValidationFailure("setup wheel Linux 隔离安装验证记录缺失、失败或与文件不一致")
        return receipt_raw, _digest(receipt_raw)
    except ValidationFailure:
        raise
    except (OSError, ValueError, TypeError):
        raise ValidationFailure("setup wheel Linux 隔离安装验证记录缺失或无效") from None


def _archive(storage: ArtifactIO) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(_file_hashes(storage)):
            _portable_member(name)
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (0o100755 if name in {"engineering-assistant/bin/ea", "engineering-assistant/bin/ea.exe"} else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, storage.read_bytes_limited(MAX_FILE_BYTES, *PurePosixPath(name).parts))
    return output.getvalue()


def _copy(source: ArtifactIO, destination: ArtifactIO) -> None:
    source.copy_contents_to(destination, max_file_bytes=MAX_FILE_BYTES, max_entries=MAX_TREE_ENTRIES,
                            max_total_bytes=MAX_TREE_BYTES)


def _marketplace(agent: str, version: str) -> tuple[str, dict]:
    plugin = {"name": "engineering-assistant", "version": platform_version(version, supports_four_part=False)}
    if agent == "codex":
        plugin.pop("version")
        plugin.update(source={"source": "local", "path": "./plugins/engineering-assistant"},
                      policy={"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, category="Productivity")
        return ".agents/plugins/marketplace.json", {"name": "engineering-assistant", "interface": {"displayName": "工程助手"}, "plugins": [plugin]}
    plugin["source"] = "./plugins/engineering-assistant"
    return ".claude-plugin/marketplace.json", {"name": "engineering-assistant", "owner": {
        "name": "sunliming625@gmail.com", "email": "sunliming625@gmail.com"}, "plugins": [plugin]}


def assemble_release(artifacts: Mapping[str, Path | str], wheel: Path | str, output: Path | str,
                     *, repository_root: Path | str = Path(__file__).resolve().parents[2]) -> dict:
    if set(artifacts) != set(TARGETS):
        raise ValidationFailure("发行候选必须包含完整的四目标矩阵")
    destination = Path(output).absolute()
    repository = Path(repository_root).resolve()
    if destination == repository or repository in destination.resolve().parents or destination.resolve() in repository.parents:
        raise ValidationFailure("发行产物必须位于作者源仓库外")
    with ExitStack() as stack:
        temporary = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="ea-release-inputs-"))).resolve()
        manifests, qualifications, evidence = {}, {}, {}
        snapshot_ios, artifact_ios = {}, {}
        versions = set()
        for target in TARGETS:
            source = _safe_root(artifacts[target])
            stack.callback(source.close)
            snapshot = temporary / target
            snapshot.mkdir()
            storage = ArtifactIO(snapshot, ".")
            stack.callback(storage.close)
            _copy(source, storage)
            artifact_ios[target] = storage
            qualifications[target], evidence[target] = _validate_records(storage, target)
            for agent in AGENTS:
                package = snapshot / agent
                with storage.open_directory(agent) as descriptor:
                    package_io = ArtifactIO.from_open_directory_fd(package, descriptor)
                stack.callback(package_io.close)
                manifest = verify_package(package)
                qualification = qualifications[target][agent]
                if (manifest.get("target") != target or manifest.get("platform") != agent
                        or manifest.get("canonical_version") != qualification.get("canonical_version")
                        or manifest.get("payload_digest") != qualification.get("payload_digest")):
                    raise ValidationFailure("原生包与 Runtime 资格 target、Agent、版本或摘要不一致")
                lock = _package_lock(package)
                if (qualification["python_build"] != lock["python_artifact"]["build"]
                        or qualification["python_artifact_digest"] != lock["python_artifact_digest"]):
                    raise ValidationFailure("Runtime 资格与包内固定 Python 构建不一致")
                manifests[target, agent] = manifest
                snapshot_ios[target, agent] = package_io
                versions.add(manifest["canonical_version"])
        if len(versions) != 1:
            raise ValidationFailure("发行候选不能混合版本")
        version = versions.pop()
        if CanonicalVersion.parse(version).prerelease is None:
            raise ValidationFailure("当前组装器拒绝稳定版发行")
        wheel_path = Path(wheel).absolute()
        if wheel_path.suffix != ".whl":
            raise ValidationFailure("setup 输入必须是现有 wheel 文件")
        wheel_io = _safe_root(wheel_path.parent)
        stack.callback(wheel_io.close)
        wheel_raw = wheel_io.read_bytes_limited(MAX_FILE_BYTES, wheel_path.name)
        wheel_version = _wheel_version(wheel_raw, version, repository)
        wheel_receipt, wheel_receipt_digest = _wheel_verification(artifact_ios["linux-x64"], wheel_raw,
                                                                wheel_path.name, wheel_version, version)
        evidence["linux-x64"]["setup/wheel-verification.json"] = wheel_receipt_digest
        parent = _safe_root(destination.parent)
        stack.callback(parent.close)
        path, descriptor, identity = parent.create_directory_exclusive_open(destination.name)
        try:
            result_io = ArtifactIO.from_open_directory_fd(path, descriptor)
        finally:
            artifact_fs.close(descriptor)
        stack.callback(result_io.close)
        entries = []
        for target in TARGETS:
            for agent in AGENTS:
                package_io = snapshot_ios[target, agent]
                archive = _archive(package_io)
                archive_path = f"archives/{target}/{agent}.zip"
                result_io.write_bytes_exclusive(archive, *PurePosixPath(archive_path).parts)
                tree_path = f"marketplaces/{agent}/{target}"
                package_path = tree_path if agent == "hermes" else tree_path + "/plugins/engineering-assistant"
                result_io.ensure_directory(*PurePosixPath(package_path).parts)
                with result_io.open_directory(*PurePosixPath(package_path).parts) as directory:
                    package_out = ArtifactIO.from_open_directory_fd(result_io.path(*PurePosixPath(package_path).parts), directory)
                try:
                    _copy(package_io, package_out)
                    # CI artifact transport loses POSIX executable bits; restore the
                    # sole native entrypoint in each independently installable tree.
                    executable = "ea.exe" if target == "windows-x64" else "ea"
                    package_out.chmod_regular_file(0o755, "engineering-assistant", "bin", executable)
                    verify_package(package_out.path())
                finally:
                    package_out.close()
                if agent != "hermes":
                    manifest_path, marketplace = _marketplace(agent, version)
                    result_io.create_immutable_json(marketplace, *PurePosixPath(tree_path + "/" + manifest_path).parts)
                with result_io.open_directory(*PurePosixPath(tree_path).parts) as directory:
                    tree_io = ArtifactIO.from_open_directory_fd(result_io.path(*PurePosixPath(tree_path).parts), directory)
                try:
                    tree_sha = _tree_digest(_file_hashes(tree_io))
                finally:
                    tree_io.close()
                entries.append({"target": target, "agent": agent, "canonical_version": version,
                    "package_payload_digest": manifests[target, agent]["payload_digest"],
                    "archive": {"path": archive_path, "sha256": _digest(archive)},
                    "marketplace": {"path": tree_path, "tree_sha256": tree_sha,
                                    "suggested_branch": f"release/{agent}/{target}"}})
        result_io.write_bytes_exclusive(wheel_raw, "setup", wheel_path.name)
        result_io.write_bytes_exclusive(wheel_receipt, "setup", "wheel-verification.json")
        index = {"schema_version": "1", "status": "candidate", "canonical_version": version,
            "assurance": "ci_artifacts_unattested", "targets": list(TARGETS), "packages": entries,
            "setup": {"path": "setup/" + wheel_path.name, "sha256": _digest(wheel_raw), "version": wheel_version,
                      "verification": {"path": "setup/wheel-verification.json", "sha256": wheel_receipt_digest, "status": "passed"}},
            "evidence_sha256": evidence,
            "support_qualification": {"status": "not_satisfied", "native_agent_sessions": "not_verified",
                "windows11": "not_verified", "requires_review": True,
                "missing": ["authenticated_codex_session", "authenticated_hermes_session",
                            "authenticated_claude_code_session", "windows11_native_host"]}}
        if not parent.child_directory_matches(destination.name, identity):
            raise ValidationFailure("发行输出目录在组装期间发生替换")
        result_io.create_immutable_json(index, "release-index.json")
        return index
