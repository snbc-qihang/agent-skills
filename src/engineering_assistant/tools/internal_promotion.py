"""Prepare immutable team tags, then activate a reviewed release in a public repository."""
from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from . import release_assets as assets
from ..runtime.artifact_io import ArtifactIO
from ..installer.installation import _protocol_run
from ..runtime.validation import ValidationFailure
from ..runtime.version import CanonicalVersion, platform_version

REMOTE = "https://github.com/" + assets.INTERNAL_REPOSITORY + ".git"
ALIAS = "refs/heads/internal/installer"
SOURCE_TAG_PREFIX = "internal/installer/"


from ..installer.release_contract import _verify_candidate

def _git(arguments: list[str], cwd: Path, *, environment: dict | None = None) -> str:
    selected = {key: value for key, value in os.environ.items() if key not in {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    } and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    selected.update(environment or {})
    selected.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="0", GIT_NO_REPLACE_OBJECTS="1")
    settings = ["-c", "core.hooksPath=" + str(cwd / ".git/no-hooks"), "-c", "init.templateDir=",
                "-c", "core.autocrlf=false", "-c", "core.filemode=true"]
    try:
        return _protocol_run(["git", *settings, *arguments], cwd=cwd, environment=selected, timeout=60).decode("utf-8").strip()
    except Exception:
        # Credential-helper and transport diagnostics may contain sensitive data.
        raise ValidationFailure("内部发行 Git 操作失败：" + arguments[0]) from None


def _remote_ref(reference: str, root: Path) -> str | None:
    output = _git(["ls-remote", "--refs", "origin", reference], root)
    if not output:
        return None
    lines = output.splitlines()
    if len(lines) != 1 or re.fullmatch(r"[0-9a-f]{40}\s+" + re.escape(reference), lines[0]) is None:
        raise ValidationFailure("内部发行远程 ref 身份不明确")
    return lines[0].split()[0]


def fixed_install_command(version: str, operation: str = "install") -> list[str]:
    return ["uvx", "--isolated", "--refresh", "--python", "3.13.13", "--from",
            "git+" + REMOTE + "@" + SOURCE_TAG_PREFIX + version,
            "ea-setup", operation, "--agent", "codex", "--json"]


def _reference(origin: ArtifactIO, snapshot: ArtifactIO, reference: dict) -> dict:
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
            or not isinstance(reference.get("path"), str) or len(reference["path"]) > 512
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(reference.get("sha256"))) is None):
        raise ValidationFailure("激活证据引用无效")
    name = reference["path"]
    assets._portable_member(name)
    parts = PurePosixPath(name).parts
    if len(parts) < 2 or parts[0] != "evidence" or not name.endswith(".json"):
        raise ValidationFailure("激活证据必须是 evidence 内的 JSON 文件")
    raw = origin.read_bytes_limited(assets.MAX_CONTROL_BYTES, *parts)
    if assets._digest(raw) != reference["sha256"]:
        raise ValidationFailure("激活证据摘要不符")
    if snapshot.entry_exists(*parts):
        if snapshot.read_bytes_limited(assets.MAX_CONTROL_BYTES, *parts) != raw:
            raise ValidationFailure("激活证据路径冲突")
    else:
        snapshot.write_bytes_exclusive(raw, *parts)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValidationFailure("激活证据不是有效 JSON") from None
    if not isinstance(value, dict):
        raise ValidationFailure("激活证据必须是对象")
    return value


def _command_receipt(origin: ArtifactIO, snapshot: ArtifactIO, reference: dict,
                     *, target: str, version: str, payload_digest: str | None,
                     source_commit: str, operation: str, native_paths: set[str]) -> dict:
    receipt = _reference(origin, snapshot, reference)
    required = {"schema_version", "evidence_kind", "command", "installer_origin", "exit_code",
                "result", "package", "native_selection"}
    command, result = receipt.get("command"), receipt.get("result")
    if (set(receipt) != required or receipt.get("schema_version") != "1"
            or receipt.get("evidence_kind") != "ea_setup_command" or type(receipt.get("exit_code")) is not int
            or not isinstance(command, list) or not 1 <= len(command) <= 64
            or any(not isinstance(part, str) or not part or len(part) > 4096 for part in command)
            or not isinstance(result, dict) or result.get("agent") != "codex"
            or result.get("target") != target or result.get("version") != version
            or (result.get("status"), receipt["exit_code"]) not in {("ready", 0), ("needs_trust", 2)}
            or result.get("runtime_ready") is not True
            or result.get("native_activation") != "enabled"):
        raise ValidationFailure("固定命令验收缺少真实成功结果或目标身份")
    if operation == "install":
        direct = receipt.get("installer_origin")
        vcs = direct.get("vcs_info") if isinstance(direct, dict) else None
        if (command != fixed_install_command(version) or not isinstance(vcs, dict)
                or direct.get("url") != REMOTE or vcs.get("vcs") != "git"
                or vcs.get("requested_revision") != SOURCE_TAG_PREFIX + version
                or vcs.get("commit_id") != source_commit or result.get("source_commit") != source_commit):
            raise ValidationFailure("固定命令必须来自已准备版本的 HTTPS Git tag 与真实 PEP 610")
    elif ("--json" not in command or not any(command[position:position + 2] == ["--agent", "codex"]
             for position in range(len(command) - 1)) or not any(
                command[position].replace("\\", "/").rsplit("/", 1)[-1] in {"ea-setup", "ea-setup.exe"}
                and command[position + 1] in ({"update"} if operation == "update" else {"doctor", "install"})
                for position in range(len(command) - 1))):
        raise ValidationFailure("BUILD 验收必须保留实际 Codex 安装器命令与 JSON 输出")
    package = receipt.get("package")
    if (not isinstance(package, dict) or set(package) != {"path", "manifest_sha256"}
            or not isinstance(package.get("path"), str) or len(package["path"]) > 512
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(package.get("manifest_sha256"))) is None):
        raise ValidationFailure("BUILD 验收缺少完整已安装包快照")
    assets._portable_member(package["path"])
    parts = PurePosixPath(package["path"]).parts
    if len(parts) < 3 or parts[:2] != ("evidence", "packages"):
        raise ValidationFailure("已安装包快照必须位于 evidence/packages")
    if not snapshot.entry_exists(*parts):
        snapshot.ensure_directory(*parts)
        with origin.open_directory(*parts) as descriptor:
            source = ArtifactIO.from_open_directory_fd(origin.path(*parts), descriptor)
        with snapshot.open_directory(*parts) as descriptor:
            destination = ArtifactIO.from_open_directory_fd(snapshot.path(*parts), descriptor)
        try:
            assets._copy(source, destination)
        finally:
            source.close()
            destination.close()
    with snapshot.open_directory(*parts) as descriptor:
        package_io = ArtifactIO.from_open_directory_fd(snapshot.path(*parts), descriptor)
    try:
        manifest_raw = package_io.read_bytes_limited(assets.MAX_CONTROL_BYTES, "package-manifest.json")
        if assets._digest(manifest_raw) != package["manifest_sha256"]:
            raise ValidationFailure("已安装包 manifest 摘要不符")
        manifest = assets.verify_package(package_io.path())
    finally:
        package_io.close()
    if (manifest.get("platform") != "codex" or manifest.get("target") != target
            or manifest.get("canonical_version") != version
            or payload_digest is not None and manifest.get("payload_digest") != payload_digest):
        raise ValidationFailure("BUILD 验收的完整包身份与候选不符")
    native_reference = receipt["native_selection"]
    native = _reference(origin, snapshot, native_reference)
    if native_reference["path"] in native_paths:
        raise ValidationFailure("不同安装操作必须分别采集原生插件列表")
    native_paths.add(native_reference["path"])
    entries = native.get("installed")
    if not isinstance(entries, list) or len(entries) > 256 or any(not isinstance(entry, dict) for entry in entries):
        raise ValidationFailure("BUILD 验收缺少真实原生插件列表")
    selected = [entry for entry in entries if entry.get("name") == "engineering-assistant" and entry.get("installed") is True
                and (result.get("marketplace") is None or entry.get("marketplaceName") == result["marketplace"])]
    if len(selected) != 1:
        raise ValidationFailure("BUILD 验收的原生选择不唯一")
    marketplace = selected[0].get("marketplaceName")
    mapped = platform_version(version, supports_four_part=False)
    if (not isinstance(marketplace, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", marketplace) is None
            or selected[0].get("enabled") is not True or selected[0].get("version") != mapped
            or selected[0].get("pluginId", "engineering-assistant@" + marketplace) != "engineering-assistant@" + marketplace):
        raise ValidationFailure("BUILD 验收的原生选择与完整四段版本映射不符")
    installed_path = result.get("package")
    suffix = "/plugins/cache/" + marketplace + "/engineering-assistant/" + mapped
    if not isinstance(installed_path, str) or not installed_path.replace("\\", "/").rstrip("/").endswith(suffix):
        raise ValidationFailure("BUILD 完整包快照未绑定实际原生缓存选择")
    return manifest


def _activation_snapshot(index: dict, index_raw: bytes, path: Path, destination: Path) -> ArtifactIO:
    origin = assets._safe_root(path.absolute().parent)
    destination.mkdir()
    snapshot = ArtifactIO(destination, ".")
    try:
        raw = origin.read_bytes_limited(assets.MAX_CONTROL_BYTES, path.name)
        wrapper = json.loads(raw)
        fields = {"schema_version", "repository_url", "installer_ref", "transport", "acceptance", "build_updates"}
        version = index["canonical_version"]
        if (not isinstance(wrapper, dict) or set(wrapper) != fields or wrapper.get("schema_version") != "1"
                or wrapper.get("repository_url") != REMOTE or wrapper.get("installer_ref") != SOURCE_TAG_PREFIX + version
                or wrapper.get("transport") != "https_git"):
            raise ValidationFailure("激活验收必须绑定精确版本的 HTTPS 固定安装命令")
        record = wrapper["acceptance"]
        assets.validate_acceptance(index, index_raw, record)
        snapshot.write_bytes_exclusive(raw, "activation.json")
        snapshot.write_bytes_exclusive(index_raw, "release-index.json")
        for item in record["targets"]:
            for role in ("app", "cli", "provider"):
                _reference(origin, snapshot, item[role])
        assets.validate_acceptance(index, index_raw, record, storage=snapshot)
        updates = wrapper.get("build_updates")
        if not isinstance(updates, list) or len(updates) != len(assets.INTERNAL_TARGETS):
            raise ValidationFailure("激活验收缺少两个目标的 BUILD 更新")
        current = CanonicalVersion.parse(version)
        following = CanonicalVersion(current.major, current.minor, current.patch, current.build + 1, current.prerelease).canonical()
        by_target = {entry["target"]: entry for entry in index["packages"]}
        seen, receipt_paths, receipt_digests, native_paths = set(), set(), set(), set()
        for update in updates:
            if (not isinstance(update, dict) or set(update) != {"target", "install", "before_update", "update"}
                    or not isinstance(update.get("target"), str) or update["target"] not in by_target or update["target"] in seen):
                raise ValidationFailure("BUILD 更新目标重复、遗漏或字段无效")
            target = update["target"]
            seen.add(target)
            for operation in ("install", "before_update", "update"):
                reference = update[operation]
                _reference(origin, snapshot, reference)
                if reference["path"] in receipt_paths or reference["sha256"] in receipt_digests:
                    raise ValidationFailure("不同安装操作不能复用同一命令收据")
                receipt_paths.add(reference["path"])
                receipt_digests.add(reference["sha256"])
                manifest = _command_receipt(origin, snapshot, reference, target=target,
                    version=following if operation == "update" else version,
                    payload_digest=None if operation == "update" else by_target[target]["package_payload_digest"],
                    source_commit=index["source_commit"], operation=operation, native_paths=native_paths)
                if operation == "update" and manifest["payload_digest"] == by_target[target]["package_payload_digest"]:
                    raise ValidationFailure("BUILD 更新没有选择不同的新版本包")
        assets._file_hashes(snapshot)
        return snapshot
    except ValidationFailure:
        snapshot.close()
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        snapshot.close()
        raise ValidationFailure("激活验收结构、文件或命令记录无效") from None
    finally:
        origin.close()


def _gh(arguments: list[str], root: Path, *, input_data: bytes = b"") -> bytes:
    environment = {key: value for key, value in os.environ.items() if key not in {"GH_HOST", "GH_REPO", "GH_DEBUG"}}
    environment.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1")
    try:
        return _protocol_run(["gh", *arguments], cwd=root, input_data=input_data, environment=environment, timeout=60)
    except Exception:
        raise ValidationFailure("维护者 GitHub 操作失败；请核对鉴权、权限和远程状态") from None


def _api(endpoint: str, root: Path, *, method: str = "GET", payload: dict | None = None):
    arguments = ["api", "--hostname", "github.com", "--method", method, endpoint]
    body = b""
    if payload is not None:
        arguments += ["--input", "-"]
        body = json.dumps(payload, ensure_ascii=False).encode()
    try:
        return json.loads(_gh(arguments, root, input_data=body))
    except (ValueError, UnicodeDecodeError):
        raise ValidationFailure("GitHub 返回无法核验的 JSON") from None


def _public_repository(root: Path) -> None:
    repo = _api("repos/" + assets.INTERNAL_REPOSITORY, root)
    if (not isinstance(repo, dict) or repo.get("full_name") != assets.INTERNAL_REPOSITORY
            or repo.get("private") is not False or repo.get("visibility") != "public" or repo.get("archived") is not False):
        raise ValidationFailure("团队推广只允许固定且未归档的公开 GitHub 仓库")


def _release_by_tag(tag: str, root: Path) -> dict | None:
    for page in range(1, 17):
        releases = _api("repos/" + assets.INTERNAL_REPOSITORY + "/releases?per_page=100&page=" + str(page), root)
        if not isinstance(releases, list) or len(releases) > 100 or any(not isinstance(item, dict) for item in releases):
            raise ValidationFailure("GitHub Release 列表结构无效")
        found = [item for item in releases if item.get("tag_name") == tag]
        if len(found) > 1:
            raise ValidationFailure("同版本 GitHub Release 身份不明确")
        if found:
            return found[0]
        if len(releases) < 100:
            return None
    raise ValidationFailure("GitHub Release 列表超过有界核验范围，不能推断版本不存在")


def _release_body(index: dict, notes: bytes, bundle: Path) -> str:
    try:
        text = notes.decode("utf-8")
    except UnicodeDecodeError:
        raise ValidationFailure("Release 教程必须是 UTF-8 文本") from None
    expected = " ".join(fixed_install_command(index["canonical_version"])[:-1])
    lines = [line.strip().replace('"', "").replace("'", "") for line in text.splitlines()]
    if (not text.strip() or index["canonical_version"] not in text
            or not any(line in {expected, expected + " --json"} for line in lines)):
        raise ValidationFailure("Release 教程必须包含候选版本和精确固定 install 命令")
    return text.rstrip() + "\n\n" + "\n".join((
        "内部验收绑定：", "- source_commit: " + index["source_commit"],
        "- release_tag: " + index["release_tag"],
        "- installer_ref: " + SOURCE_TAG_PREFIX + index["canonical_version"],
        "- notes_sha256: " + assets._digest(notes),
        "- activation_summary_sha256: " + assets._digest(bundle.read_bytes()))) + "\n"


def _activation_summary(index: dict, index_raw: bytes, snapshot: ArtifactIO) -> dict:
    raw = snapshot.read_bytes_limited(assets.MAX_CONTROL_BYTES, "activation.json")
    wrapper = json.loads(raw)
    current = CanonicalVersion.parse(index["canonical_version"])
    following = CanonicalVersion(current.major, current.minor, current.patch, current.build + 1, current.prerelease).canonical()
    return {"schema_version": "1", "evidence_kind": "release_activation_summary", "status": "accepted",
            "assurance": "local_unattested", "canonical_version": index["canonical_version"],
            "source_commit": index["source_commit"], "candidate_index_digest": assets._digest(index_raw),
            "activation_sha256": assets._digest(raw),
            "acceptance": assets.acceptance_summary(index, index_raw, wrapper["acceptance"], storage=snapshot),
            "build_updates": [{"target": update["target"], "from_version": current.canonical(), "to_version": following,
                               **{operation + "_sha256": update[operation]["sha256"]
                                  for operation in ("install", "before_update", "update")}}
                              for update in sorted(wrapper["build_updates"], key=lambda update: update["target"])]}


def _check_release(release: dict, index: dict, body: str) -> int:
    identifier = release.get("id") if isinstance(release, dict) else None
    if (type(identifier) is not int or identifier < 1 or release.get("tag_name") != index["release_tag"]
            or release.get("body") != body or release.get("name") != "engineering-assistant " + index["canonical_version"] + "（内部）"
            or type(release.get("draft")) is not bool
            or release.get("prerelease") is not (CanonicalVersion.parse(index["canonical_version"]).prerelease is not None)
            or release.get("url") != "https://api.github.com/repos/" + assets.INTERNAL_REPOSITORY + "/releases/" + str(identifier)):
        raise ValidationFailure("现有 Release 的仓库、版本、教程或验收绑定不同，不会覆盖")
    return identifier


def _ensure_release(index: dict, root: Path, body: str, bundle: Path, notes: Path) -> dict:
    published, modified = None, False
    prefix = "repos/" + assets.INTERNAL_REPOSITORY + "/releases"
    try:
        release = _release_by_tag(index["release_tag"], root)
        if release is None:
            published = False
            release = _api(prefix, root, method="POST", payload={"tag_name": index["release_tag"],
                "name": "engineering-assistant " + index["canonical_version"] + "（内部）", "body": body,
                "draft": True, "prerelease": CanonicalVersion.parse(index["canonical_version"]).prerelease is not None, "make_latest": "false"})
            modified = True
        identifier = _check_release(release, index, body)
        published = not release["draft"]
        expected = {bundle.name: bundle, notes.name: notes}
        for name, path in expected.items():
            current = _api(prefix + "/" + str(identifier), root)
            _check_release(current, index, body)
            entries = current.get("assets")
            if (not isinstance(entries, list) or len(entries) > 16
                    or any(not isinstance(item, dict) or item.get("name") not in expected for item in entries)):
                raise ValidationFailure("Release 包含未知或无法核验的资产")
            matches = [item for item in entries if item["name"] == name]
            if len(matches) > 1:
                raise ValidationFailure("Release 证据资产重复")
            if not matches:
                if not current["draft"]:
                    raise ValidationFailure("已发布 Release 缺少验收资产，不会补写或推进 alias")
                _gh(["release", "upload", index["release_tag"], str(path), "--repo", "github.com/" + assets.INTERNAL_REPOSITORY], root)
                modified = True
                current = _api(prefix + "/" + str(identifier), root)
                _check_release(current, index, body)
                matches = [item for item in current.get("assets", []) if isinstance(item, dict) and item.get("name") == name]
            if (len(matches) != 1 or matches[0].get("state") != "uploaded"
                    or type(matches[0].get("size")) is not int or matches[0]["size"] != path.stat().st_size
                    or path.stat().st_size > assets.MAX_TREE_BYTES + assets.MAX_TREE_ENTRIES * 1024):
                raise ValidationFailure("Release 证据资产上传或大小核验失败")
            download = root.parent / ("download-" + name)
            download.mkdir()
            _gh(["release", "download", index["release_tag"], "--pattern", name, "--dir", str(download),
                 "--repo", "github.com/" + assets.INTERNAL_REPOSITORY], root)
            reader = assets._safe_root(download)
            try:
                actual = reader.read_bytes_limited(assets.MAX_TREE_BYTES + assets.MAX_TREE_ENTRIES * 1024, name)
            finally:
                reader.close()
            if assets._digest(actual) != assets._digest(path.read_bytes()):
                raise ValidationFailure("Release 资产实际字节摘要与已验收输入不符")
        current = _api(prefix + "/" + str(identifier), root)
        _check_release(current, index, body)
        if current["draft"]:
            published = None
            current = _api(prefix + "/" + str(identifier), root, method="PATCH", payload={"draft": False, "make_latest": "false"})
            _check_release(current, index, body)
            modified = True
            published = not current["draft"]
        current = _api(prefix + "/" + str(identifier), root)
        _check_release(current, index, body)
        published = not current["draft"]
        if not published:
            raise ValidationFailure("Release 仍是草稿，alias 未推广")
        return {"status": "published", "release_published": True, "remote_modified": modified,
                "release_url": "https://github.com/" + assets.INTERNAL_REPOSITORY + "/releases/tag/" + index["release_tag"]}
    except ValidationFailure as error:
        return {"status": "failed", "reason": str(error), "release_published": published,
                "remote_modified": modified or None}
    except (OSError, TypeError, ValueError, KeyError, AttributeError):
        return {"status": "failed", "reason": "Release 状态无法核验，alias 未推广", "release_published": published,
                "remote_modified": modified or None}


def _local_commit(index: dict, record: dict, root: Path) -> tuple[str, str]:
    _git(["init", "--quiet"], root)
    _git(["remote", "add", "origin", REMOTE], root)
    _git(["fetch", "--no-tags", "--depth=1", "origin", index["source_commit"]], root)
    try:
        catalog = json.loads(_git(["show", index["source_commit"] + ":catalog/skills/public.json"], root))
    except (ValueError, UnicodeDecodeError):
        raise ValidationFailure("远程源码 catalog 无法核验") from None
    if not isinstance(catalog, dict) or catalog.get("version") != index["canonical_version"]:
        raise ValidationFailure("远程源码版本与候选发行不一致")
    _git(["add", "--all"], root)
    for target in assets.INTERNAL_TARGETS:
        executable = "ea.exe" if target == "windows-x64" else "ea"
        _git(["update-index", "--chmod=+x", "marketplaces/codex/" + target
              + "/plugins/engineering-assistant/engineering-assistant/bin/" + executable], root)
    _git(["-c", "user.name=engineering-assistant publisher", "-c", "user.email=sunliming625@gmail.com",
          "commit", "--quiet", "-m", "build: 内部 Codex 发行 " + index["canonical_version"]], root,
         environment={"GIT_AUTHOR_DATE": record["reviewed_at"], "GIT_COMMITTER_DATE": record["reviewed_at"]})
    generated, tree = _git(["rev-parse", "HEAD"], root), _git(["rev-parse", "HEAD^{tree}"], root)
    if any(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in (generated, tree)):
        raise ValidationFailure("本地发行 Git 身份无效")
    return generated, tree


def _tag_identity(root: Path, reference: str, *, commit: str | None = None, tree: str | None = None) -> str | None:
    existing = _remote_ref(reference, root)
    if existing is None:
        return None
    _git(["fetch", "--no-tags", "--depth=1", "origin", reference], root)
    actual = _git(["rev-parse", "FETCH_HEAD^{commit}"], root)
    actual_tree = _git(["rev-parse", "FETCH_HEAD^{tree}"], root) if tree is not None else None
    if commit is not None and actual != commit or tree is not None and actual_tree != tree:
        raise ValidationFailure("不可变内部 tag 已存在且内容不同，不会覆盖")
    return existing


def promote(candidate: Path | str, acceptance: Path | str, *, phase: str = "prepare",
            activation: Path | str | None = None, release_notes: Path | str | None = None,
            expected_alias: str | None = None, execute: bool = False) -> dict:
    """Prepare immutable tags first; publish reviewed instructions before alias activation."""
    if phase not in {"prepare", "activate"}:
        raise ValidationFailure("推广 phase 必须是 prepare 或 activate")
    if phase == "activate" and (activation is None or release_notes is None
            or expected_alias != "absent" and (not isinstance(expected_alias, str) or re.fullmatch(r"[0-9a-f]{40}", expected_alias) is None)):
        raise ValidationFailure("activate 需要固定命令验收、Release 教程和明确旧 alias commit 或 absent")
    with tempfile.TemporaryDirectory(prefix="ea-internal-promotion-") as temporary, ExitStack() as stack:
        root = Path(temporary).resolve() / "release"
        root.mkdir()
        storage = ArtifactIO(root, ".")
        stack.callback(storage.close)
        source = assets._safe_root(candidate)
        stack.callback(source.close)
        evidence = assets._safe_root(Path(acceptance).absolute().parent)
        stack.callback(evidence.close)
        assets._copy(source, storage)
        index, index_raw = _verify_candidate(storage)
        acceptance_raw = evidence.read_bytes_limited(assets.MAX_CONTROL_BYTES, Path(acceptance).name)
        try:
            record = json.loads(acceptance_raw)
        except (ValueError, UnicodeDecodeError):
            raise ValidationFailure("人工验收记录无效") from None
        assets.validate_acceptance(index, index_raw, record)
        private_root = root.parent / "acceptance"
        private_root.mkdir()
        private = ArtifactIO(private_root, ".")
        stack.callback(private.close)
        for item in record["targets"]:
            for role in ("app", "cli", "provider"):
                _reference(evidence, private, item[role])
        summary = assets.acceptance_summary(index, index_raw, record, storage=private)
        assets.validate_acceptance_summary(index, index_raw, summary)
        storage.create_immutable_json(summary, "acceptance-summary.json")
        source_tag = SOURCE_TAG_PREFIX + index["canonical_version"]
        common = {"phase": phase, "release_tag": index["release_tag"], "installer_tag": source_tag,
                  "alias": ALIAS, "alias_promoted": False}
        if phase == "activate":
            snapshot = _activation_snapshot(index, index_raw, Path(activation), root.parent / "activation")
            stack.callback(snapshot.close)
            bundle = root.parent / "activation-summary.json"
            bundle.write_text(json.dumps(_activation_summary(index, index_raw, snapshot), sort_keys=True) + "\n", encoding="utf-8")
            notes_reader = assets._safe_root(Path(release_notes).absolute().parent)
            stack.callback(notes_reader.close)
            notes = root.parent / "installation.md"
            notes_raw = notes_reader.read_bytes_limited(assets.MAX_CONTROL_BYTES, Path(release_notes).name)
            notes.write_bytes(notes_raw)
            body = _release_body(index, notes_raw, bundle)
        if not execute:
            return {**common, "status": "ready_for_" + phase, "remote_modified": False,
                    "remote_checked": False, "requires_explicit_yes": True}
        _public_repository(root)
        storage.delete_regular_file(".artifact.lock")
        generated, tree = _local_commit(index, record, root)
        payload_ref, source_ref = "refs/tags/" + index["release_tag"], "refs/tags/" + source_tag
        payload = _tag_identity(root, payload_ref, tree=tree)
        installer = _tag_identity(root, source_ref, commit=index["source_commit"])
        if phase == "prepare":
            modified = False
            for reference, existing, revision in ((payload_ref, payload, generated), (source_ref, installer, index["source_commit"])):
                if existing is not None:
                    continue
                try:
                    _git(["push", "origin", revision + ":" + reference], root)
                except ValidationFailure:
                    try:
                        observed = _remote_ref(reference, root)
                    except ValidationFailure:
                        observed = None
                    if observed != revision:
                        return {**common, "status": "failed", "reason": "不可变 tag 推送结果未能核对；不删除任何 ref",
                                "remote_modified": True if modified else None, "remote_checked": False}
                modified = True
                try:
                    verified = _remote_ref(reference, root) == revision
                except ValidationFailure:
                    verified = False
                if not verified:
                    return {**common, "status": "failed", "reason": "不可变 tag 已尝试写入但身份暂不可核验；保留 tag，alias 未修改",
                            "remote_modified": True, "remote_checked": False}
            return {**common, "status": "prepared", "remote_modified": modified, "remote_checked": True,
                    "payload_tag_verified": True, "source_tag_verified": True, "release_published": False}
        if payload is None or installer is None:
            raise ValidationFailure("activate 只能核对 prepare 已存在的两个不可变 tag，不会创建缺失 tag")
        expected = None if expected_alias == "absent" else expected_alias
        observed = _remote_ref(ALIAS, root)
        if observed not in {expected, index["source_commit"]}:
            raise ValidationFailure("installer alias 已变化；尚未创建或发布 Release")
        release = _ensure_release(index, root, body, bundle, notes)
        if release["status"] != "published":
            return {**common, **release, "status": "failed"}
        alias_attempted = False
        try:
            _public_repository(root)
            if _remote_ref(payload_ref, root) != payload or _remote_ref(source_ref, root) != installer:
                raise ValidationFailure("不可变 tag 在激活期间改变，alias 未推进")
            if observed != index["source_commit"]:
                lease = "--force-with-lease=" + ALIAS + ":" + (expected or "")
                try:
                    alias_attempted = True
                    _git(["push", lease, "origin", index["source_commit"] + ":" + ALIAS], root)
                except ValidationFailure:
                    pass
            actual = _remote_ref(ALIAS, root)
        except ValidationFailure:
            return {**common, **release, "status": "failed", "alias_promoted": None,
                    "remote_modified": True if release["remote_modified"] else None,
                    "reason": "Release 已发布，alias 或 tag 状态暂不可核验；请核对后重试"}
        if actual != index["source_commit"]:
            return {**common, **release, "status": "failed", "alias_promoted": False,
                    "remote_modified": True if release["remote_modified"] else None if alias_attempted else False,
                    "reason": "Release 已发布，当前 alias 未指向本版；无法确认本次 CAS 是否曾写入，保留 Release 和两个 tag"}
        return {**common, **release, "status": "promoted", "alias_promoted": True,
                "remote_modified": release["remote_modified"] or alias_attempted, "remote_checked": True}
