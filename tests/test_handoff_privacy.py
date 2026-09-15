"""The saved handoff must not leak the host name by default.

The handoff body is committed and travels to other machines and people, so the machine
field defaults to an explicit placeholder and only shows a real label when the user opts
in via `HARNESS_HANDOFF_MACHINE`.
"""
import importlib.util
import os
import socket
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
            self.assertEqual(handoff.machine_name(), "undisclosed")

    def test_machine_name_does_not_leak_the_host_name(self):
        """The default must be a fixed placeholder, never anything derived from the host."""
        with patch.dict(os.environ, {}, clear=True):
            name = handoff.machine_name()
        for leak in (socket.gethostname(), os.path.expanduser("~")):
            if leak:
                self.assertNotIn(leak, name)

    def test_machine_name_can_be_explicitly_labeled(self):
        with patch.dict(
            os.environ, {"HARNESS_HANDOFF_MACHINE": "team-runner"}, clear=True
        ):
            self.assertEqual(handoff.machine_name(), "team-runner")


if __name__ == "__main__":
    unittest.main()
