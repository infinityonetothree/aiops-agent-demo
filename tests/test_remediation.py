import json
import subprocess
import unittest
from unittest.mock import patch

from aiops.config import Config
from aiops.remediate import restart_demo_target


class RemediationTests(unittest.TestCase):
    def test_rejects_unauthorized_target_before_calling_docker(self):
        with patch("aiops.remediate.subprocess.run", side_effect=AssertionError("called Docker")):
            with self.assertRaises(PermissionError):
                restart_demo_target("database", Config())

    def test_rejects_container_from_other_project(self):
        obj = {"Name": "/aiops-recommendation", "Config": {"Labels": {
            "com.docker.compose.project": "unrelated", "com.docker.compose.service": "recommendation",
        }}}
        calls = []

        def fake_run(argv, **_kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps([obj]), "")

        with patch("aiops.remediate.subprocess.run", side_effect=fake_run):
            with self.assertRaises(PermissionError):
                restart_demo_target("recommendation", Config())
        self.assertEqual(calls, [["docker", "inspect", "aiops-recommendation"]])
