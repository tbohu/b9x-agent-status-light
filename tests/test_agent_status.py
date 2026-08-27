#!/usr/bin/python3
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EVENT = ROOT / "src/b9x_agent_event.py"
MONITOR_PATH = ROOT / "src/b9x_agent_monitor.py"


def load_monitor():
    spec = importlib.util.spec_from_file_location("monitor", MONITOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        self.env = dict(os.environ, B9X_AGENT_STATE_DIR=str(self.state))

    def tearDown(self):
        self.temp.cleanup()

    def event(self, provider, name, **extra):
        payload = {"session_id": provider + "-session", "hook_event_name": name, **extra}
        result = subprocess.run(
            ["/usr/bin/python3", str(EVENT), provider],
            input=json.dumps(payload), text=True, capture_output=True, env=self.env
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def states(self):
        return [json.loads(path.read_text()) for path in (self.state / "sessions").glob("*.json")]

    def test_priority_and_error_latch(self):
        monitor = load_monitor()
        self.event("codex", "UserPromptSubmit")
        self.event("claude", "UserPromptSubmit")
        status, _ = monitor.desired_status(self.states(), 1, False)
        self.assertEqual(status, "working")
        self.event("claude", "PermissionRequest", tool_name="Bash")
        status, _ = monitor.desired_status(self.states(), 1, False)
        self.assertEqual(status, "error")
        self.event("claude", "Stop")
        status, _ = monitor.desired_status(self.states(), 0, False)
        self.assertEqual(status, "error")
        self.event("claude", "UserPromptSubmit")
        status, _ = monitor.desired_status(self.states(), 0, False)
        self.assertEqual(status, "working")

    def test_completed_agents_are_green(self):
        monitor = load_monitor()
        self.event("claude", "UserPromptSubmit")
        self.event("claude", "Stop", background_tasks=[])
        status, reasons = monitor.desired_status(self.states(), 0, False)
        self.assertEqual((status, reasons), ("idle", ["no active task"]))

    def test_background_task_stays_yellow(self):
        monitor = load_monitor()
        self.event("claude", "UserPromptSubmit")
        self.event("claude", "Stop", background_tasks=[{"id": "1"}])
        status, _ = monitor.desired_status(self.states(), 0, False)
        self.assertEqual(status, "working")

    def test_stop_failure_is_red(self):
        monitor = load_monitor()
        self.event("claude", "StopFailure", error="rate_limit")
        status, _ = monitor.desired_status(self.states(), 0, False)
        self.assertEqual(status, "error")


if __name__ == "__main__":
    unittest.main()
