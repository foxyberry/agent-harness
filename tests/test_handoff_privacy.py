import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "handoff", ROOT / "core" / "scripts" / "handoff.py"
)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)


class HandoffPrivacyTest(unittest.TestCase):
    def test_machine_name_is_private_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(handoff.machine_name(), "비공개")

    def test_machine_name_can_be_explicitly_labeled(self):
        with patch.dict(
            os.environ, {"HARNESS_HANDOFF_MACHINE": "team-runner"}, clear=True
        ):
            self.assertEqual(handoff.machine_name(), "team-runner")


if __name__ == "__main__":
    unittest.main()
