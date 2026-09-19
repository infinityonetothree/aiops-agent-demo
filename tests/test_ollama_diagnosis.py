import asyncio
import json
import unittest
from unittest.mock import patch

from aiops.config import Config
from aiops.diagnose import ollama_diagnosis


ALERT = {"alertname": "RecommendationMemoryGrowth", "service": "recommendation"}
DIAGNOSIS = {
    "kind": "deploy_regression", "suspect_service": "recommendation",
    "remediation_type": "online_op", "confidence": 0.8,
    "summary": "Growing retained product count", "evidence": ["observed growth"],
    "also_code_fix": True, "proposed_action": "restart_instance",
}


class OllamaDiagnosisTests(unittest.TestCase):
    def test_requires_exact_read_only_tool_call(self):
        response = {"message": {"content": "no tool"}}
        with patch("aiops.diagnose._ollama_chat", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "exactly once"):
                asyncio.run(ollama_diagnosis(ALERT, Config()))

    def test_tool_result_is_followed_by_schema_bound_diagnosis(self):
        first = {
            "message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "inspect_demo", "arguments": {}}}
            ]},
            "prompt_eval_count": 10, "eval_count": 2, "total_duration": 1_000_000,
        }
        final = {
            "message": {"content": json.dumps(DIAGNOSIS)},
            "prompt_eval_count": 20, "eval_count": 30, "total_duration": 2_000_000,
        }
        snapshot = {"docker": {"labels": {"secret": "excluded"}, "running": True}}
        with patch("aiops.diagnose._ollama_chat", side_effect=[first, final]) as chat, \
             patch("aiops.observe.collect_snapshot", return_value=snapshot):
            outcome = asyncio.run(ollama_diagnosis(ALERT, Config()))
        self.assertEqual(outcome.diagnosis.kind, "deploy_regression")
        self.assertEqual(outcome.run["provider"], "ollama")
        self.assertTrue(outcome.run["tool_called"])
        second_payload = chat.call_args_list[1].args[1]
        self.assertEqual(second_payload["format"]["type"], "object")
        self.assertNotIn("secret", json.dumps(second_payload))
