"""Read-only release identity, archive and acceptance contracts."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath

from ..runtime.catalog import DEFAULT_REPOSITORY_ROOT
from ..runtime.environment import PYTHON_VERSION
from ..runtime.artifact_io import ArtifactIO
from ..runtime.package import verify_package
from ..runtime.validation import ValidationFailure
from ..runtime.version import CanonicalVersion, platform_version

INTERNAL_AGENTS = ("codex",)


INTERNAL_TARGETS = ("macos-arm64", "windows-x64")


INTERNAL_REPOSITORY = "snbc-qihang/agent-skills"


MAX_CONTROL_BYTES = 1_048_576


MAX_FILE_BYTES = 64 * 1024 * 1024


MAX_TREE_BYTES = 512 * 1024 * 1024


MAX_TREE_ENTRIES = 16_384


REQUIRED_PROVIDER_CHECKS = frozenset({
    "positive_execution", "snapshot_read", "private_work_write", "network_ipv4", "network_ipv6",
    "outside_read", "outside_write", "snapshot_write", "child_process", "same_python_exec", "extra_exec",
})


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


def _portable_member(name: str, *, directory: bool = False) -> None:
    body = name[:-1] if directory and name.endswith("/") else name
    parts = body.split("/")
    for part in parts:
        if (not part or part in {".", ".."} or part.endswith((".", " "))
                or any(ord(character) < 32 or character in '<>:"\\|?*' for character in part)
                or re.fullmatch(r"(?i)(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?", part)):
            raise ValidationFailure("发行归档包含非便携或不安全路径")


def _required_wheel_files(repository_root: Path) -> set[str]:
    """Require the complete consumer module and resource layout, including lazy imports."""
    modules = repository_root / "src/engineering_assistant"
    if not modules.is_dir():
        modules = Path(__file__).resolve().parents[1]
    module_io = _safe_root(modules)
    try:
        required = {"engineering_assistant/" + name for name in _file_hashes(module_io)
                    if name.endswith(".py") and not name.startswith("tools/") and not any(part.startswith(".") for part in PurePosixPath(name).parts)}
    finally:
        module_io.close()
    for directory in ("catalog", "skills", "packs", "schemas", "config"):
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
        if any(name.startswith(("engineering_assistant/tools/", "engineering_assistant/_assets/evals/"))
               for name in names):
            raise ValidationFailure("消费者 setup wheel 不得包含作者工具或评测资产")
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
        if not re.search(r"(?m)^ea-setup\s*=\s*engineering_assistant\.installer\.setup_cli:main\s*$", read(prefix + "entry_points.txt")):
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
                or set(checks) != {"help", "doctor", "source_validation", "runtime_protocol"}
                or any(value != "passed" for value in checks.values())
                or _digest(storage.read_bytes_limited(MAX_FILE_BYTES, filename)) != _digest(raw)):
            raise ValidationFailure("setup wheel 隔离安装验证记录缺失、失败或与文件不一致")
        return receipt_raw, _digest(receipt_raw)
    except ValidationFailure:
        raise
    except (OSError, ValueError, TypeError):
        raise ValidationFailure("setup wheel 隔离安装验证记录缺失或无效") from None


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
        raise ValidationFailure("公开验收摘要必须覆盖两个原生目标")
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

def _verify_candidate(storage: ArtifactIO, *, allow_acceptance: bool = False) -> tuple[dict, bytes]:
    raw = storage.read_bytes_limited(MAX_CONTROL_BYTES, "release-index.json")
    try:
        index = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValidationFailure("候选发行 index 无效") from None
    if (not isinstance(index, dict) or index.get("schema_version") != "2" or index.get("status") != "candidate"
            or index.get("agents") != list(INTERNAL_AGENTS) or index.get("targets") != list(INTERNAL_TARGETS)):
        raise ValidationFailure("内部推广只接受完整 Codex 两目标候选")
    provenance = index_provenance(index)
    try:
        version = CanonicalVersion.parse(index.get("canonical_version", ""))
    except (TypeError, ValueError):
        raise ValidationFailure("候选发行版本无效") from None
    if index.get("release_tag") != "internal/codex/" + index["canonical_version"]:
        raise ValidationFailure("内部推广必须使用固定内部 namespace 的不可变版本 tag")
    files = _file_hashes(storage)
    allowed = {"release-index.json", "archives", "marketplaces", "setup", ".artifact.lock"}
    if allow_acceptance:
        allowed.add("acceptance-summary.json")
    if any(name.split("/")[0] not in allowed for name in files):
        raise ValidationFailure("候选发行含未知顶层文件")
    packages = index.get("packages")
    if not isinstance(packages, list) or len(packages) != len(INTERNAL_TARGETS):
        raise ValidationFailure("候选发行缺少目标包")
    seen = set()
    for entry in packages:
        if (not isinstance(entry, dict) or entry.get("target") not in INTERNAL_TARGETS
                or entry.get("agent") != "codex" or entry["target"] in seen
                or entry.get("canonical_version") != index["canonical_version"]):
            raise ValidationFailure("候选发行目标重复或身份错误")
        seen.add(entry["target"])
        target = entry["target"]
        tree = "marketplaces/codex/" + target
        archive = "archives/" + target + "/codex.zip"
        if (not isinstance(entry.get("marketplace"), dict) or not isinstance(entry.get("archive"), dict)
                or entry["marketplace"].get("path") != tree or entry["archive"].get("path") != archive):
            raise ValidationFailure("候选市场或归档路径不符合固定发行合同")
        if _digest(storage.read_bytes_limited(MAX_FILE_BYTES, *PurePosixPath(archive).parts)) != entry["archive"].get("sha256"):
            raise ValidationFailure("候选发行归档摘要不一致")
        with storage.open_directory(*PurePosixPath(tree).parts) as directory:
            tree_io = ArtifactIO.from_open_directory_fd(storage.path(*PurePosixPath(tree).parts), directory)
        try:
            if _tree_digest(_file_hashes(tree_io)) != entry["marketplace"].get("tree_sha256"):
                raise ValidationFailure("候选发行市场摘要不一致")
            package = tree_io.path("plugins", "engineering-assistant")
            manifest = verify_package(package)
            if (manifest.get("platform") != "codex" or manifest.get("target") != target
                    or manifest.get("canonical_version") != index["canonical_version"]
                    or manifest.get("payload_digest") != entry.get("package_payload_digest")):
                raise ValidationFailure("候选市场包与发行身份不一致")
        finally:
            tree_io.close()
    setup = index.get("setup", {})
    if not isinstance(setup, dict):
        raise ValidationFailure("候选 setup wheel 记录无效")
    wheel_name = PurePosixPath(str(setup.get("path", "")))
    if len(wheel_name.parts) != 2 or wheel_name.parts[0] != "setup" or wheel_name.suffix != ".whl":
        raise ValidationFailure("候选 setup wheel 路径无效")
    wheel = storage.read_bytes_limited(MAX_FILE_BYTES, *wheel_name.parts)
    if _digest(wheel) != setup.get("sha256"):
        raise ValidationFailure("候选 setup wheel 摘要不一致")
    receipt = setup.get("verification", {})
    if (not isinstance(receipt, dict) or receipt.get("path") != "setup/wheel-verification.json"
            or receipt.get("status") != "passed"):
        raise ValidationFailure("候选 setup wheel 缺少验证记录")
    raw_receipt = storage.read_bytes_limited(MAX_CONTROL_BYTES, "setup", "wheel-verification.json")
    if _digest(raw_receipt) != receipt.get("sha256"):
        raise ValidationFailure("候选 setup wheel 验证记录摘要不一致")
    wheel_version = _wheel_version(wheel, index["canonical_version"])
    with storage.open_directory("setup") as directory:
        setup_io = ArtifactIO.from_open_directory_fd(storage.path("setup"), directory)
    try:
        _wheel_verification(setup_io, wheel, wheel_name.name, wheel_version,
                                   index["canonical_version"], index["source_commit"], provenance)
    finally:
        setup_io.close()
    return index, raw
