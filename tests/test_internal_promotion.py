"""Synthetic acceptance tests enforce promotion rules, never claim host qualification."""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engineering_assistant.artifact_io import ArtifactIO
from engineering_assistant.release_assets import REQUIRED_PROVIDER_CHECKS, validate_acceptance
from engineering_assistant.validation import ValidationFailure
import test_release_assets as fixtures
from test_release_assets import INTERNAL_TARGETS, SOURCE_COMMIT, VERSION, sha, write

ORIGINAL_SESSION_CHECKS = frozenset({
    "install", "skills", "mcp", "hook", "persistent_run", "restart", "update", "recovery", "uninstall",
})
LIFECYCLE_SESSION_CHECKS = ORIGINAL_SESSION_CHECKS | {
    "repeat_install", "repair", "uv_upgrade", "uv_removal", "cache_cleanup", "installer_alias_advance",
    "network_failure", "authentication_failure", "digest_failure", "interrupted_update",
    "preparation_failure_preserves_previous", "unicode_space_paths",
}


class InternalPromotionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReleaseAssetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        for target in INTERNAL_TARGETS:
            self.fixture.mutate(target, "runtime-qualification.json", lambda report: report.update(
                results=[item for item in report["results"] if item["agent"] == "codex"]))
        self.index = self.fixture.assemble(agents=("codex",), targets=INTERNAL_TARGETS,
            artifacts={target: self.fixture.artifacts[target] for target in INTERNAL_TARGETS})
        self.candidate = self.root / "candidate"
        self.raw = (self.candidate / "release-index.json").read_bytes()
        self.evidence_root = self.root / "acceptance"
        self.record = {"schema_version": "1", "status": "accepted", "canonical_version": VERSION,
            "source_commit": SOURCE_COMMIT, "candidate_index_digest": sha(self.raw),
            "reviewer_ref": "synthetic-test-reviewer", "reviewed_at": "2026-10-08T01:00:00Z", "targets": []}
        for entry in self.index["packages"]:
            target = entry["target"]
            item = {"target": target, "package_payload_digest": entry["package_payload_digest"],
                "os": {"name": "Windows" if target == "windows-x64" else "macOS", "version": "11" if target == "windows-x64" else "14.0"}}
            for role in ("app", "cli", "provider"):
                evidence = {"os": item["os"], "target": target, "source_commit": SOURCE_COMMIT, "canonical_version": VERSION,
                    "package_payload_digest": entry["package_payload_digest"]}
                if role == "provider":
                    evidence.update(evidence_kind="provider_qualification", qualified=True,
                        checks={name: True for name in REQUIRED_PROVIDER_CHECKS},
                        baselines={"network_ipv4": True, "network_ipv6": True})
                else:
                    evidence.update(evidence_kind="authenticated_codex_session", entrypoint=role,
                        authenticated=True, execution="native", checks={name: "passed" for name in LIFECYCLE_SESSION_CHECKS})
                path = "evidence/" + target + "-" + role + ".json"
                write(self.evidence_root / path, evidence)
                item[role] = {"path": path, "sha256": sha((self.evidence_root / path).read_bytes())}
            self.record["targets"].append(item)
        write(self.evidence_root / "acceptance.json", self.record)

    def validate(self, record=None):
        storage = ArtifactIO(self.evidence_root, ".")
        try:
            return validate_acceptance(self.index, self.raw, record or self.record, storage=storage)
        finally:
            storage.close()

    def promote(self, *, execute=False, expected_alias="absent", phase="prepare"):
        from engineering_assistant.internal_promotion import promote
        arguments = {"expected_alias": expected_alias, "execute": execute, "phase": phase}
        if phase == "activate":
            self.activation_fixture()
            arguments.update(activation=self.activation_root / "activation.json", release_notes=self.notes)
        return promote(self.candidate, self.evidence_root / "acceptance.json", **arguments)

    def activation_fixture(self):
        """Synthetic command/package receipts test binding only, never authenticated hosts."""
        if hasattr(self, "activation_root"):
            return
        from engineering_assistant.internal_promotion import fixed_install_command, REMOTE, SOURCE_TAG_PREFIX
        from engineering_assistant.version import CanonicalVersion, platform_version
        current = CanonicalVersion.parse(VERSION)
        following = CanonicalVersion(current.major, current.minor, current.patch, current.build + 1, current.prerelease).canonical()
        self.activation_root = self.root / "activation-input"
        shutil.copytree(self.evidence_root / "evidence", self.activation_root / "evidence")
        wrapper = {"schema_version": "1", "repository_url": REMOTE, "installer_ref": SOURCE_TAG_PREFIX + VERSION,
                   "transport": "private_https_git", "acceptance": copy.deepcopy(self.record), "build_updates": []}
        for entry in self.index["packages"]:
            target = entry["target"]
            packages = {}
            for version in (VERSION, following):
                package_name = "evidence/packages/" + target + "/" + version
                package = self.activation_root / package_name
                source = self.candidate / entry["marketplace"]["path"] / "plugins/engineering-assistant"
                shutil.copytree(source, package)
                manifest = json.loads((package / "package-manifest.json").read_bytes())
                if version == following:
                    launcher = package / "engineering-assistant/bin" / ("ea.exe" if target == "windows-x64" else "ea")
                    launcher.write_bytes(launcher.read_bytes() + b" synthetic BUILD update")
                    manifest["canonical_version"] = version
                    manifest["payload_files"] = {file.relative_to(package).as_posix(): sha(file.read_bytes())
                        for file in package.rglob("*") if file.is_file() and file.name != "package-manifest.json"}
                    manifest["payload_digest"] = sha("\n".join(name + ":" + digest
                        for name, digest in sorted(manifest["payload_files"].items())).encode())
                    write(package / "package-manifest.json", manifest)
                packages[version] = {"path": package_name, "manifest_sha256": sha((package / "package-manifest.json").read_bytes())}
            row = {"target": target}
            for operation in ("install", "before_update", "update"):
                version = following if operation == "update" else VERSION
                native_name = "evidence/" + target + "-" + operation + "-native.json"
                native = {"installed": [{"name": "engineering-assistant", "marketplaceName": "engineering-assistant",
                    "installed": True, "enabled": True, "version": platform_version(version, supports_four_part=False)}]}
                write(self.activation_root / native_name, native)
                command = fixed_install_command(VERSION) if operation == "install" else ["ea-setup", "update" if operation == "update" else "doctor", "--agent", "codex", "--json"]
                receipt = {"schema_version": "1", "evidence_kind": "ea_setup_command", "command": command,
                    "installer_origin": {"url": REMOTE, "vcs_info": {"vcs": "git", "requested_revision": SOURCE_TAG_PREFIX + VERSION, "commit_id": SOURCE_COMMIT}},
                    "exit_code": 0, "result": {"status": "ready", "runtime_ready": True, "native_activation": "enabled",
                        "agent": "codex", "target": target, "version": version, "source_commit": SOURCE_COMMIT, "marketplace": "engineering-assistant",
                        "package": "/synthetic-home/plugins/cache/engineering-assistant/engineering-assistant/" + platform_version(version, supports_four_part=False)},
                    "package": packages[version], "native_selection": {"path": native_name, "sha256": sha((self.activation_root / native_name).read_bytes())}}
                receipt_name = "evidence/" + target + "-" + operation + "-command.json"
                write(self.activation_root / receipt_name, receipt)
                row[operation] = {"path": receipt_name, "sha256": sha((self.activation_root / receipt_name).read_bytes())}
            wrapper["build_updates"].append(row)
        write(self.activation_root / "activation.json", wrapper)
        self.notes = self.root / "installation.md"
        self.notes.write_text("内部版本 " + VERSION + "\n\n```bash\n" + " ".join(fixed_install_command(VERSION)[:-1]) + "\n```\n", encoding="utf-8")

    def activation_mutate(self, operation, change):
        self.activation_fixture()
        path = self.activation_root / "activation.json"
        wrapper = json.loads(path.read_bytes())
        reference = wrapper["build_updates"][0][operation]
        receipt_path = self.activation_root / reference["path"]
        receipt = json.loads(receipt_path.read_bytes())
        change(receipt)
        write(receipt_path, receipt)
        reference["sha256"] = sha(receipt_path.read_bytes())
        write(path, wrapper)

    def remote(self, *, alias=None, tag_tree="d" * 40, failure=None):
        payload = "refs/tags/" + self.index["release_tag"]
        source = "refs/tags/internal/installer/" + VERSION
        refs = {payload: "e" * 40, source: SOURCE_COMMIT}
        if alias is not None:
            refs["refs/heads/internal/installer"] = alias
        calls, fetched, attempted = [], None, False
        def git(args, root, **kwargs):
            nonlocal fetched, attempted
            calls.append(args)
            if args[0] == "ls-remote":
                if attempted and failure == "unknown" and args[-1] == "refs/heads/internal/installer":
                    raise ValidationFailure("synthetic unavailable observation")
                return refs[args[-1]] + "\t" + args[-1] if args[-1] in refs else ""
            if args[0] == "fetch":
                fetched = args[-1]
            if args[0] == "show":
                return json.dumps({"version": VERSION})
            if args[0] == "rev-parse":
                if args[1] == "HEAD":
                    return "c" * 40
                if args[1] == "HEAD^{tree}":
                    return "d" * 40
                return tag_tree if args[1].endswith("{tree}") else refs.get(fetched, SOURCE_COMMIT)
            if args[0] == "push":
                value, reference = args[-1].split(":", 1)
                if reference == "refs/heads/internal/installer":
                    attempted = True
                    if failure in {"before", "unknown"}:
                        raise ValidationFailure("synthetic CAS failure")
                refs[reference] = value
                if reference == "refs/heads/internal/installer" and failure == "after":
                    raise ValidationFailure("synthetic transport failed after CAS")
            return ""
        return git, refs, calls

    def execute_activation(self, git):
        with mock.patch("engineering_assistant.internal_promotion._git", side_effect=git), mock.patch(
                "engineering_assistant.internal_promotion._private_repository"), mock.patch(
                "engineering_assistant.internal_promotion._ensure_release", return_value={"status": "published", "release_published": True,
                    "remote_modified": False}) as release:
            result = self.promote(execute=True, phase="activate")
        return result, release

    def test_dry_run_checks_real_files_without_any_git_mutation(self):
        with mock.patch("engineering_assistant.internal_promotion._git") as git:
            result = self.promote()
        self.assertEqual("ready_for_prepare", result["status"])
        self.assertFalse(result["remote_modified"])
        git.assert_not_called()

    def test_prepare_phase_is_the_default_and_never_promotes_the_alias(self):
        calls, refs = [], {}
        def git(args, root, **kwargs):
            calls.append(args)
            if args[0] == "ls-remote":
                return refs[args[-1]] + "\t" + args[-1] if args[-1] in refs else ""
            if args[0] == "show":
                return json.dumps({"version": VERSION})
            if args[0] == "rev-parse":
                return "c" * 40
            if args[0] == "push":
                value, reference = args[-1].split(":", 1)
                refs[reference] = value
            return ""
        with mock.patch("engineering_assistant.internal_promotion._git", side_effect=git), mock.patch(
                "engineering_assistant.internal_promotion._private_repository", create=True):
            result = self.promote(execute=True)
        self.assertEqual("prepared", result["status"])
        self.assertEqual({"refs/tags/" + self.index["release_tag"], "refs/tags/internal/installer/" + VERSION}, set(refs))
        self.assertFalse(any("refs/heads/internal/installer" in argument for call in calls for argument in call))

    def test_activate_requires_separate_fixed_command_and_build_update_evidence(self):
        from engineering_assistant.internal_promotion import promote
        with mock.patch("engineering_assistant.internal_promotion._git") as git:
            with self.assertRaises(ValidationFailure):
                promote(self.candidate, self.evidence_root / "acceptance.json", phase="activate",
                        expected_alias="absent", execute=True)
        git.assert_not_called()

    def test_prepare_reports_written_tag_if_post_push_observation_fails(self):
        pushed = False
        def git(args, root, **kwargs):
            nonlocal pushed
            if args[0] == "show":
                return json.dumps({"version": VERSION})
            if args[0] == "rev-parse":
                return "c" * 40
            if args[0] == "ls-remote":
                if pushed:
                    raise ValidationFailure("synthetic lost observation")
                return ""
            if args[0] == "push":
                pushed = True
            return ""
        with mock.patch("engineering_assistant.internal_promotion._git", side_effect=git), mock.patch(
                "engineering_assistant.internal_promotion._private_repository"):
            result = self.promote(execute=True)
        self.assertEqual("failed", result["status"])
        self.assertTrue(result["remote_modified"])
        self.assertFalse(result["alias_promoted"])
        self.assertFalse(result["remote_checked"])

    def test_prepare_source_tag_conflict_prevents_any_ref_write(self):
        git, refs, calls = self.remote()
        refs["refs/tags/internal/installer/" + VERSION] = "b" * 40
        with mock.patch("engineering_assistant.internal_promotion._git", side_effect=git), mock.patch(
                "engineering_assistant.internal_promotion._private_repository"):
            with self.assertRaisesRegex(ValidationFailure, "内容不同"):
                self.promote(execute=True)
        self.assertFalse(any(call[0] == "push" for call in calls))

    def test_invalid_acceptance_or_assets_never_reaches_git(self):
        (self.candidate / self.index["packages"][0]["archive"]["path"]).write_bytes(b"tampered")
        with mock.patch("engineering_assistant.internal_promotion._git") as git:
            with self.assertRaises(ValidationFailure):
                self.promote(execute=True)
        git.assert_not_called()

    def test_malformed_candidate_fields_fail_without_echoing_untrusted_values(self):
        secret = "https://user:private-test-credential@example.invalid/release"
        changes = (
            lambda index: index.update(canonical_version=secret),
            lambda index: index.update(canonical_version=[]),
            lambda index: index["packages"][0].update(marketplace=[]),
            lambda index: index["packages"][0].update(archive=None),
            lambda index: index.update(setup=[]),
            lambda index: index["setup"].update(verification=[]),
        )
        for position, change in enumerate(changes):
            index = copy.deepcopy(self.index)
            change(index)
            write(self.candidate / "release-index.json", index)
            with self.subTest(case=position), mock.patch("engineering_assistant.internal_promotion._git") as git:
                with self.assertRaises(ValidationFailure) as failure:
                    self.promote(execute=True)
                self.assertNotIn(secret, str(failure.exception))
                git.assert_not_called()

    def test_malformed_acceptance_target_is_a_validation_failure_before_git(self):
        record = copy.deepcopy(self.record)
        record["targets"][0]["target"] = []
        write(self.evidence_root / "acceptance.json", record)
        with mock.patch("engineering_assistant.internal_promotion._git") as git:
            with self.assertRaises(ValidationFailure):
                self.promote(execute=True)
        git.assert_not_called()

    def test_promotion_cli_does_not_echo_unexpected_exception_text(self):
        import importlib.util
        import io
        from contextlib import redirect_stdout
        script = ROOT / "scripts/promote_internal_release.py"
        spec = importlib.util.spec_from_file_location("ea_promotion_cli_review", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        secret = "private-test-credential"
        with mock.patch.object(module, "promote", side_effect=RuntimeError(secret)), redirect_stdout(io.StringIO()) as output:
            result = module.main(["--candidate", str(self.candidate), "--acceptance",
                                  str(self.evidence_root / "acceptance.json"), "--expected-alias", "absent"])
        self.assertEqual(2, result)
        self.assertNotIn(secret, output.getvalue())

    def test_activate_publishes_release_before_alias_cas_and_never_creates_tags(self):
        git, refs, calls = self.remote()
        result, release = self.execute_activation(git)
        self.assertEqual("promoted", result["status"])
        self.assertTrue(result["release_published"])
        pushes = [args for args in calls if args[0] == "push"]
        self.assertEqual(1, len(pushes))
        self.assertIn("--force-with-lease=refs/heads/internal/installer:", pushes[0])
        self.assertEqual(SOURCE_COMMIT + ":refs/heads/internal/installer", pushes[0][-1])
        release.assert_called_once()
        self.assertTrue(result["remote_modified"])

    def test_existing_payload_tag_reused_only_for_identical_tree(self):
        for same in (True, False):
            git, refs, calls = self.remote(tag_tree=("d" if same else "f") * 40)
            with self.subTest(same=same), mock.patch("engineering_assistant.internal_promotion._git", side_effect=git), mock.patch(
                    "engineering_assistant.internal_promotion._private_repository"):
                if same:
                    self.assertEqual("prepared", self.promote(execute=True)["status"])
                else:
                    with self.assertRaisesRegex(ValidationFailure, "内容不同"):
                        self.promote(execute=True)
            self.assertFalse(any(args[0] == "push" for args in calls))

    def test_activate_requires_both_prepared_tags_before_release(self):
        git, refs, calls = self.remote()
        refs.pop("refs/tags/internal/installer/" + VERSION)
        with mock.patch("engineering_assistant.internal_promotion._git", side_effect=git), mock.patch(
                "engineering_assistant.internal_promotion._private_repository"), mock.patch(
                "engineering_assistant.internal_promotion._ensure_release") as release:
            with self.assertRaisesRegex(ValidationFailure, "两个不可变 tag"):
                self.promote(execute=True, phase="activate")
        release.assert_not_called()
        self.assertFalse(any(args[0] == "push" for args in calls))

    def test_unobservable_alias_after_cas_preserves_published_release_state(self):
        git, refs, calls = self.remote(failure="unknown")
        result, _ = self.execute_activation(git)
        self.assertEqual("failed", result["status"])
        self.assertIsNone(result["alias_promoted"])
        self.assertTrue(result["release_published"])
        self.assertIsNone(result["remote_modified"])

    def test_stale_alias_rejects_before_release_or_ref_push(self):
        git, refs, calls = self.remote(alias="b" * 40)
        with mock.patch("engineering_assistant.internal_promotion._git", side_effect=git), mock.patch(
                "engineering_assistant.internal_promotion._private_repository"), mock.patch(
                "engineering_assistant.internal_promotion._ensure_release") as release:
            with self.assertRaisesRegex(ValidationFailure, "alias 已变化"):
                self.promote(execute=True, phase="activate")
        release.assert_not_called()
        self.assertFalse(any(args[0] == "push" for args in calls))

    def test_alias_cas_failure_does_not_hide_already_published_release(self):
        git, refs, calls = self.remote(failure="before")
        result, _ = self.execute_activation(git)
        self.assertEqual("failed", result["status"])
        self.assertTrue(result["release_published"])
        self.assertFalse(result["alias_promoted"])

    def test_git_helper_cannot_follow_inherited_repository_environment(self):
        from engineering_assistant.internal_promotion import _git
        with mock.patch.dict("os.environ", {"GIT_DIR": "/outside", "GIT_WORK_TREE": "/outside"}), \
             mock.patch("engineering_assistant.internal_promotion._protocol_run", return_value=b"") as run:
            _git(["init", "--quiet"], self.root)
        self.assertNotIn("GIT_DIR", run.call_args.kwargs["environment"])
        self.assertNotIn("GIT_WORK_TREE", run.call_args.kwargs["environment"])
        self.assertIn("core.autocrlf=false", run.call_args.args[0])
        self.assertIn("core.hooksPath=" + str(self.root / ".git/no-hooks"), run.call_args.args[0])

    def test_competing_alias_writer_after_lost_cas_response_cannot_claim_no_mutation(self):
        git, refs, calls = self.remote()
        def competing(args, root, **kwargs):
            if args[0] == "push" and args[-1].endswith(":refs/heads/internal/installer"):
                git(args, root, **kwargs)
                refs["refs/heads/internal/installer"] = "b" * 40
                raise ValidationFailure("synthetic lost response followed by competing writer")
            return git(args, root, **kwargs)
        result, _ = self.execute_activation(competing)
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["alias_promoted"])
        self.assertTrue(result["release_published"])
        self.assertIsNone(result["remote_modified"])
        self.assertIn("当前 alias", result["reason"])

    def test_release_failure_never_attempts_alias_cas(self):
        git, refs, calls = self.remote()
        with mock.patch("engineering_assistant.internal_promotion._git", side_effect=git), mock.patch(
                "engineering_assistant.internal_promotion._private_repository"), mock.patch(
                "engineering_assistant.internal_promotion._ensure_release", return_value={"status": "failed",
                    "release_published": False, "remote_modified": True, "reason": "synthetic draft upload failure"}):
            result = self.promote(execute=True, phase="activate")
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["alias_promoted"])
        self.assertFalse(any(call[0] == "push" for call in calls))

    def test_failed_alias_transport_is_observed_instead_of_claiming_rollback(self):
        git, refs, calls = self.remote(failure="after")
        result, _ = self.execute_activation(git)
        self.assertEqual("promoted", result["status"])
        self.assertTrue(result["alias_promoted"])
        self.assertTrue(result["release_published"])

    def test_activation_dry_run_validates_complete_synthetic_receipts_without_remote_calls(self):
        with mock.patch("engineering_assistant.internal_promotion._git") as git, mock.patch(
                "engineering_assistant.internal_promotion._gh") as gh:
            result = self.promote(phase="activate")
        self.assertEqual("ready_for_activate", result["status"])
        self.assertFalse(result["remote_checked"])
        git.assert_not_called()
        gh.assert_not_called()

    def test_activation_rejects_doctor_receipt_in_place_of_build_update(self):
        self.activation_mutate("update", lambda receipt: receipt.update(command=["ea-setup", "doctor", "--agent", "codex", "--json"]))
        with self.assertRaises(ValidationFailure):
            self.promote(phase="activate")

    def test_activation_rejects_exit_zero_while_waiting_for_hook_trust(self):
        self.activation_mutate("install", lambda receipt: receipt["result"].update(status="needs_trust"))
        with self.assertRaises(ValidationFailure):
            self.promote(phase="activate")

    def test_activation_rejects_wrong_pep610_source_even_with_correct_command(self):
        self.activation_mutate("install", lambda receipt: receipt["installer_origin"]["vcs_info"].update(requested_revision="main"))
        with self.assertRaises(ValidationFailure):
            self.promote(phase="activate")

    def test_activation_rejects_unbound_native_cache_location(self):
        self.activation_mutate("update", lambda receipt: receipt["result"].update(package="/synthetic-home/unrelated-package"))
        with self.assertRaises(ValidationFailure):
            self.promote(phase="activate")

    def test_activation_rejects_reused_command_record_across_roles(self):
        self.activation_fixture()
        path = self.activation_root / "activation.json"
        wrapper = json.loads(path.read_bytes())
        wrapper["build_updates"][0]["before_update"] = wrapper["build_updates"][0]["install"]
        write(path, wrapper)
        with self.assertRaises(ValidationFailure):
            self.promote(phase="activate")

    def test_activation_rejects_reused_native_capture_path_across_roles(self):
        self.activation_fixture()
        wrapper = json.loads((self.activation_root / "activation.json").read_bytes())
        install_ref = wrapper["build_updates"][0]["install"]
        install = json.loads((self.activation_root / install_ref["path"]).read_bytes())
        self.activation_mutate("before_update", lambda receipt: receipt.update(native_selection=install["native_selection"]))
        with self.assertRaises(ValidationFailure):
            self.promote(phase="activate")

    def test_native_same_version_captures_may_have_identical_bytes_at_distinct_paths(self):
        self.promote(phase="activate")

    def test_real_cli_needs_trust_exit_pair_can_be_bound_to_separate_host_acceptance(self):
        from engineering_assistant.setup_cli import main
        import io
        from contextlib import redirect_stdout
        self.activation_fixture()
        with redirect_stdout(io.StringIO()), mock.patch("engineering_assistant.setup_cli._execute",
                return_value={"status": "needs_trust", "runtime_ready": True}):
            code = main(["install", "--agent", "codex", "--json"])
        self.assertEqual(2, code)
        self.activation_mutate("install", lambda receipt: (receipt.update(exit_code=code), receipt["result"].update(status="needs_trust")))
        self.assertEqual("ready_for_activate", self.promote(phase="activate")["status"])

    def test_complete_bound_three_host_acceptance_is_accepted(self):
        self.validate()

    def test_original_nine_checks_cannot_promote_without_complete_lifecycle_acceptance(self):
        reference = self.record["targets"][0]["app"]
        path = self.evidence_root / reference["path"]
        evidence = json.loads(path.read_bytes())
        evidence["checks"] = {name: "passed" for name in ORIGINAL_SESSION_CHECKS}
        write(path, evidence)
        reference["sha256"] = sha(path.read_bytes())
        write(self.evidence_root / "acceptance.json", self.record)
        with mock.patch("engineering_assistant.internal_promotion._git") as git:
            with self.assertRaises(ValidationFailure):
                self.promote()
        git.assert_not_called()

    def test_every_native_session_lifecycle_check_is_mandatory_and_must_pass(self):
        for item in self.record["targets"]:
            for role in ("app", "cli"):
                reference = item[role]
                path = self.evidence_root / reference["path"]
                original = path.read_bytes()
                evidence = json.loads(original)
                for name in sorted(LIFECYCLE_SESSION_CHECKS):
                    for outcome in ("missing", "failed"):
                        changed = copy.deepcopy(evidence)
                        changed["checks"] = {check: "passed" for check in LIFECYCLE_SESSION_CHECKS}
                        if outcome == "missing":
                            changed["checks"].pop(name)
                        else:
                            changed["checks"][name] = "failed"
                        write(path, changed)
                        reference["sha256"] = sha(path.read_bytes())
                        write(self.evidence_root / "acceptance.json", self.record)
                        with self.subTest(target=item["target"], role=role, check=name, outcome=outcome), \
                                mock.patch("engineering_assistant.internal_promotion._git") as git:
                            with self.assertRaises(ValidationFailure):
                                self.promote(execute=True)
                            git.assert_not_called()
                path.write_bytes(original)
                reference["sha256"] = sha(original)
        write(self.evidence_root / "acceptance.json", self.record)

    def test_metadata_or_target_coverage_cannot_be_substituted(self):
        variants = []
        for field, value in (("source_commit", "b" * 40), ("canonical_version", "9.0.0.0-rc.1"),
                             ("candidate_index_digest", "sha256:" + "0" * 64)):
            record = copy.deepcopy(self.record)
            record[field] = value
            variants.append(record)
        variants += [{**self.record, "targets": self.record["targets"][:-1]},
                     {**self.record, "targets": self.record["targets"] + self.record["targets"][:1]}]
        for record in variants:
            with self.subTest(record=record):
                with self.assertRaises(ValidationFailure):
                    self.validate(record)

    def test_windows_server_and_unqualified_macos_are_rejected(self):
        for position, name, version in ((2, "Windows Server", "2025"), (0, "macOS", "13.0")):
            record = copy.deepcopy(self.record)
            record["targets"][position]["os"] = {"name": name, "version": version}
            with self.assertRaises(ValidationFailure):
                self.validate(record)

    def test_evidence_rehash_and_native_session_semantics_are_required(self):
        item = self.record["targets"][0]
        path = self.evidence_root / item["app"]["path"]
        original = path.read_bytes()
        for mutation in (lambda e: e.update(authenticated=False), lambda e: e.update(execution="simulation"),
                         lambda e: e.update(evidence_kind="doctor"), lambda e: e["checks"].update(hook="not_run")):
            evidence = json.loads(original)
            mutation(evidence)
            write(path, evidence)
            record = copy.deepcopy(self.record)
            record["targets"][0]["app"]["sha256"] = sha(path.read_bytes())
            with self.assertRaises(ValidationFailure):
                self.validate(record)
        path.write_bytes(original + b" ")
        with self.assertRaises(ValidationFailure):
            self.validate()

    def test_provider_complete_boundary_checks_and_baselines_are_required(self):
        item = self.record["targets"][2]
        path = self.evidence_root / item["provider"]["path"]
        evidence = json.loads(path.read_bytes())
        evidence["checks"]["positive_execution"] = False
        write(path, evidence)
        record = copy.deepcopy(self.record)
        record["targets"][2]["provider"]["sha256"] = sha(path.read_bytes())
        with self.assertRaises(ValidationFailure):
            self.validate(record)

    def test_evidence_references_cannot_escape_or_reuse_session_receipts(self):
        for path in ("../secret", "evidence/CON.json", "evidence/file:stream", "evidence/link.json"):
            record = copy.deepcopy(self.record)
            record["targets"][0]["app"]["path"] = path
            if path.endswith("link.json"):
                (self.evidence_root / path).symlink_to(self.evidence_root / self.record["targets"][0]["app"]["path"])
            with self.assertRaises((OSError, ValidationFailure)):
                self.validate(record)
        record = copy.deepcopy(self.record)
        record["targets"][0]["cli"] = record["targets"][0]["app"]
        with self.assertRaises(ValidationFailure):
            self.validate(record)


class ReleaseBoundaryTests(unittest.TestCase):
    """Mock GitHub transport exercises exact byte checks, never publishes a Release."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "release"
        self.root.mkdir()
        self.bundle = self.root.parent / "activation-evidence.zip"
        self.bundle.write_bytes(b"synthetic evidence bundle")
        self.notes = self.root.parent / "installation.md"
        self.notes.write_bytes(b"synthetic reviewed tutorial")
        self.body = "synthetic tutorial\nnotes/bundle exact hash bindings"
        self.index = {"canonical_version": "1.0.0.1", "release_tag": "internal/codex/1.0.0.1"}
        self.release = None
        self.files = {}
        self.calls = []
        self.tamper = False
        self.fail_upload = False
        self.unknown_publish = False

    def api(self, endpoint, root, *, method="GET", payload=None):
        from engineering_assistant.release_assets import INTERNAL_REPOSITORY
        self.calls.append((method, endpoint, payload))
        if "?per_page" in endpoint:
            return [] if self.release is None else [copy.deepcopy(self.release)]
        if method == "POST":
            self.release = {**payload, "id": 123, "url": "https://api.github.com/repos/" + INTERNAL_REPOSITORY + "/releases/123", "assets": []}
        elif method == "PATCH":
            self.release["draft"] = payload["draft"]
            if self.unknown_publish:
                raise ValidationFailure("synthetic response lost after publication")
        return copy.deepcopy(self.release)

    def gh(self, arguments, root, **kwargs):
        self.calls.append(tuple(arguments))
        if arguments[1] == "upload":
            if self.fail_upload:
                raise ValidationFailure("synthetic controlled upload failure")
            path = Path(arguments[3])
            self.files[path.name] = path.read_bytes()
            self.release["assets"].append({"name": path.name, "state": "uploaded", "size": path.stat().st_size})
        elif arguments[1] == "download":
            name = arguments[arguments.index("--pattern") + 1]
            destination = Path(arguments[arguments.index("--dir") + 1]) / name
            raw = self.files[name]
            destination.write_bytes(b"x" * len(raw) if self.tamper else raw)
        return b""

    def ensure(self):
        from engineering_assistant.internal_promotion import _ensure_release
        for path in self.root.parent.glob("download-*"):
            shutil.rmtree(path)
        with mock.patch("engineering_assistant.internal_promotion._api", side_effect=self.api), mock.patch(
                "engineering_assistant.internal_promotion._gh", side_effect=self.gh):
            return _ensure_release(self.index, self.root, self.body, self.bundle, self.notes)

    def test_formal_internal_release_stays_private_channel_without_prerelease_label(self):
        result = self.ensure()
        self.assertEqual("published", result["status"])
        self.assertFalse(self.release["prerelease"])
        self.assertFalse(self.release["draft"])
        self.assertEqual("false", self.release["make_latest"])
        self.assertEqual({self.bundle.name, self.notes.name}, set(self.files))
        uploads = [position for position, call in enumerate(self.calls) if isinstance(call, tuple) and call[:2] == ("release", "upload")]
        downloads = [position for position, call in enumerate(self.calls) if isinstance(call, tuple) and call[:2] == ("release", "download")]
        publish = [position for position, call in enumerate(self.calls) if call[0] == "PATCH"]
        self.assertEqual(2, len(downloads))
        self.assertLess(max(uploads + downloads), publish[0])

    def test_existing_rc_internal_release_retains_prerelease_semantics(self):
        self.index = {"canonical_version": VERSION, "release_tag": "internal/codex/" + VERSION}
        self.assertEqual("published", self.ensure()["status"])
        self.assertTrue(self.release["prerelease"])

    def test_same_size_but_tampered_remote_asset_blocks_publication(self):
        self.tamper = True
        result = self.ensure()
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["release_published"])
        self.assertTrue(self.release["draft"])
        self.assertFalse(any(call[0] == "PATCH" for call in self.calls))

    def test_failed_upload_retains_draft_and_cannot_claim_usable_release(self):
        self.fail_upload = True
        result = self.ensure()
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["release_published"])
        self.assertTrue(self.release["draft"])

    def test_lost_publish_response_reports_unknown_remote_state(self):
        self.unknown_publish = True
        result = self.ensure()
        self.assertEqual("failed", result["status"])
        self.assertIsNone(result["release_published"])
        self.assertFalse(self.release["draft"])

    def test_existing_release_with_different_notes_or_evidence_is_not_overwritten(self):
        self.ensure()
        self.calls.clear()
        self.body += " changed binding"
        result = self.ensure()
        self.assertEqual("failed", result["status"])
        self.assertFalse(any(call[0] in {"PATCH", "POST"} or call[:2] == ("release", "upload") for call in self.calls))

    def test_existing_published_release_missing_asset_is_not_repaired_or_republished(self):
        self.ensure()
        self.release["assets"].pop()
        self.calls.clear()
        result = self.ensure()
        self.assertEqual("failed", result["status"])
        self.assertTrue(result["release_published"])
        self.assertFalse(any(call[0] in {"PATCH", "POST"} or call[:2] == ("release", "upload") for call in self.calls))

    def test_git_environment_cannot_rewrite_fixed_https_origin(self):
        from engineering_assistant.internal_promotion import _git, REMOTE
        if shutil.which("git") is None:
            self.skipTest("real temporary Git regression requires Git")
        _git(["init", "--quiet"], self.root)
        _git(["remote", "add", "origin", REMOTE], self.root)
        injected = (
            {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "url.https://example.invalid/.insteadOf",
             "GIT_CONFIG_VALUE_0": "https://github.com/"},
            {"GIT_CONFIG_PARAMETERS": "'url.https://example.invalid/.insteadOf'='https://github.com/'"},
        )
        for environment in injected:
            with self.subTest(environment_keys=sorted(environment)), mock.patch.dict("os.environ", environment):
                self.assertEqual(REMOTE, _git(["remote", "get-url", "origin"], self.root))

    def test_public_or_different_repository_is_rejected(self):
        from engineering_assistant.internal_promotion import _private_repository
        for identity in ({"full_name": "snbc-qihang/agent-skills", "private": False},
                         {"full_name": "another/repository", "private": True}):
            with self.subTest(identity=identity), mock.patch("engineering_assistant.internal_promotion._api", return_value=identity):
                with self.assertRaises(ValidationFailure):
                    _private_repository(self.root)


if __name__ == "__main__":
    unittest.main()
