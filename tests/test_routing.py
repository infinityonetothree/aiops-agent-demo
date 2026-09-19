import asyncio
import unittest
from unittest.mock import patch

from aiops.config import Config
from aiops.diagnose import heuristic_diagnosis
from aiops.run import run_alert
from aiops.schema import Diagnosis


ALERT = {"alertname": "RecommendationMemoryGrowth", "service": "recommendation"}


class RoutingTests(unittest.TestCase):
    def test_growth_proposes_temporary_restart_and_code_fix(self):
        snapshot = {
            "seen_products_samples": [100, 400, 900],
            "docker": {"running": True, "restart_count": 1, "oom_killed": True},
        }
        diagnosis = heuristic_diagnosis(ALERT, snapshot)
        self.assertEqual(diagnosis.remediation_type, "online_op")
        self.assertEqual(diagnosis.proposed_action, "restart_instance")
        self.assertTrue(diagnosis.also_code_fix)

    def test_no_observations_route_to_human(self):
        with patch("aiops.run.collect_snapshot", return_value={"errors": ["daemon unavailable"]}):
            report = asyncio.run(run_alert(ALERT, Config()))
        self.assertEqual(report.route, "human_review_low_confidence")
        self.assertFalse(report.executed_actions)

    def test_action_requires_explicit_apply_flag(self):
        diagnosis = Diagnosis(
            kind="resource", suspect_service="recommendation", remediation_type="online_op",
            confidence=0.9, summary="growth", evidence=["measured growth"],
            proposed_action="restart_instance",
        )
        with patch("aiops.run.collect_snapshot", return_value={}), \
             patch("aiops.run.heuristic_diagnosis", return_value=diagnosis), \
             patch("aiops.run.restart_demo_target", side_effect=AssertionError("restart attempted")):
            report = asyncio.run(run_alert(ALERT, Config()))
        self.assertEqual(report.route, "human_review_online_op")
        self.assertFalse(report.executed_actions)
