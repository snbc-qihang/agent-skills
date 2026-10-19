"""Public Git transport and local integrity tests; no native host qualification."""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant import internal_distribution as distribution
from engineering_assistant.artifact_io import ArtifactIO
from engineering_assistant.installation import runtime_lock, python_download_metadata
from engineering_assistant.release_assets import NATIVE_SESSION_CHECKS, REQUIRED_PROVIDER_CHECKS, acceptance_summary
from engineering_assistant.validation import ValidationFailure
import test_release_assets as release_fixtures

VERSION = "2.3.0.0-rc.1"
SOURCE = "a" * 40
URL = "https://github.com/snbc-qihang/agent-skills.git"
TAG = "internal/codex/" + VERSION


def digest(payload):
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


class InternalDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.release = self.root / "release"
        self.release.mkdir()
        self.private = self.root / "acceptance-input"
        packages = []
        self.index = {"schema_version": "2", "status": "candidate", "canonical_version": VERSION,
            "source_commit": SOURCE, "release_tag": TAG, "agents": ["codex"],
            "assurance": "ci_artifacts_unattested",
            "targets": list(distribution.INTERNAL_TARGETS),
            "ci_identity": {"repository": "snbc-qihang/agent-skills", "run_id": "123", "run_attempt": 1},
            "packages": packages}
        for target in distribution.INTERNAL_TARGETS:
            market = self.release / "marketplaces/codex" / target
            package = market / "plugins/engineering-assistant"
            package.mkdir(parents=True)
            lock, requirements = runtime_lock(ROOT, "codex", target, VERSION)
            files = {".codex-plugin/plugin.json": b"{}", ".mcp.json": b"{}", "hooks/hooks.json": b"{}",
                "hooks/feedback_capture.py": b"# fixture", "engineering-assistant/runtime_boot.py": b"# fixture",
                "engineering-assistant/runtime-lock.json": json.dumps(lock).encode(),
                "engineering-assistant/runtime-requirements.txt": requirements,
                "engineering-assistant/runtime-python-downloads.json": python_download_metadata(lock)}
            # Machine headers are sufficient for package integrity checks; these
            # inert test bytes are never executed and do not model Codex or LPAC.
            if target == "windows-x64":
                header = bytearray(128)
                header[:2] = b"MZ"
                struct.pack_into("<I", header, 60, 64)
                header[64:68] = b"PE\0\0"
                struct.pack_into("<H", header, 68, 0x8664)
            else:
                header = b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C if target == "macos-arm64" else 0x01000007)
            executable = "engineering-assistant/bin/" + ("ea.exe" if target == "windows-x64" else "ea")
            files[executable] = bytes(header)
            for name, payload in files.items():
                path = package / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            (package / executable).chmod(0o700)
            hashes = {name: digest(payload) for name, payload in sorted(files.items())}
            payload_digest = digest("\n".join(f"{name}:{value}" for name, value in hashes.items()).encode())
            write(package / "package-manifest.json", {"build_format_version": "2.0", "status": "built",
                "platform": "codex", "canonical_version": VERSION, "target": target,
                "runtime_environment_key": lock["environment_key"], "skill_versions": {},
                "skill_count": 0, "flow_count": 0, "pack_count": 0, "policy_count": 0,
                "provider_count": 0, "source_count": 0, "payload_files": hashes, "payload_digest": payload_digest})
            write(market / ".agents/plugins/marketplace.json", {"name": "engineering-assistant"})
            with closing(ArtifactIO(market, ".")) as storage:
                tree_digest = distribution._tree_digest(storage)
            archive = "archives/" + target + "/codex.zip"
            path = self.release / archive
            path.parent.mkdir(parents=True)
            path.write_bytes(b"unused synthetic archive " + target.encode())
            packages.append({"agent": "codex", "target": target, "canonical_version": VERSION,
                "package_payload_digest": payload_digest,
                "archive": {"path": archive, "sha256": digest(path.read_bytes())},
                "marketplace": {"path": "marketplaces/codex/" + target, "tree_sha256": tree_digest}})
        setup = self.release / "setup"
        setup.mkdir()
        fixture = release_fixtures.ReleaseAssetTests()
        fixture.wheel = setup / "fixture.whl"
        fixture.make_wheel()
        self.index["setup"] = {"path": "setup/fixture.whl", "sha256": digest((setup / "fixture.whl").read_bytes()),
            "verification": {"path": "setup/wheel-verification.json", "status": "passed",
                             "sha256": digest((setup / "wheel-verification.json").read_bytes())}}
        self.write_index()

    def write_index(self):
        write(self.release / "release-index.json", self.index)
        self.record = {"schema_version": "1", "status": "accepted", "canonical_version": VERSION,
            "source_commit": SOURCE, "candidate_index_digest": digest((self.release / "release-index.json").read_bytes()),
            "reviewer_ref": "synthetic-protocol-test", "reviewed_at": "2026-10-08T01:00:00Z", "targets": []}
        for package in self.index["packages"]:
            target = package["target"]
            item = {"target": target, "package_payload_digest": package["package_payload_digest"],
                "os": {"name": "Windows" if target == "windows-x64" else "macOS",
                       "version": "11" if target == "windows-x64" else "14.0"}}
            for role in ("app", "cli", "provider"):
                evidence = {"target": target, "os": item["os"], "canonical_version": VERSION,
                    "source_commit": SOURCE, "package_payload_digest": package["package_payload_digest"]}
                if role == "provider":
                    evidence.update(evidence_kind="provider_qualification", qualified=True,
                        checks={name: True for name in REQUIRED_PROVIDER_CHECKS},
                        baselines={"network_ipv4": True, "network_ipv6": True})
                else:
                    evidence.update(evidence_kind="authenticated_codex_session", entrypoint=role,
                        authenticated=True, execution="native", checks={name: "passed" for name in NATIVE_SESSION_CHECKS})
                name = "evidence/" + target + "-" + role + ".json"
                write(self.private / name, evidence)
                item[role] = {"path": name, "sha256": digest((self.private / name).read_bytes())}
            self.record["targets"].append(item)
        with closing(ArtifactIO(self.private, ".")) as storage:
            self.summary = acceptance_summary(self.index, (self.release / "release-index.json").read_bytes(), self.record, storage=storage)
        write(self.release / "acceptance-summary.json", self.summary)

    def verify(self, *, target="macos-arm64", source_commit=SOURCE, version=VERSION, tag=TAG):
        with closing(ArtifactIO(self.release, ".")) as storage:
            return distribution.verify_release(storage, version=version, source_commit=source_commit, target=target, tag=tag)

    def git_release(self):
        if not shutil.which("git"):
            self.skipTest("Git is required for the transport protocol test")
        repo = self.root / "repository"
        shutil.copytree(self.release, repo)
        for arguments in (("init",), ("add", "."), ("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "synthetic"), ("tag", TAG)):
            subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True)
        return repo

    def acquire(self, data, repository):
        from engineering_assistant.installation import _read_control
        spec = {"repository_url": str(repository), "release_tag_prefix": "internal/codex/", "marketplace": "engineering-assistant"}
        with mock.patch.object(distribution, "internal_spec", return_value=spec), mock.patch.object(
            distribution, "installer_source_commit", return_value=SOURCE), mock.patch(
            "engineering_assistant.installation._read_control", side_effect=lambda path:
                {"version": VERSION} if Path(path).name == "public.json" else _read_control(path)):
            return distribution.acquire_internal_release(data, "macos-arm64")

    def test_pep610_requires_the_validated_installer_ref_and_exact_git_origin(self):
        info = self.root / "engineering_assistant_kernel-0.dist-info"
        info.mkdir()
        origin = {"url": URL, "vcs_info": {"vcs": "git", "commit_id": SOURCE, "requested_revision": "internal/installer"}}
        for change, accepted in (({}, True), ({"requested_revision": "main"}, False), ({"commit_id": "a" * 39}, False), ({"vcs": "hg"}, False)):
            value = copy.deepcopy(origin)
            value["vcs_info"].update(change)
            write(info / "direct_url.json", value)
            actual = importlib.metadata.Distribution.at(info)
            with self.subTest(change=change), mock.patch.object(importlib.metadata, "distribution", return_value=actual):
                if accepted:
                    self.assertEqual(SOURCE, distribution.installer_source_commit(URL))
                else:
                    with self.assertRaises(ValidationFailure):
                        distribution.installer_source_commit(URL)
        origin["url"] = "https://secret-token@github.com/snbc-qihang/agent-skills.git"
        write(info / "direct_url.json", origin)
        with mock.patch.object(importlib.metadata, "distribution", return_value=importlib.metadata.Distribution.at(info)):
            with self.assertRaises(ValidationFailure) as raised:
                distribution.installer_source_commit(URL)
        self.assertNotIn("secret-token", str(raised.exception))

    def test_pep610_accepts_only_the_current_version_immutable_source_tag(self):
        info = self.root / "immutable.dist-info"
        info.mkdir()
        origin = {"url": URL, "vcs_info": {"vcs": "git", "commit_id": SOURCE,
                  "requested_revision": "internal/installer/" + VERSION}}
        write(info / "direct_url.json", origin)
        with mock.patch.object(importlib.metadata, "distribution", return_value=importlib.metadata.Distribution.at(info)):
            self.assertEqual(SOURCE, distribution.installer_source_commit(URL, version=VERSION))
            with self.assertRaises(ValidationFailure):
                distribution.installer_source_commit(URL, version="1.0.0.2")

    def test_valid_release_uses_real_manifest_and_public_acceptance_summary(self):
        index, entry = self.verify()
        self.assertEqual(self.index, index)
        self.assertEqual("macos-arm64", entry["target"])
        self.assertFalse((self.release / "evidence").exists())
        self.summary["targets"][2]["provider"]["status"] = "not_run"
        write(self.release / "acceptance-summary.json", self.summary)
        with self.assertRaisesRegex(ValidationFailure, "Provider"):
            self.verify()

    def test_public_summary_rejects_private_fields_missing_roles_and_wrong_bindings(self):
        mutations = (
            lambda summary: summary.update(reviewer_ref="private@example.invalid"),
            lambda summary: summary.update(source_commit="b" * 40),
            lambda summary: summary.update(candidate_index_digest="sha256:" + "b" * 64),
            lambda summary: summary.update(targets=summary["targets"][:-1]),
            lambda summary: summary["targets"][0].pop("app"),
            lambda summary: summary["targets"][0]["cli"].update(path="/Users/private/session.json"),
            lambda summary: summary["targets"][0].update(package_payload_digest="sha256:" + "b" * 64),
            lambda summary: summary["targets"][0].update(target=[]),
            lambda summary: summary.update(assurance="cryptographically_verified"),
        )
        for position, change in enumerate(mutations):
            summary = copy.deepcopy(self.summary)
            change(summary)
            write(self.release / "acceptance-summary.json", summary)
            with self.subTest(case=position), self.assertRaises(ValidationFailure):
                self.verify()

    def test_raw_host_files_are_rejected_in_public_distribution(self):
        write(self.release / "acceptance.json", self.record)
        with self.assertRaisesRegex(ValidationFailure, "未知顶层"):
            self.verify()

    def test_local_origin_remains_bound_through_consumer_verification(self):
        self.index.pop("ci_identity")
        self.index.update(validation_origin=release_fixtures.LOCAL_ORIGIN, assurance="local_artifacts_unattested")
        path = self.release / "setup/wheel-verification.json"
        receipt = json.loads(path.read_text())
        receipt.pop("ci_identity")
        receipt["validation_origin"] = release_fixtures.LOCAL_ORIGIN
        write(path, receipt)
        self.index["setup"]["verification"]["sha256"] = digest(path.read_bytes())
        self.write_index()
        index, _ = self.verify()
        self.assertEqual("local_artifacts_unattested", index["assurance"])
        self.summary["targets"][0].pop("app")
        write(self.release / "acceptance-summary.json", self.summary)
        with self.assertRaises(ValidationFailure):
            self.verify()

    def test_version_source_and_tag_are_bound_before_consumer_selection(self):
        for change in ({"version": "2.3.0.0-rc.2"}, {"source_commit": "b" * 40}, {"tag": TAG + "-other"}):
            with self.subTest(change=change), self.assertRaises(ValidationFailure):
                self.verify(**change)

    def test_malformed_index_shapes_fail_closed_as_validation_errors(self):
        original = copy.deepcopy(self.index)
        for field, value in (("targets", [[], "macos-x64", "windows-x64"]), ("ci_identity", []), ("packages", [{"agent": [], "target": "macos-arm64"}] * 3)):
            self.index = copy.deepcopy(original)
            self.index[field] = value
            write(self.release / "release-index.json", self.index)
            with self.subTest(field=field), self.assertRaises(ValidationFailure):
                self.verify()

    def test_other_platform_market_archive_and_setup_tamper_are_rejected(self):
        paths = ("marketplaces/codex/windows-x64/plugins/engineering-assistant/hooks/hooks.json",
                 "archives/windows-x64/codex.zip", "setup/fixture.whl", "setup/wheel-verification.json")
        for name in paths:
            path = self.release / name
            original = path.read_bytes()
            path.write_bytes(b"tampered")
            with self.subTest(name=name), self.assertRaises(ValidationFailure):
                self.verify()
            path.write_bytes(original)

    def test_incomplete_or_duplicate_targets_never_select_a_package(self):
        original = copy.deepcopy(self.index)
        for values in (("macos-arm64", "macos-x64"), ("macos-arm64", "macos-arm64", "windows-x64")):
            self.index = copy.deepcopy(original)
            self.index["targets"] = list(values)
            write(self.release / "release-index.json", self.index)
            with self.subTest(values=values), self.assertRaises(ValidationFailure):
                self.verify()

    def test_portable_archive_rejects_links_reserved_names_and_unicode_aliases(self):
        for names in (("../escape",), (".GIT/config",), ("CON.txt",), ("folder./x",), ("a\\b",), ("\u00e9.txt", "e\u0301.txt")):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                for name in names:
                    member = tarfile.TarInfo(name)
                    member.size = 1
                    archive.addfile(member, io.BytesIO(b"x"))
            destination = self.root / ("extract-" + str(hash(names)))
            destination.mkdir()
            with self.subTest(names=names), closing(ArtifactIO(destination, ".")) as storage, self.assertRaises(ValidationFailure):
                distribution._extract_git_archive(stream.getvalue(), storage)
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            member = tarfile.TarInfo("link")
            member.type = tarfile.SYMTYPE
            member.linkname = str(self.root)
            archive.addfile(member)
        destination = self.root / "link-extract"
        destination.mkdir()
        with closing(ArtifactIO(destination, ".")) as storage, self.assertRaises(ValidationFailure):
            distribution._extract_git_archive(stream.getvalue(), storage)

    def test_archive_preserves_executable_permission_without_world_access(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            member = tarfile.TarInfo("ea")
            member.size, member.mode = 1, 0o755
            archive.addfile(member, io.BytesIO(b"x"))
        destination = self.root / "mode-extract"
        destination.mkdir()
        with closing(ArtifactIO(destination, ".")) as storage:
            distribution._extract_git_archive(stream.getvalue(), storage)
        if os.name != "nt":
            self.assertEqual(0o700, (destination / "ea").stat().st_mode & 0o777)

    def test_archive_enforces_byte_and_entry_budgets_and_rejects_malformed_tar(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            for name in ("one", "two"):
                member = tarfile.TarInfo(name)
                member.size = 2
                archive.addfile(member, io.BytesIO(b"xx"))
        for setting in ("MAX_FILE_BYTES", "MAX_TREE_BYTES", "MAX_ENTRIES"):
            destination = self.root / setting
            destination.mkdir()
            with self.subTest(setting=setting), closing(ArtifactIO(destination, ".")) as storage, mock.patch.object(
                distribution, setting, 1), self.assertRaises(ValidationFailure):
                distribution._extract_git_archive(stream.getvalue(), storage)
        destination = self.root / "bad-tar"
        destination.mkdir()
        with closing(ArtifactIO(destination, ".")) as storage, self.assertRaises(ValidationFailure):
            distribution._extract_git_archive(b"not a tar", storage)

    def test_real_git_fetch_is_cached_offline_and_cache_is_reverified(self):
        repository = self.git_release()
        data = self.root / "data"
        first = self.acquire(data, repository)
        with mock.patch.object(distribution, "_fetch_ref", side_effect=AssertionError("offline")):
            second = self.acquire(data, repository)
        self.assertEqual(first["source"], second["source"])
        cache = first["source"].parents[2]
        (cache / "archives/windows-x64/codex.zip").write_bytes(b"tampered")
        with mock.patch.object(distribution, "_fetch_ref", side_effect=AssertionError("offline")), self.assertRaises(ValidationFailure):
            self.acquire(data, repository)

    def test_concurrent_fetch_publishes_one_complete_tree(self):
        from engineering_assistant.installation import _read_control
        repository = self.git_release()
        spec = {"repository_url": str(repository), "release_tag_prefix": "internal/codex/", "marketplace": "engineering-assistant"}
        data = self.root / "并发 data"
        with mock.patch.object(distribution, "internal_spec", return_value=spec), mock.patch.object(
            distribution, "installer_source_commit", return_value=SOURCE), mock.patch(
            "engineering_assistant.installation._read_control", side_effect=lambda path:
                {"version": VERSION} if Path(path).name == "public.json" else _read_control(path)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: distribution.acquire_internal_release(data, "macos-arm64"), range(2)))
        self.assertEqual(results[0]["source"], results[1]["source"])
        self.assertEqual(1, len(list((data / "distributions").iterdir())))

    def test_failed_final_verification_cleans_only_its_staging(self):
        repository = self.git_release()
        actual = distribution.verify_release
        count = 0
        def fail_second(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise ValidationFailure("synthetic final validation failure")
            return actual(*args, **kwargs)
        data = self.root / "failed-data"
        with mock.patch.object(distribution, "verify_release", side_effect=fail_second), self.assertRaisesRegex(ValidationFailure, "synthetic final"):
            self.acquire(data, repository)
        self.assertEqual([], list((data / "distributions").iterdir()))

    def test_replaced_final_staging_is_not_deleted_by_failure_cleanup(self):
        repository = self.git_release()
        actual = ArtifactIO.copy_contents_to
        replaced = []
        def replace_after_copy(source, destination, **kwargs):
            actual(source, destination, **kwargs)
            if destination.artifact_root.name.startswith(".verified-"):
                path = destination.artifact_root
                path.rename(path.with_name("detached-final"))
                path.mkdir()
                marker = path / "foreign-marker"
                marker.write_bytes(b"must survive")
                replaced.append(marker)
                raise ValidationFailure("synthetic staging replacement")
        data = self.root / "replace-data"
        with mock.patch.object(ArtifactIO, "copy_contents_to", new=replace_after_copy), self.assertRaisesRegex(ValidationFailure, "replacement"):
            self.acquire(data, repository)
        self.assertEqual(b"must survive", replaced[0].read_bytes())
        self.assertFalse(any(len(path.name) == 64 for path in (data / "distributions").iterdir()))

    def test_git_transport_rejects_replaced_working_directory_before_next_command(self):
        storage_root = self.root / "replaced-transport"
        storage_root.mkdir()
        calls = []
        def replace(command, **kwargs):
            calls.append(command)
            storage_root.rename(self.root / "detached-transport")
            storage_root.mkdir()
            (storage_root / "foreign-marker").write_bytes(b"must survive")
            return ""
        with closing(ArtifactIO(storage_root, ".")) as storage, mock.patch(
            "engineering_assistant.installation._command", side_effect=replace), self.assertRaises(ValidationFailure):
            distribution._fetch_ref(URL, TAG, storage_root, storage)
        self.assertEqual(1, len(calls))
        self.assertEqual(b"must survive", (storage_root / "foreign-marker").read_bytes())

    def test_git_fetch_ignores_inherited_repository_and_object_routing(self):
        repository = self.git_release()
        poisoned = {name: str(self.root / "must-not-exist") for name in (
            "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_SHALLOW_FILE")}
        with mock.patch.dict(os.environ, poisoned):
            result = self.acquire(self.root / "clean-data", repository)
        self.assertTrue(result["source"].is_dir())
        self.assertFalse((self.root / "must-not-exist").exists())

    def test_unsupported_target_rejects_before_creating_runtime_directories(self):
        data = self.root / "unsupported-data"
        with mock.patch.object(distribution, "internal_spec", side_effect=AssertionError("not reached")), self.assertRaises(ValidationFailure):
            distribution.acquire_internal_release(data, "linux-x64")
        self.assertFalse(data.exists())

    def test_git_error_does_not_echo_transport_credentials(self):
        storage_root = self.root / "transport"
        storage_root.mkdir()
        with closing(ArtifactIO(storage_root, ".")) as storage, mock.patch(
            "engineering_assistant.installation._command", side_effect=RuntimeError("token=private credential")):
            with self.assertRaises(ValidationFailure) as raised:
                distribution._fetch_ref(URL, TAG, storage_root, storage)
        self.assertNotIn("private credential", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
