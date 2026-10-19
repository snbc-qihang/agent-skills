"""Consumer behavior after separating author tooling from the runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.installer import installation


class RuntimeBoundaryTests(unittest.TestCase):
    def test_mac_intel_is_rejected_before_runtime_preparation(self):
        with mock.patch.object(installation.platform, "system", return_value="Darwin"), mock.patch.object(
            installation.platform, "machine", return_value="x86_64"
        ), mock.patch.object(installation.platform, "mac_ver", return_value=("14.7", (), "")):
            self.assertEqual("unsupported", installation.host_target())

    def test_runtime_routes_without_installer_or_author_tools(self):
        intent = dict(task_kind="review", requested_outcome="只读评审", scope=["fixture"],
                      risk_signals=["security"], requested_external_actions=[], confirmed_actions=[],
                      confidence=.99, evidence=["用户要求只读"], read_only=True)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "src/engineering_assistant", root / "engineering_assistant",
                            ignore=shutil.ignore_patterns("__pycache__", "tools", "installer"))
            request = root / "intent.json"
            request.write_text(json.dumps(intent), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, "-m", "engineering_assistant.runtime.cli", "--repository-root", str(ROOT),
                 "route", "--intent", str(request)], cwd=root,
                env={**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(0, process.returncode, process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual("proceed", result["decision"]["decision"])
            self.assertEqual("inline", result["execution"]["recommended_execution"])


if __name__ == "__main__":
    unittest.main()
