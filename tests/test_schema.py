import unittest

from aiops.schema import Diagnosis


class SchemaTests(unittest.TestCase):
    def test_invalid_confidence_is_rejected(self):
        with self.assertRaises(ValueError):
            Diagnosis.parse({
                "kind": "unknown", "suspect_service": "recommendation",
                "remediation_type": "info_only", "confidence": 1.5,
                "summary": "bad", "evidence": ["sample"],
            })

    def test_evidence_cannot_be_empty(self):
        with self.assertRaises(ValueError):
            Diagnosis.parse({
                "kind": "unknown", "suspect_service": "recommendation",
                "remediation_type": "info_only", "confidence": 0.1,
                "summary": "bad", "evidence": [],
            })

    def test_restart_requires_online_operation_route(self):
        with self.assertRaisesRegex(ValueError, "online_op"):
            Diagnosis.parse({
                "kind": "resource", "suspect_service": "recommendation",
                "remediation_type": "code_fix", "confidence": 0.9,
                "summary": "fix leak", "evidence": ["growth"],
                "also_code_fix": True, "proposed_action": "restart_instance",
            })
