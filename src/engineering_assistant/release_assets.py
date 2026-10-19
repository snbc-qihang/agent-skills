"""Assemble bounded native validation inputs into reviewable internal candidates."""
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
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Mapping

from .artifact_io import ArtifactIO, artifact_fs
from .compiler import verify_package
from .catalog import DEFAULT_REPOSITORY_ROOT
from .installation import AGENTS, PYTHON_VERSION, TARGETS, _package_lock
from .validation import ValidationFailure
from .version import CanonicalVersion, platform_version

INTERNAL_AGENTS = ("codex",)
INTERNAL_TARGETS = ("macos-arm64", "macos-x64", "windows-x64")
INTERNAL_REPOSITORY = "snbc-qihang/agent-skills"
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


def release_scope(agents, targets) -> tuple[tuple[str, ...], tuple[str, ...]]:
    def selected(values, known, label):
        if (not isinstance(values, (list, tuple)) or not values
                or any(not isinstance(item, str) or item not in known for item in values)
                or len(set(values)) != len(values)):
            raise ValidationFailure("发行 " + label + " 集合为空、重复或包含未知值")
        return tuple(values)
    return selected(agents, AGENTS, "Agent"), selected(targets, TARGETS, "目标")


def release_provenance(source_commit: str, ci_identity: dict | None = None,
                       *, validation_origin: dict | None = None) -> dict:
    if (not isinstance(source_commit, str) or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
            or (ci_identity is None) == (validation_origin is None)):
        raise ValidationFailure("发行来源必须绑定源码 commit 和唯一验证来源")
    if ci_identity is not None:
        if (not isinstance(ci_identity, dict) or set(ci_identity) != {"repository", "run_id", "run_attempt"}
                or ci_identity["repository"] != INTERNAL_REPOSITORY
                or not isinstance(ci_identity["run_id"], str) or re.fullmatch(r"[1-9][0-9]*", ci_identity["run_id"]) is None
                or type(ci_identity["run_attempt"]) is not int or ci_identity["run_attempt"] < 1):
            raise ValidationFailure("发行来源必须绑定固定仓库和有效 CI 运行身份")
        return {"ci_identity": dict(ci_identity)}
    origin = validation_origin
    if (not isinstance(origin, dict) or set(origin) != {"kind", "repository", "validation_id", "assurance"}
            or origin["kind"] != "local" or origin["repository"] != INTERNAL_REPOSITORY
            or origin["assurance"] != "local_unattested" or not isinstance(origin["validation_id"], str)
            or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                            origin["validation_id"]) is None):
        raise ValidationFailure("本地验证来源必须绑定固定仓库、随机批次 ID 和 local_unattested")
    return {"validation_origin": dict(origin)}


def index_provenance(index: dict) -> dict:
    fields = {name: index[name] for name in ("ci_identity", "validation_origin") if name in index}
    if len(fields) != 1 or next(iter(fields.values())) is None:
        raise ValidationFailure("发行 index 必须包含唯一验证来源")
    provenance = release_provenance(index.get("source_commit"), **fields)
    assurance = "local_artifacts_unattested" if "validation_origin" in provenance else "ci_artifacts_unattested"
    if index.get("assurance") != assurance:
        raise ValidationFailure("发行 assurance 与验证来源不一致")
    return provenance


def _matches_provenance(record: dict, source_commit: str, provenance: dict) -> bool:
    return (record.get("source_commit") == source_commit
            and {name: record[name] for name in ("ci_identity", "validation_origin") if name in record} == provenance)


def _validate_records(storage: ArtifactIO, target: str, agents: tuple[str, ...],
                      source_commit: str, provenance: dict) -> tuple[dict, dict]:
    records, hashes = {}, {}
    for name in ("host.json", "native-tests.json", "runtime-qualification.json"):
        records[name], hashes[name] = _record(storage, name)
        if not _matches_provenance(records[name], source_commit, provenance):
            raise ValidationFailure("验证记录来源不一致：" + target + "/" + name)
        if records[name].get("target") != target:
            raise ValidationFailure(f"验证记录 target 不一致：{target}/{name}")
    host, native, runtime = (records[name] for name in records)
    if host.get("python") != PYTHON_VERSION:
        raise ValidationFailure("验证宿主没有使用固定 Python")
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
    if not isinstance(results, list) or len(results) != len(agents):
        raise ValidationFailure("Runtime 资格必须精确覆盖已选择 Agent")
    by_agent = {}
    for result in results:
        if not isinstance(result, dict) or result.get("agent") not in agents or result["agent"] in by_agent:
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
    for name in ("VERSIONING.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        required.add("engineering_assistant/_assets/" + name)
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
                   repository_root: Path = DEFAULT_REPOSITORY_ROOT) -> str:
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
        pre = (version.prerelease or "").replace(".", "").replace("-", "")
        expected = {base + pre, base + "." + str(version.build) + pre} if version.build == 0 else {base + "." + str(version.build) + pre}
        if metadata.get("Version") not in expected:
            raise ValidationFailure("setup wheel distribution 与作者源版本不一致")
        return metadata["Version"]


def _wheel_verification(storage: ArtifactIO, raw: bytes, filename: str, wheel_version: str,
                        canonical_version: str, source_commit: str, provenance: dict) -> tuple[bytes, str]:
    try:
        receipt_raw = storage.read_bytes_limited(MAX_CONTROL_BYTES, "wheel-verification.json")
        receipt = json.loads(receipt_raw)
        required = {"schema_version", "status", "python_version", "canonical_version", "wheel_filename",
                    "wheel_digest", "wheel_version", "checks", "source_commit"} | set(provenance)
        checks = receipt.get("checks") if isinstance(receipt, dict) else None
        if (not isinstance(receipt, dict) or set(receipt) != required
                or receipt.get("schema_version") != "1" or receipt.get("status") != "passed"
                or receipt.get("python_version") != PYTHON_VERSION or receipt.get("canonical_version") != canonical_version
                or receipt.get("wheel_filename") != filename or receipt.get("wheel_version") != wheel_version
                or not _matches_provenance(receipt, source_commit, provenance)
                or receipt.get("wheel_digest") != _digest(raw) or not isinstance(checks, dict)
                or set(checks) != {"help", "doctor", "source_validation", "eval"}
                or any(value != "passed" for value in checks.values())
                or _digest(storage.read_bytes_limited(MAX_FILE_BYTES, filename)) != _digest(raw)):
            raise ValidationFailure("setup wheel 隔离安装验证记录缺失、失败或与文件不一致")
        return receipt_raw, _digest(receipt_raw)
    except ValidationFailure:
        raise
    except (OSError, ValueError, TypeError):
        raise ValidationFailure("setup wheel 隔离安装验证记录缺失或无效") from None


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
                     *, agents=INTERNAL_AGENTS, targets=INTERNAL_TARGETS, source_commit: str,
                     ci_identity: dict | None = None, validation_origin: dict | None = None,
                     repository_root: Path | str = DEFAULT_REPOSITORY_ROOT) -> dict:
    agents, targets = release_scope(agents, targets)
    provenance = release_provenance(source_commit, ci_identity, validation_origin=validation_origin)
    if set(artifacts) != set(targets):
        raise ValidationFailure("发行输入必须精确覆盖已选择目标矩阵")
    destination = Path(output).absolute()
    repository = Path(repository_root).resolve()
    if destination == repository or repository in destination.resolve().parents or destination.resolve() in repository.parents:
        raise ValidationFailure("发行产物必须位于作者源仓库外")
    with ExitStack() as stack:
        temporary = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="ea-release-inputs-"))).resolve()
        manifests, qualifications, evidence = {}, {}, {}
        snapshot_ios, artifact_ios = {}, {}
        versions = set()
        for target in targets:
            source = _safe_root(artifacts[target])
            stack.callback(source.close)
            snapshot = temporary / target
            snapshot.mkdir()
            storage = ArtifactIO(snapshot, ".")
            stack.callback(storage.close)
            _copy(source, storage)
            artifact_ios[target] = storage
            qualifications[target], evidence[target] = _validate_records(storage, target, agents, source_commit, provenance)
            for agent in agents:
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
            if "codex" in agents:
                official, official_digest = _record(storage, "official-validation.json")
                if (official.get("status") != "passed" or official.get("quick_validate") != "passed"
                        or official.get("codex_plugin_validate") != "passed" or official.get("skill_count") != 11
                        or official.get("codex_payload_digest") != manifests[target, "codex"]["payload_digest"]
                        or not _matches_provenance(official, source_commit, provenance)):
                    raise ValidationFailure("官方校验与发行包或来源不一致：" + target)
                evidence[target]["official-validation.json"] = official_digest
        if len(versions) != 1:
            raise ValidationFailure("发行候选不能混合版本")
        version = versions.pop()
        if (CanonicalVersion.parse(version).prerelease is None
                and (agents != INTERNAL_AGENTS or targets != INTERNAL_TARGETS)):
            raise ValidationFailure("正式内部编号只允许完整 Codex 三目标候选；其他稳定版发行仍被拒绝")
        wheel_path = Path(wheel).absolute()
        if wheel_path.suffix != ".whl":
            raise ValidationFailure("setup 输入必须是现有 wheel 文件")
        wheel_io = _safe_root(wheel_path.parent)
        stack.callback(wheel_io.close)
        wheel_raw = wheel_io.read_bytes_limited(MAX_FILE_BYTES, wheel_path.name)
        wheel_version = _wheel_version(wheel_raw, version, repository)
        wheel_receipt, wheel_receipt_digest = _wheel_verification(wheel_io, wheel_raw, wheel_path.name, wheel_version, version,
                                                                source_commit, provenance)
        evidence["setup"] = {"wheel-verification.json": wheel_receipt_digest}
        parent = _safe_root(destination.parent)
        stack.callback(parent.close)
        path, descriptor, identity = parent.create_directory_exclusive_open(destination.name)
        try:
            result_io = ArtifactIO.from_open_directory_fd(path, descriptor)
        finally:
            artifact_fs.close(descriptor)
        stack.callback(result_io.close)
        entries = []
        for target in targets:
            for agent in agents:
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
                    "marketplace": {"path": tree_path, "tree_sha256": tree_sha}})
        result_io.write_bytes_exclusive(wheel_raw, "setup", wheel_path.name)
        result_io.write_bytes_exclusive(wheel_receipt, "setup", "wheel-verification.json")
        index = {"schema_version": "2", "status": "candidate", "canonical_version": version,
            "source_commit": source_commit, **provenance, "agents": list(agents),
            "release_tag": "internal/codex/" + version,
            "assurance": "local_artifacts_unattested" if validation_origin is not None else "ci_artifacts_unattested",
            "targets": list(targets), "packages": entries,
            "setup": {"path": "setup/" + wheel_path.name, "sha256": _digest(wheel_raw), "version": wheel_version,
                      "verification": {"path": "setup/wheel-verification.json", "sha256": wheel_receipt_digest, "status": "passed"}},
            "evidence_sha256": evidence,
            "support_qualification": {"status": "not_satisfied", "native_agent_sessions": "not_verified",
                "windows11": "not_verified", "requires_review": True,
                "missing": ["authenticated_" + agent + "_session" for agent in agents]
                            + (["windows11_native_host"] if "windows-x64" in targets else [])}}
        if not parent.child_directory_matches(destination.name, identity):
            raise ValidationFailure("发行输出目录在组装期间发生替换")
        result_io.create_immutable_json(index, "release-index.json")
        return index


NATIVE_SESSION_CHECKS = frozenset({
    "install", "skills", "mcp", "hook", "persistent_run", "restart", "update", "recovery", "uninstall",
    "repeat_install", "repair", "uv_upgrade", "uv_removal", "cache_cleanup", "installer_alias_advance",
    "network_failure", "authentication_failure", "digest_failure", "interrupted_update",
    "preparation_failure_preserves_previous", "unicode_space_paths",
})


def validate_acceptance(index: dict, index_raw: bytes, record: dict, storage: ArtifactIO | None = None) -> None:
    """Validate human-reviewed local host evidence; this does not authenticate a reviewer."""
    if (not isinstance(index, dict) or index.get("schema_version") != "2"
            or index.get("agents") != list(INTERNAL_AGENTS) or index.get("targets") != list(INTERNAL_TARGETS)):
        raise ValidationFailure("内部发行验收必须精确覆盖 Codex 的三个原生目标")
    index_provenance(index)
    try:
        if json.loads(index_raw) != index:
            raise ValidationFailure("验收 index 与原始候选字节不一致")
        reviewed = datetime.fromisoformat(record.get("reviewed_at", "").replace("Z", "+00:00"))
        if reviewed.tzinfo is None:
            raise ValueError("review time must include a timezone")
    except (TypeError, ValueError, AttributeError):
        raise ValidationFailure("验收记录或人工审查时间无效") from None
    fields = {"schema_version", "status", "canonical_version", "source_commit", "candidate_index_digest",
              "reviewer_ref", "reviewed_at", "targets"}
    if (not isinstance(record, dict) or set(record) != fields
            or record.get("schema_version") != "1" or record.get("status") != "accepted"
            or record.get("canonical_version") != index.get("canonical_version")
            or record.get("source_commit") != index.get("source_commit")
            or record.get("candidate_index_digest") != _digest(index_raw)
            or not isinstance(record.get("reviewer_ref"), str) or not record["reviewer_ref"].strip()
            or len(record["reviewer_ref"]) > 256):
        raise ValidationFailure("人工验收未接受、缺少审查人或与候选版本及来源不一致")
    packages = index.get("packages")
    if not isinstance(packages, list) or len(packages) != len(INTERNAL_TARGETS):
        raise ValidationFailure("验收候选包集合不完整")
    by_target = {}
    for package in packages:
        if (not isinstance(package, dict) or package.get("agent") != "codex"
                or package.get("target") not in INTERNAL_TARGETS or package["target"] in by_target
                or re.fullmatch(r"sha256:[0-9a-f]{64}", str(package.get("package_payload_digest"))) is None):
            raise ValidationFailure("验收候选 target、Agent 或摘要无效")
        by_target[package["target"]] = package["package_payload_digest"]
    targets = record.get("targets")
    if not isinstance(targets, list) or len(targets) != len(INTERNAL_TARGETS):
        raise ValidationFailure("人工验收缺少原生目标")
    seen, references = set(), set()
    for item in targets:
        if (not isinstance(item, dict) or set(item) != {"target", "package_payload_digest", "os", "app", "cli", "provider"}
                or not isinstance(item.get("target"), str) or item["target"] not in by_target or item["target"] in seen
                or item.get("package_payload_digest") != by_target[item["target"]]):
            raise ValidationFailure("人工验收目标重复、遗漏或与包摘要不一致")
        target = item["target"]
        seen.add(target)
        operating = item["os"]
        if not isinstance(operating, dict) or set(operating) != {"name", "version"}:
            raise ValidationFailure("人工验收缺少真实操作系统")
        version = operating.get("version")
        if not isinstance(version, str) or re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version) is None:
            raise ValidationFailure("人工验收系统版本无效")
        if (target == "windows-x64" and (operating.get("name") != "Windows" or int(version.split(".")[0]) != 11)
                or target.startswith("macos-") and (operating.get("name") != "macOS" or int(version.split(".")[0]) < 14)):
            raise ValidationFailure("必须验收 macOS 14+ 或 Windows 11 原生宿主")
        for role in ("app", "cli", "provider"):
            reference = item[role]
            if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
                raise ValidationFailure("人工验收证据引用无效")
            name = reference.get("path")
            if not isinstance(name, str) or len(name) > 512:
                raise ValidationFailure("人工验收证据路径无效")
            _portable_member(name)
            path = PurePosixPath(name)
            if (len(path.parts) < 2 or path.parts[0] != "evidence" or path.suffix != ".json" or name in references
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", str(reference.get("sha256"))) is None):
                raise ValidationFailure("人工验收证据不能逃逸或复用其他会话")
            references.add(name)
            if storage is None:
                continue
            raw = storage.read_bytes_limited(MAX_CONTROL_BYTES, *path.parts)
            if _digest(raw) != reference["sha256"]:
                raise ValidationFailure("人工验收证据摘要不一致")
            try:
                evidence = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise ValidationFailure("人工验收证据不是有效 JSON") from None
            if (not isinstance(evidence, dict) or evidence.get("target") != target or evidence.get("os") != operating
                    or evidence.get("source_commit") != index["source_commit"]
                    or evidence.get("canonical_version") != index["canonical_version"]
                    or evidence.get("package_payload_digest") != by_target[target]):
                raise ValidationFailure("人工验收证据与真实系统、来源或候选身份不一致")
            checks = evidence.get("checks")
            if role == "provider":
                baselines = evidence.get("baselines")
                if (evidence.get("evidence_kind") != "provider_qualification" or evidence.get("qualified") is not True
                        or not isinstance(checks, dict) or set(checks) != REQUIRED_PROVIDER_CHECKS
                        or any(value is not True for value in checks.values()) or not isinstance(baselines, dict)
                        or any(baselines.get(name) is not True for name in ("network_ipv4", "network_ipv6"))):
                    raise ValidationFailure("人工验收 Provider 的完整隔离资格未通过")
            elif (evidence.get("evidence_kind") != "authenticated_codex_session" or evidence.get("entrypoint") != role
                    or evidence.get("authenticated") is not True or evidence.get("execution") != "native"
                    or not isinstance(checks, dict) or set(checks) != NATIVE_SESSION_CHECKS
                    or any(value != "passed" for value in checks.values())):
                raise ValidationFailure("人工验收必须包含真实已认证 App 与 CLI 会话，doctor 或 simulation 不能替代")


def acceptance_summary(index: dict, index_raw: bytes, record: dict, *, storage: ArtifactIO) -> dict:
    """Project validated private evidence into a public, non-attested receipt."""
    validate_acceptance(index, index_raw, record, storage=storage)
    return {
        "schema_version": "1", "evidence_kind": "release_acceptance_summary",
        "status": "accepted", "assurance": "local_unattested",
        "canonical_version": index["canonical_version"], "source_commit": index["source_commit"],
        "candidate_index_digest": _digest(index_raw),
        "acceptance_sha256": _digest(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()),
        "targets": [{"target": item["target"], "package_payload_digest": item["package_payload_digest"],
                     **{role: {"status": "passed", "sha256": item[role]["sha256"]}
                        for role in ("app", "cli", "provider")}}
                    for item in sorted(record["targets"], key=lambda item: item["target"])],
    }


def validate_acceptance_summary(index: dict, index_raw: bytes, summary: dict) -> None:
    """Consumers verify a maintainer summary; raw host evidence stays private."""
    fields = {"schema_version", "evidence_kind", "status", "assurance", "canonical_version",
              "source_commit", "candidate_index_digest", "acceptance_sha256", "targets"}
    digest = re.compile(r"sha256:[0-9a-f]{64}")
    if (not isinstance(summary, dict) or set(summary) != fields
            or summary.get("schema_version") != "1" or summary.get("evidence_kind") != "release_acceptance_summary"
            or summary.get("status") != "accepted" or summary.get("assurance") != "local_unattested"
            or summary.get("canonical_version") != index["canonical_version"]
            or summary.get("source_commit") != index["source_commit"]
            or summary.get("candidate_index_digest") != _digest(index_raw)
            or not isinstance(summary.get("acceptance_sha256"), str)
            or digest.fullmatch(summary["acceptance_sha256"]) is None):
        raise ValidationFailure("公开验收摘要缺失、来源不符或包含非公开字段")
    targets = summary["targets"]
    if not isinstance(targets, list) or len(targets) != len(INTERNAL_TARGETS):
        raise ValidationFailure("公开验收摘要必须覆盖三个原生目标")
    by_target = {package["target"]: package["package_payload_digest"] for package in index["packages"]}
    seen = set()
    for item in targets:
        if (not isinstance(item, dict) or set(item) != {"target", "package_payload_digest", "app", "cli", "provider"}
                or not isinstance(item.get("target"), str) or item["target"] not in by_target or item["target"] in seen
                or item["package_payload_digest"] != by_target[item["target"]]):
            raise ValidationFailure("公开验收目标重复、遗漏或包摘要不符")
        seen.add(item["target"])
        for role in ("app", "cli", "provider"):
            check = item[role]
            if (not isinstance(check, dict) or set(check) != {"status", "sha256"} or check.get("status") != "passed"
                    or not isinstance(check.get("sha256"), str) or digest.fullmatch(check["sha256"]) is None):
                raise ValidationFailure("公开验收摘要缺少 App、CLI 或完整 Provider 的通过记录")
