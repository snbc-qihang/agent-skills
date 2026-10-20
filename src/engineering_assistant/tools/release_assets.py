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

from ..runtime.artifact_io import ArtifactIO, artifact_fs
from .compiler import verify_package
from ..runtime.catalog import DEFAULT_REPOSITORY_ROOT
from ..installer.installation import PYTHON_VERSION, TARGETS, _package_lock
from ..runtime.validation import ValidationFailure
from ..runtime.version import CanonicalVersion, platform_version

from ..installer.release_contract import (
    _wheel_record, _safe_root, INTERNAL_AGENTS, INTERNAL_TARGETS, INTERNAL_REPOSITORY, MAX_CONTROL_BYTES, MAX_FILE_BYTES, MAX_TREE_BYTES, MAX_TREE_ENTRIES, REQUIRED_PROVIDER_CHECKS, _digest, _tree_digest, _file_hashes, _record, release_provenance, index_provenance, _matches_provenance, _portable_member, _required_wheel_files, _wheel_version, _wheel_verification, _marketplace, validate_acceptance_summary
)

# A build adapter is not automatically a release-qualified host. Retain the
# existing advanced matrix; first internal delivery remains INTERNAL_AGENTS.
RELEASE_AGENTS = ("codex", "hermes", "claude-code")

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
        "test_readonly_file_deletion_preserves_an_external_hardlink",
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
            "test_windows_lpac_keeps_temporary_and_profile_options_in_private_work",
            "test_provider_runtime.ProviderRuntimeTests.test_windows_lpac_reads_and_writes_deep_unicode_paths",
            "test_provider_sandboxes.WindowsPrivatePythonTests.test_windows_private_worker_retains_token_restrictions",
        }
    return frozenset(required)


def release_scope(agents, targets) -> tuple[tuple[str, ...], tuple[str, ...]]:
    def selected(values, known, label):
        if (not isinstance(values, (list, tuple)) or not values
                or any(not isinstance(item, str) or item not in known for item in values)
                or len(set(values)) != len(values)):
            raise ValidationFailure("发行 " + label + " 集合为空、重复或包含未知值")
        return tuple(values)
    return selected(agents, RELEASE_AGENTS, "Agent"), selected(targets, TARGETS, "目标")


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
            raise ValidationFailure("正式内部编号只允许完整 Codex 两目标候选；其他稳定版发行仍被拒绝")
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
        raise ValidationFailure("内部发行验收必须精确覆盖 Codex 的两个原生目标")
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
