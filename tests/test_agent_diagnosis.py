import asyncio
import os
import sys
import types
import unittest
from unittest.mock import patch

from aiops.config import Config
from aiops.diagnose import claude_diagnosis


ALERT = {"alertname": "RecommendationMemoryGrowth", "service": "recommendation"}
DIAGNOSIS = {
    "kind": "deploy_regression", "suspect_service": "recommendation",
    "remediation_type": "online_op", "confidence": 0.8,
    "summary": "Growing retained product count", "evidence": ["observed growth"],
    "also_code_fix": True, "proposed_action": "restart_instance",
}


class AssistantMessage:
    def __init__(self, content):
        self.content = content


class ToolUseBlock:
    def __init__(self, name):
        self.name = name


class ResultMessage:
    def __init__(self, *, is_error=False, terminal_reason=None):
        self.subtype = "success"
        self.is_error = is_error
        self.terminal_reason = terminal_reason
        self.structured_output = DIAGNOSIS
        self.num_turns = 2
        self.total_cost_usd = 0.01


def fake_sdk(messages):
    async def query(**_kwargs):
        for message in messages:
            yield message

    module = types.ModuleType("claude_agent_sdk")
    module.AssistantMessage = AssistantMessage
    module.ToolUseBlock = ToolUseBlock
    module.ResultMessage = ResultMessage
    module.ClaudeAgentOptions = lambda **kwargs: kwargs
    module.create_sdk_mcp_server = lambda **kwargs: kwargs
    module.tool = lambda *_args: lambda function: function
    module.query = query
    return module


class AgentDiagnosisTests(unittest.TestCase):
    def test_missing_key_fails_before_sdk_call(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY"):
                asyncio.run(claude_diagnosis(ALERT, Config()))

    def test_structured_answer_requires_observation_tool(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}), \
             patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk([ResultMessage()])}):
            with self.assertRaisesRegex(RuntimeError, "did not call"):
                asyncio.run(claude_diagnosis(ALERT, Config()))

    def test_valid_tool_call_records_cost_and_turns(self):
        messages = [
            AssistantMessage([ToolUseBlock("mcp__aiops_demo__inspect_demo")]),
            ResultMessage(),
        ]
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}), \
             patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk(messages)}):
            outcome = asyncio.run(claude_diagnosis(ALERT, Config()))
        self.assertEqual(outcome.diagnosis.suspect_service, "recommendation")
        self.assertTrue(outcome.run["tool_called"])
        self.assertEqual(outcome.run["num_turns"], 2)
        self.assertEqual(outcome.run["total_cost_usd"], 0.01)

    def test_success_subtype_with_api_error_is_rejected(self):
        messages = [
            AssistantMessage([ToolUseBlock("mcp__aiops_demo__inspect_demo")]),
            ResultMessage(is_error=True, terminal_reason="api_error"),
        ]
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}), \
             patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk(messages)}):
            with self.assertRaisesRegex(RuntimeError, "api_error"):
                asyncio.run(claude_diagnosis(ALERT, Config()))
