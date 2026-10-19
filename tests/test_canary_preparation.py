from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engineering_assistant.tools.canary import _observation_claims  # noqa: E402
from engineering_assistant.tools.canary_protocol import canonical_digest  # noqa: E402


class LocalCanaryTests(unittest.TestCase):
    def test_canary_contract_is_local_unattested_and_has_no_attestation_schema(self) -> None:
        evidence_schema = json.loads(
            (ROOT / "evals/canary/run-evidence.schema.json").read_text()
        )
        result_schema = json.loads(
            (ROOT / "evals/canary/result.schema.json").read_text()
        )

        self.assertEqual(
            {"const": "local_unattested"}, evidence_schema["properties"]["assurance"]
        )
        self.assertEqual(
            {"const": "local_unattested"}, result_schema["properties"]["assurance"]
        )
        self.assertNotIn("attestation", evidence_schema["properties"])
        self.assertNotIn("trust_provenance", evidence_schema["properties"])
        self.assertFalse((ROOT / "evals/canary/attestation-response.schema.json").exists())

    def test_local_claim_is_only_a_canonical_digest(self) -> None:
        observation = {"assurance": "local_unattested", "task_id": "task-1"}
        self.assertEqual(
            {"canary_observation": {"digest": canonical_digest(observation)}},
            _observation_claims(observation),
        )


if __name__ == "__main__":
    unittest.main()
