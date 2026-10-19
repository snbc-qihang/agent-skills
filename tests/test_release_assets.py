"""Synthetic CI records test assembly decisions, never four-OS qualification."""
from __future__ import annotations

import hashlib
import base64
import csv
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.installer.installation import AGENTS, PYTHON_VERSION, TARGETS, python_download_metadata, runtime_lock
from engineering_assistant.tools.release_assets import REQUIRED_PROVIDER_CHECKS, assemble_release, required_native_tests
from engineering_assistant.runtime.validation import ValidationFailure

VERSION = "2.3.0.0-rc.1"
SOURCE_COMMIT = "a" * 40
CI_IDENTITY = {"repository": "snbc-qihang/agent-skills", "run_id": "123", "run_attempt": 1}
LOCAL_ORIGIN = {"kind": "local", "repository": "snbc-qihang/agent-skills",
                "validation_id": "e05ad626-4354-477a-9222-a02562f0ead2", "assurance": "local_unattested"}
INTERNAL_TARGETS = ("macos-arm64", "windows-x64")


def sha(payload):
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def fake_verify(package):
    """Verify synthetic payload integrity; no native OS or launcher is emulated."""
    package = Path(package)
    manifest = json.loads((package / "package-manifest.json").read_text())
    actual = {path.relative_to(package).as_posix(): sha(path.read_bytes())
              for path in package.rglob("*") if path.is_file() and path.name != "package-manifest.json"}
    if actual != manifest["payload_files"]:
        raise ValidationFailure("synthetic payload differs")
    return manifest


class ReleaseAssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.artifacts = {}
        for target in TARGETS:
            root = self.root / target
            root.mkdir()
            self.artifacts[target] = root
            results = []
            for agent in AGENTS:
                package = root / agent
                package.mkdir()
                launcher = package / "engineering-assistant/bin" / ("ea.exe" if target == "windows-x64" else "ea")
                launcher.parent.mkdir(parents=True)
                launcher.write_bytes(f"synthetic target {target} agent {agent}".encode())
                lock, _ = runtime_lock(ROOT, agent, target, VERSION)
                write(package / "engineering-assistant/runtime-lock.json", lock)
                (package / "engineering-assistant/runtime-python-downloads.json").write_bytes(python_download_metadata(lock))
                files = {path.relative_to(package).as_posix(): sha(path.read_bytes())
                         for path in package.rglob("*") if path.is_file()}
                digest = sha("\n".join(f"{name}:{value}" for name, value in sorted(files.items())).encode())
                write(package / "package-manifest.json", {"canonical_version": VERSION, "target": target,
                    "platform": agent, "payload_digest": digest, "payload_files": files})
                results.append({"agent": agent, "canonical_version": VERSION, "target": target,
                    "payload_digest": digest, "python_version": PYTHON_VERSION, "persistent_run": "passed", "feedback_hook": "passed",
                    "python_build": lock["python_artifact"]["build"], "python_artifact_digest": lock["python_artifact_digest"],
                    "native_marketplace_session": "not_executed", "hook_trust": "requires_native_host_review",
                    "checks": {"mcp": "passed", "tools_call": "passed", "hook": "passed",
                        "windows_hook_bridge": "passed" if target == "windows-x64" and agent == "codex" else "not_applicable",
                        "hermes_bridge": "passed" if agent == "hermes" else "not_applicable",
                        "provider": {"supported": True, "qualified": True,
                            "checks": {name: True for name in REQUIRED_PROVIDER_CHECKS},
                            "baselines": {"network_ipv4": True, "network_ipv6": True}}}})
            write(root / "host.json", {"target": target, "python": PYTHON_VERSION,
                "agent_host_qualification": "not_run", "windows11_qualification": "not_run" if target == "windows-x64" else "not_applicable"})
            write(root / "native-tests.json", {"target": target, "test_count": 100,
                "native_tests": sorted(required_native_tests(target)), "required_native_skips": 0,
                "provider_capability": {"supported": True}, "agent_host_qualification": "not_run"})
            write(root / "runtime-qualification.json", {"schema_version": "1", "status": "runtime_qualified",
                "target": target, "results": results,
                "windows_11_qualification": "not_executed" if target == "windows-x64" else "not_applicable"})
            for name in ("host.json", "native-tests.json", "runtime-qualification.json"):
                value = json.loads((root / name).read_text())
                value.update(source_commit=SOURCE_COMMIT, ci_identity=CI_IDENTITY)
                write(root / name, value)
            write(root / "official-validation.json", {"status": "passed", "quick_validate": "passed",
                "codex_plugin_validate": "passed", "skill_count": 11, "source_commit": SOURCE_COMMIT,
                "ci_identity": CI_IDENTITY, "codex_payload_digest": results[0]["payload_digest"]})
        self.wheel = self.artifacts["linux-x64"] / "setup/engineering_assistant_kernel-2.3.0rc1-py3-none-any.whl"
        self.make_wheel()
        patch = mock.patch("engineering_assistant.tools.release_assets.verify_package", side_effect=fake_verify)
        self.verify = patch.start()
        self.addCleanup(patch.stop)
        contract_patch = mock.patch("engineering_assistant.installer.release_contract.verify_package", side_effect=fake_verify)
        contract_patch.start()
        self.addCleanup(contract_patch.stop)

    def tearDown(self):
        self.temporary.cleanup()

    def test_consumer_wheel_rejects_author_tools_and_evals(self):
        for number, name in enumerate(("engineering_assistant/tools/unneeded.py", "engineering_assistant/_assets/evals/unneeded.json")):
            with self.subTest(name=name):
                self.make_wheel(extra_members={name: b"unneeded author payload"})
                with self.assertRaisesRegex(ValidationFailure, "作者工具|评测"):
                    self.assemble(output=self.root / ("extra-" + str(number)))

    def make_wheel(self, *, version=VERSION, metadata_version="2.3.0rc1", universal=True,
                   include_payload=True, omit=frozenset(), record_change=None, extra_members=None):
        prefix = "engineering_assistant_kernel-" + metadata_version + ".dist-info/"
        files = {
            prefix + "METADATA": ("Metadata-Version: 2.1\nName: engineering-assistant-kernel\nVersion: " + metadata_version + "\n").encode(),
            prefix + "WHEEL": ("Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: " + ("py3-none-any" if universal else "cp313-cp313-win_amd64") + "\n").encode(),
            prefix + "entry_points.txt": b"[console_scripts]\nea-setup = engineering_assistant.installer.setup_cli:main\n",
        }
        if include_payload:
            for path in (ROOT / "src/engineering_assistant").rglob("*.py"):
                if "tools" in path.relative_to(ROOT / "src/engineering_assistant").parts:
                    continue
                files["engineering_assistant/" + path.relative_to(ROOT / "src/engineering_assistant").as_posix()] = path.read_bytes()
            for directory in ("catalog", "skills", "packs", "schemas", "config"):
                for path in (ROOT / directory).rglob("*"):
                    if path.is_file() and not any(part.startswith(".") for part in path.relative_to(ROOT).parts):
                        files["engineering_assistant/_assets/" + path.relative_to(ROOT).as_posix()] = path.read_bytes()
            for name in ("VERSIONING.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
                files["engineering_assistant/_assets/" + name] = (ROOT / name).read_bytes()
        files["engineering_assistant/_assets/catalog/skills/public.json"] = json.dumps({"version": version}).encode()
        files.update(extra_members or {})
        files = {name: payload for name, payload in files.items() if name not in omit}
        rows = [[name, "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode(), str(len(payload))]
                for name, payload in sorted(files.items())]
        rows.append([prefix + "RECORD", "", ""])
        if record_change:
            record_change(rows)
        stream = io.StringIO(newline="")
        csv.writer(stream, lineterminator="\n").writerows(rows)
        if prefix + "RECORD" not in omit:
            files[prefix + "RECORD"] = stream.getvalue().encode()
        self.wheel.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.wheel, "w") as archive:
            for name, payload in sorted(files.items()):
                archive.writestr(name, payload)
        write(self.wheel.parent / "wheel-verification.json", {"schema_version": "1", "status": "passed",
            "python_version": PYTHON_VERSION, "canonical_version": version,
            "wheel_filename": self.wheel.name, "wheel_digest": sha(self.wheel.read_bytes()), "wheel_version": metadata_version,
            "checks": {name: "passed" for name in ("help", "doctor", "source_validation", "runtime_protocol")},
            "source_commit": SOURCE_COMMIT, "ci_identity": CI_IDENTITY})

    def assemble(self, *, output=None, artifacts=None, wheel=None, agents=AGENTS, targets=TARGETS):
        return assemble_release(self.artifacts if artifacts is None else artifacts, self.wheel if wheel is None else wheel,
                                self.root / "candidate" if output is None else output, repository_root=ROOT,
                                agents=agents, targets=targets, source_commit=SOURCE_COMMIT, ci_identity=CI_IDENTITY)

    def mutate(self, target, name, change):
        path = self.artifacts[target] / name
        value = json.loads(path.read_text())
        change(value)
        write(path, value)

    def test_complete_synthetic_matrix_produces_candidate_and_separate_native_marketplace_trees(self):
        index = self.assemble()
        output = self.root / "candidate"
        self.assertEqual("candidate", index["status"])
        self.assertEqual("ci_artifacts_unattested", index["assurance"])
        self.assertEqual("not_satisfied", index["support_qualification"]["status"])
        self.assertIn("windows11_native_host", index["support_qualification"]["missing"])
        self.assertEqual(9, len(index["packages"]))
        self.assertEqual(self.wheel.read_bytes(), (output / index["setup"]["path"]).read_bytes())
        self.assertEqual(sha(self.wheel.read_bytes()), index["setup"]["sha256"])
        verification = index["setup"]["verification"]
        self.assertEqual(sha((self.wheel.parent / "wheel-verification.json").read_bytes()), verification["sha256"])
        self.assertEqual("passed", verification["status"])
        self.assertEqual((self.wheel.parent / "wheel-verification.json").read_bytes(), (output / verification["path"]).read_bytes())
        self.assertEqual(index, json.loads((output / "release-index.json").read_text()))
        self.assertEqual(18, self.verify.call_count)
        for entry in index["packages"]:
            archive_path = output / entry["archive"]["path"]
            self.assertEqual(sha(archive_path.read_bytes()), entry["archive"]["sha256"])
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("package-manifest.json", archive.namelist())
                self.assertNotIn("plugins/engineering-assistant/package-manifest.json", archive.namelist())
                executable = "engineering-assistant/bin/" + ("ea.exe" if entry["target"] == "windows-x64" else "ea")
                self.assertTrue((archive.getinfo(executable).external_attr >> 16) & 0o100)
            tree = output / entry["marketplace"]["path"]
            if entry["agent"] == "hermes":
                self.assertTrue((tree / "package-manifest.json").is_file())
                package_tree = tree
            else:
                prefix = ".agents/plugins" if entry["agent"] == "codex" else ".claude-plugin"
                manifest = json.loads((tree / prefix / "marketplace.json").read_text())
                source = manifest["plugins"][0]["source"]
                self.assertEqual("./plugins/engineering-assistant", source["path"] if isinstance(source, dict) else source)
                self.assertTrue((tree / "plugins/engineering-assistant/package-manifest.json").is_file())
                package_tree = tree / "plugins/engineering-assistant"
            if os.name != "nt":
                self.assertTrue((package_tree / executable).stat().st_mode & 0o100)

    def test_codex_two_target_release_does_not_require_linux_or_other_agents(self):
        for target in INTERNAL_TARGETS:
            self.mutate(target, "runtime-qualification.json", lambda report: report.update(
                results=[item for item in report["results"] if item["agent"] == "codex"]))
        independent = self.root / "setup"
        independent.mkdir()
        wheel = independent / self.wheel.name
        wheel.write_bytes(self.wheel.read_bytes())
        (independent / "wheel-verification.json").write_bytes((self.wheel.parent / "wheel-verification.json").read_bytes())
        index = self.assemble(artifacts={target: self.artifacts[target] for target in INTERNAL_TARGETS},
                              wheel=wheel, agents=("codex",), targets=INTERNAL_TARGETS)
        self.assertEqual("2", index["schema_version"])
        self.assertEqual(["codex"], index["agents"])
        self.assertEqual(list(INTERNAL_TARGETS), index["targets"])
        self.assertEqual(2, len(index["packages"]))
        self.assertEqual(SOURCE_COMMIT, index["source_commit"])
        self.assertEqual(CI_IDENTITY, index["ci_identity"])
        self.assertEqual("internal/codex/" + VERSION, index["release_tag"])

    def formal_codex_inputs(self):
        version = "1.0.0.1"
        for target in INTERNAL_TARGETS:
            package = self.artifacts[target] / "codex"
            lock, _ = runtime_lock(ROOT, "codex", target, version)
            write(package / "engineering-assistant/runtime-lock.json", lock)
            (package / "engineering-assistant/runtime-python-downloads.json").write_bytes(python_download_metadata(lock))
            files = {path.relative_to(package).as_posix(): sha(path.read_bytes())
                     for path in package.rglob("*") if path.is_file() and path.name != "package-manifest.json"}
            digest = sha("\n".join(f"{name}:{value}" for name, value in sorted(files.items())).encode())
            write(package / "package-manifest.json", {"canonical_version": version, "target": target,
                "platform": "codex", "payload_digest": digest, "payload_files": files})
            def qualification(report):
                report["results"] = [item for item in report["results"] if item["agent"] == "codex"]
                report["results"][0].update(canonical_version=version, payload_digest=digest)
            self.mutate(target, "runtime-qualification.json", qualification)
            self.mutate(target, "official-validation.json", lambda report: report.update(codex_payload_digest=digest))
        self.make_wheel(version=version, metadata_version=version)
        return {target: self.artifacts[target] for target in INTERNAL_TARGETS}

    def test_formal_internal_codex_version_assembles_unattested_three_target_candidate(self):
        artifacts = self.formal_codex_inputs()
        index = self.assemble(artifacts=artifacts, agents=("codex",), targets=INTERNAL_TARGETS)
        self.assertEqual("1.0.0.1", index["canonical_version"])
        self.assertEqual("1.0.0.1", index["setup"]["version"])
        self.assertEqual("candidate", index["status"])
        self.assertEqual("ci_artifacts_unattested", index["assurance"])
        self.assertEqual("not_satisfied", index["support_qualification"]["status"])

    def local_inputs(self):
        artifacts = self.formal_codex_inputs()
        paths = [root / name for root in artifacts.values() for name in (
            "host.json", "native-tests.json", "runtime-qualification.json", "official-validation.json")]
        paths.append(self.wheel.parent / "wheel-verification.json")
        for path in paths:
            value = json.loads(path.read_text())
            value.pop("ci_identity")
            value["validation_origin"] = dict(LOCAL_ORIGIN)
            write(path, value)
        return artifacts

    def test_local_validation_assembles_without_a_ci_run_but_keeps_host_acceptance_pending(self):
        from engineering_assistant.runtime.artifact_io import ArtifactIO
        from engineering_assistant.tools.internal_promotion import _verify_candidate
        from engineering_assistant.tools.release_assets import validate_acceptance
        artifacts = self.local_inputs()
        output = self.root / "local-candidate"
        index = assemble_release(artifacts, self.wheel, output, agents=("codex",), targets=INTERNAL_TARGETS,
                                 source_commit=SOURCE_COMMIT, validation_origin=LOCAL_ORIGIN)
        self.assertEqual(LOCAL_ORIGIN, index["validation_origin"])
        self.assertNotIn("ci_identity", index)
        self.assertEqual("local_artifacts_unattested", index["assurance"])
        self.assertEqual("not_satisfied", index["support_qualification"]["status"])
        storage = ArtifactIO(output, ".")
        try:
            verified, raw = _verify_candidate(storage)
            self.assertEqual(index, verified)
            with self.assertRaises(ValidationFailure):
                validate_acceptance(index, raw, {})
            index["assurance"] = "ci_artifacts_unattested"
            with self.assertRaises(ValidationFailure):
                validate_acceptance(index, json.dumps(index).encode(), {})
        finally:
            storage.close()

    def test_local_validation_rejects_mixed_batches_and_ci_fields_before_output(self):
        artifacts = self.local_inputs()
        path = artifacts["macos-arm64"] / "native-tests.json"
        original = json.loads(path.read_text())
        for change in ({"ci_identity": CI_IDENTITY}, {"validation_origin": {
                **LOCAL_ORIGIN, "validation_id": "d1b8c2ef-c242-4a90-b903-a27acc66f0be"}}):
            write(path, {**original, **change})
            with self.assertRaisesRegex(ValidationFailure, "来源"):
                assemble_release(artifacts, self.wheel, self.root / "candidate", agents=("codex",),
                                 targets=INTERNAL_TARGETS, source_commit=SOURCE_COMMIT, validation_origin=LOCAL_ORIGIN)
            self.assertFalse((self.root / "candidate").exists())

    def test_validation_origin_requires_one_explicit_unattested_source(self):
        from engineering_assistant.tools.release_assets import release_provenance
        for change in ({"validation_id": "123"}, {"repository": "other/repo"},
                       {"assurance": "verified"}, {"kind": "github"}):
            with self.assertRaises(ValidationFailure):
                release_provenance(SOURCE_COMMIT, validation_origin={**LOCAL_ORIGIN, **change})
        with self.assertRaises(ValidationFailure):
            release_provenance(SOURCE_COMMIT, CI_IDENTITY, validation_origin=LOCAL_ORIGIN)

    def test_formal_internal_candidate_cannot_silently_drop_a_supported_target(self):
        artifacts = self.formal_codex_inputs()
        targets = INTERNAL_TARGETS[:-1]
        with self.assertRaises(ValidationFailure):
            self.assemble(artifacts={target: artifacts[target] for target in targets}, agents=("codex",), targets=targets)

    def test_formal_four_part_wheel_version_is_verified_without_a_prerelease(self):
        from engineering_assistant.tools.release_assets import _wheel_version
        self.make_wheel(version="1.0.0.1", metadata_version="1.0.0.1")
        self.assertEqual("1.0.0.1", _wheel_version(self.wheel.read_bytes(), "1.0.0.1"))

    def test_mixed_source_or_ci_identity_is_rejected_before_output(self):
        for field, value in (("source_commit", "b" * 40),
                             ("ci_identity", {**CI_IDENTITY, "run_id": "124"})):
            original = (self.artifacts["macos-arm64"] / "runtime-qualification.json").read_bytes()
            self.mutate("macos-arm64", "runtime-qualification.json", lambda report: report.update({field: value}))
            with self.assertRaisesRegex(ValidationFailure, "来源"):
                self.assemble()
            (self.artifacts["macos-arm64"] / "runtime-qualification.json").write_bytes(original)
        self.assertFalse((self.root / "candidate").exists())

    def test_agent_scope_must_match_records_exactly(self):
        with self.assertRaisesRegex(ValidationFailure, "Agent"):
            self.assemble(agents=("codex",))
        with self.assertRaises(ValidationFailure):
            self.assemble(agents=())
        with self.assertRaises(ValidationFailure):
            self.assemble(agents=("codex", "codex"))

    def test_official_validation_receipt_is_required_and_bound_to_codex(self):
        self.mutate("macos-arm64", "official-validation.json", lambda report: report.update(
            codex_payload_digest="sha256:" + "0" * 64))
        with self.assertRaisesRegex(ValidationFailure, "官方"):
            self.assemble()

    def test_same_inputs_generate_identical_archives_and_index(self):
        first = self.assemble(output=self.root / "first")
        second = self.assemble(output=self.root / "second")
        self.assertEqual(first, second)

    def test_missing_target_is_rejected_before_output(self):
        inputs = dict(self.artifacts)
        inputs.pop("windows-x64")
        with self.assertRaisesRegex(ValidationFailure, "目标"):
            self.assemble(artifacts=inputs)
        self.assertFalse((self.root / "candidate").exists())

    def test_required_native_tests_cannot_be_omitted_or_skipped(self):
        for field, value in (("required_native_skips", 1), ("native_tests", []), ("test_count", 0)):
            with self.subTest(field=field):
                path = self.artifacts["windows-x64"] / "native-tests.json"
                previous = path.read_bytes()
                self.mutate("windows-x64", "native-tests.json", lambda report: report.update({field: value}))
                with self.assertRaisesRegex(ValidationFailure, "原生必需"):
                    self.assemble()
                path.write_bytes(previous)

    def test_windows_private_provider_environment_requires_native_execution(self):
        test_id = (
            "test_provider_runtime.ProviderRuntimeTests."
            "test_windows_lpac_keeps_temporary_and_profile_options_in_private_work"
        )
        self.mutate("windows-x64", "native-tests.json", lambda report: report.update(
            native_tests=[name for name in report["native_tests"] if name != test_id]
        ))
        with self.assertRaisesRegex(ValidationFailure, "原生必需"):
            self.assemble()

    def test_runtime_checks_and_provider_eleven_boundaries_cannot_be_soft_passed(self):
        path = self.artifacts["linux-x64"] / "runtime-qualification.json"
        original = path.read_bytes()
        mutations = [lambda result: result["checks"].update(mcp="not_run"),
            lambda result: result["checks"].update(windows_hook_bridge="requires_prepared_binding"),
            lambda result: result["checks"]["provider"]["checks"].pop("same_python_exec"),
            lambda result: result["checks"]["provider"]["checks"].update(network_ipv6=False),
            lambda result: result["checks"]["provider"]["baselines"].update(network_ipv4=False),
            lambda result: result.update(persistent_run="not_run"),
            lambda result: result.update(feedback_hook="not_run")]
        for mutation in mutations:
            self.mutate("linux-x64", "runtime-qualification.json", lambda report: mutation(report["results"][0]))
            with self.assertRaises(ValidationFailure):
                self.assemble()
            path.write_bytes(original)

    def test_target_version_and_payload_digest_must_match_records(self):
        path = self.artifacts["macos-arm64"] / "runtime-qualification.json"
        original = path.read_bytes()
        for field, value in (("target", "macos-x64"), ("canonical_version", "9.0.0.0-rc.1"), ("payload_digest", "sha256:" + "0" * 64)):
            self.mutate("macos-arm64", "runtime-qualification.json", lambda report: report["results"][0].update({field: value}))
            with self.assertRaises(ValidationFailure):
                self.assemble()
            path.write_bytes(original)

    def test_runtime_qualification_requires_fixed_python_artifact_fields(self):
        path = self.artifacts["linux-x64"] / "runtime-qualification.json"
        original = path.read_bytes()
        for field in ("python_build", "python_artifact_digest"):
            with self.subTest(field=field):
                self.mutate("linux-x64", "runtime-qualification.json", lambda report: report["results"][0].pop(field))
                with self.assertRaisesRegex(ValidationFailure, "Python.*构建"):
                    self.assemble()
                path.write_bytes(original)

    def test_runtime_qualification_cannot_substitute_same_version_different_build(self):
        path = self.artifacts["linux-x64"] / "runtime-qualification.json"
        original = path.read_bytes()
        for field, value in (("python_build", "20260602"), ("python_artifact_digest", "0" * 64)):
            with self.subTest(field=field):
                self.mutate("linux-x64", "runtime-qualification.json", lambda report: report["results"][0].update({field: value}))
                with self.assertRaisesRegex(ValidationFailure, "Python.*构建"):
                    self.assemble()
                path.write_bytes(original)

    def test_tampered_package_is_recomputed_not_trusted(self):
        package = self.artifacts["macos-arm64"] / "codex"
        (package / "engineering-assistant/bin/ea").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValidationFailure, "payload differs"):
            self.assemble()

    def test_stable_and_mixed_package_versions_are_rejected(self):
        for target in TARGETS:
            self.mutate(target, "runtime-qualification.json", lambda report: [result.update(canonical_version="2.3.0.0") for result in report["results"]])
            for agent in AGENTS:
                self.mutate(target, agent + "/package-manifest.json", lambda report: report.update(canonical_version="2.3.0.0"))
        with self.assertRaisesRegex(ValidationFailure, "稳定版"):
            self.assemble()
        self.mutate("linux-x64", "runtime-qualification.json", lambda report: [result.update(canonical_version=VERSION) for result in report["results"]])
        for agent in AGENTS:
            self.mutate("linux-x64", agent + "/package-manifest.json", lambda report: report.update(canonical_version=VERSION))
        with self.assertRaisesRegex(ValidationFailure, "混合版本"):
            self.assemble()

    def test_wheel_must_be_universal_and_have_matching_canonical_and_distribution_version(self):
        for kwargs in ({"version": "9.0.0.0-rc.1"}, {"metadata_version": "9.0.0rc1"}, {"universal": False}):
            self.make_wheel(**kwargs)
            with self.assertRaises(ValidationFailure):
                self.assemble()
            self.assertFalse((self.root / "candidate").exists())

    def test_metadata_only_wheel_and_missing_installation_modules_or_resources_are_rejected(self):
        from engineering_assistant.tools.release_assets import _wheel_version
        variants = [{"include_payload": False}] + [{"omit": {name}} for name in (
            "engineering_assistant/installer/setup_cli.py", "engineering_assistant/installer/installation.py",
            "engineering_assistant/runtime/artifact_io.py", "engineering_assistant/platforms/adapters/codex.py",
            "engineering_assistant/_assets/config/runtime.json", "engineering_assistant/_assets/schemas/route-intent.schema.json")]
        for kwargs in variants:
            with self.subTest(kwargs=kwargs):
                self.make_wheel(**kwargs)
                with self.assertRaisesRegex(ValidationFailure, "wheel.*缺少"):
                    _wheel_version(self.wheel.read_bytes(), VERSION)

    def test_wheel_record_must_cover_all_members_with_valid_hashes_and_sizes(self):
        from engineering_assistant.tools.release_assets import _wheel_version
        def missing(rows):
            rows.pop(0)
        def duplicate(rows):
            rows.append(rows[0][:])
        def wrong_hash(rows):
            rows[0][1] = "sha256=" + "0" * 43
        def wrong_size(rows):
            rows[0][2] = "0"
        def forged_self_hash(rows):
            rows[-1][1] = "sha256=" + "0" * 43
        for mutation in (missing, duplicate, wrong_hash, wrong_size, forged_self_hash):
            with self.subTest(mutation=mutation.__name__):
                self.make_wheel(record_change=mutation)
                with self.assertRaisesRegex(ValidationFailure, "RECORD"):
                    _wheel_version(self.wheel.read_bytes(), VERSION)

    def test_wheel_record_file_is_required(self):
        from engineering_assistant.tools.release_assets import _wheel_version
        self.make_wheel(omit={"engineering_assistant_kernel-2.3.0rc1.dist-info/RECORD"})
        with self.assertRaisesRegex(ValidationFailure, "RECORD"):
            _wheel_version(self.wheel.read_bytes(), VERSION)

    def test_linux_wheel_smoke_receipt_is_required_and_bound_to_exact_wheel(self):
        receipt = self.wheel.parent / "wheel-verification.json"
        original = receipt.read_bytes()
        receipt.unlink()
        with self.assertRaisesRegex(ValidationFailure, "wheel.*验证"):
            self.assemble(output=self.root / "missing-smoke")
        receipt.write_bytes(original)
        variants = [lambda report: report.update(wheel_digest="sha256:" + "0" * 64),
                    lambda report: report.update(wheel_filename="unrelated.whl"),
                    lambda report: report.update(wheel_version="9.0.0rc1"),
                    lambda report: report.update(canonical_version="9.0.0.0-rc.1"),
                    lambda report: report.update(python_version="3.14.0"),
                    lambda report: report["checks"].update(doctor="not_run"),
                    lambda report: report["checks"].pop("source_validation")]
        for index, mutation in enumerate(variants):
            with self.subTest(index=index):
                report = json.loads(original)
                mutation(report)
                write(receipt, report)
                with self.assertRaisesRegex(ValidationFailure, "wheel.*验证"):
                    self.assemble(output=self.root / ("invalid-smoke-" + str(index)))
                self.assertFalse((self.root / ("invalid-smoke-" + str(index))).exists())

    def test_explicit_wheel_must_match_the_same_linux_ci_artifact_as_its_receipt(self):
        original = self.wheel.read_bytes()
        self.make_wheel(extra_members={"engineering_assistant/_assets/additional-fixture.txt": b"different wheel"})
        external = self.root / "explicit" / self.wheel.name
        external.parent.mkdir()
        external.write_bytes(self.wheel.read_bytes())
        (external.parent / "wheel-verification.json").write_bytes((self.wheel.parent / "wheel-verification.json").read_bytes())
        # Replace the actual wheel after its colocated receipt was written.
        external.write_bytes(original)
        with self.assertRaisesRegex(ValidationFailure, "wheel.*验证"):
            self.assemble(wheel=external)
        self.assertFalse((self.root / "candidate").exists())

    def test_symlink_input_and_package_payload_are_rejected(self):
        linked = self.root / "linked-input"
        linked.symlink_to(self.artifacts["macos-arm64"], target_is_directory=True)
        inputs = {**self.artifacts, "macos-arm64": linked}
        with self.assertRaises((OSError, ValidationFailure)):
            self.assemble(artifacts=inputs)
        payload = self.artifacts["macos-arm64"] / "codex" / "linked"
        payload.symlink_to(self.wheel)
        with self.assertRaises((OSError, ValidationFailure)):
            self.assemble()

    def test_wheel_cannot_hide_traversal_reparse_or_windows_device_entries(self):
        for name, mode in (("../outside", 0o100644), ("C:stream", 0o100644), ("payload/CON", 0o100644),
                           ("payload/file. ", 0o100644), ("payload/link", 0o120777)):
            self.make_wheel()
            with zipfile.ZipFile(self.wheel, "a") as archive:
                entry = zipfile.ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = mode << 16
                archive.writestr(entry, "unsafe")
            with self.assertRaises(ValidationFailure):
                self.assemble()
            self.assertFalse((self.root / "candidate").exists())

    def test_existing_output_and_author_source_output_are_never_overwritten(self):
        output = self.root / "candidate"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            self.assemble()
        self.assertEqual("keep", marker.read_text())
        with self.assertRaisesRegex(ValidationFailure, "仓库外"):
            self.assemble(output=ROOT / "candidate")


if __name__ == "__main__":
    unittest.main()
