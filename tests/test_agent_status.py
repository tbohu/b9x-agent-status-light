#!/usr/bin/python3
import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


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

    def test_stop_is_idle_even_with_background_helpers(self):
        monitor = load_monitor()
        self.event("claude", "UserPromptSubmit")
        self.event("claude", "Stop", background_tasks=[
            {"id": "1", "type": "subagent"},
            {"id": "2", "type": "monitor"},
            {"id": "3", "type": "shell"},
        ])
        status, reasons = monitor.desired_status(self.states(), 0, False)
        self.assertEqual((status, reasons), ("idle", ["no active task"]))

    def test_idle_notification_is_green(self):
        monitor = load_monitor()
        self.event("claude", "UserPromptSubmit")
        self.event("claude", "Notification", notification_type="idle_prompt")
        status, reasons = monitor.desired_status(self.states(), 0, False)
        self.assertEqual((status, reasons), ("idle", ["no active task"]))

    def test_stop_failure_is_red(self):
        monitor = load_monitor()
        self.event("claude", "StopFailure", error="rate_limit")
        status, _ = monitor.desired_status(self.states(), 0, False)
        self.assertEqual(status, "error")

    def test_rate_limit_stays_red_for_five_minutes(self):
        monitor = load_monitor()
        sessions = self.state / "sessions"
        sessions.mkdir()
        (sessions / "claude-limit.json").write_text(json.dumps({
            "provider": "claude",
            "event": "StopFailure",
            "detail": "rate_limit",
            "status": "error",
            "latched": True,
            "updated_at": 1000,
        }))
        with (
            mock.patch.object(monitor, "STATE_ROOT", self.state),
            mock.patch.object(monitor.time, "time", return_value=1299),
        ):
            states = monitor.session_states()
        self.assertEqual(states[0]["status"], "error")

    def test_rate_limit_expires_after_five_minutes(self):
        monitor = load_monitor()
        sessions = self.state / "sessions"
        sessions.mkdir()
        (sessions / "claude-limit.json").write_text(json.dumps({
            "provider": "claude",
            "event": "StopFailure",
            "detail": "rate_limit",
            "status": "error",
            "latched": True,
            "updated_at": 1000,
        }))
        with (
            mock.patch.object(monitor, "STATE_ROOT", self.state),
            mock.patch.object(monitor.time, "time", return_value=1300),
        ):
            states = monitor.session_states()
        self.assertEqual(states[0]["status"], "idle")
        self.assertFalse(states[0]["latched"])
        self.assertEqual(states[0]["detail"], "rate_limit_expired")

    def test_non_rate_limit_failure_does_not_expire(self):
        monitor = load_monitor()
        sessions = self.state / "sessions"
        sessions.mkdir()
        (sessions / "claude-failure.json").write_text(json.dumps({
            "provider": "claude",
            "event": "StopFailure",
            "detail": "network_error",
            "status": "error",
            "latched": True,
            "updated_at": 1000,
        }))
        with (
            mock.patch.object(monitor, "STATE_ROOT", self.state),
            mock.patch.object(monitor.time, "time", return_value=9999),
        ):
            states = monitor.session_states()
        self.assertEqual(states[0]["status"], "error")

    def test_tool_failure_stays_yellow_while_claude_recovers(self):
        monitor = load_monitor()
        self.event("claude", "PostToolUseFailure", tool_name="Bash", error="timeout")
        state = self.states()[0]
        self.assertEqual((state["status"], state["latched"]), ("working", False))
        status, _ = monitor.desired_status(self.states(), 0, False)
        self.assertEqual(status, "working")

    def test_legacy_tool_failure_error_is_recoverable(self):
        monitor = load_monitor()
        sessions = self.state / "sessions"
        sessions.mkdir()
        (sessions / "claude-legacy.json").write_text(json.dumps({
            "provider": "claude",
            "session_id": "legacy",
            "event": "PostToolUseFailure",
            "detail": "timeout",
            "status": "error",
            "latched": True,
            "updated_at": int(time.time()),
        }))
        with mock.patch.object(monitor, "STATE_ROOT", self.state):
            states = monitor.session_states()
        self.assertEqual((states[0]["status"], states[0]["latched"]), ("working", False))

    def test_completed_transcript_clears_stale_claude_working_state(self):
        monitor = load_monitor()
        transcript = self.state / "claude.jsonl"
        started = int(time.time())
        transcript.write_text(json.dumps({
            "type": "assistant",
            "sessionId": "claude-session",
            "isSidechain": False,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started + 1)),
            "message": {"stop_reason": "end_turn", "content": [{"type": "text"}]},
        }) + "\n")
        self.event("claude", "UserPromptSubmit", transcript_path=str(transcript))
        session_file = next((self.state / "sessions").glob("claude-*.json"))
        value = json.loads(session_file.read_text())
        value["updated_at"] = started
        session_file.write_text(json.dumps(value))
        with mock.patch.object(monitor, "STATE_ROOT", self.state):
            states = monitor.session_states()
        self.assertEqual(states[0]["status"], "idle")
        self.assertEqual(states[0]["detail"], "transcript:end_turn")

    def test_old_end_turn_does_not_clear_new_prompt(self):
        monitor = load_monitor()
        transcript = self.state / "claude.jsonl"
        started = int(time.time())
        transcript.write_text(json.dumps({
            "type": "assistant",
            "sessionId": "claude-session",
            "isSidechain": False,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started - 10)),
            "message": {"stop_reason": "end_turn", "content": [{"type": "text"}]},
        }) + "\n")
        self.event("claude", "UserPromptSubmit", transcript_path=str(transcript))
        with mock.patch.object(monitor, "STATE_ROOT", self.state):
            states = monitor.session_states()
        self.assertEqual(states[0]["status"], "working")

    def test_legacy_working_stop_is_idle(self):
        monitor = load_monitor()
        sessions = self.state / "sessions"
        sessions.mkdir()
        (sessions / "claude-legacy.json").write_text(json.dumps({
            "provider": "claude",
            "session_id": "legacy",
            "event": "Stop",
            "detail": "Stop",
            "status": "working",
            "latched": False,
            "updated_at": int(time.time()),
        }))
        with mock.patch.object(monitor, "STATE_ROOT", self.state):
            states = monitor.session_states()
        self.assertEqual(states[0]["status"], "idle")

    def test_new_hook_event_reapplies_unchanged_color(self):
        monitor = load_monitor()
        self.event("claude", "UserPromptSubmit")
        runtime = {"desired_color": "yellow", "processed_wake_at": 0}
        completed = subprocess.CompletedProcess([], 0, "COLOR_SET color=yellow\n", "")
        with (
            mock.patch.object(monitor, "STATE_ROOT", self.state),
            mock.patch.object(monitor, "MONITOR_STATE", self.state / "monitor.json"),
            mock.patch.object(monitor, "CONTROL_STATE", self.state / "control.json"),
            mock.patch.object(monitor, "WAKE_STATE", self.state / "wake.json"),
            mock.patch.object(monitor, "codex_snapshot", return_value=(0, {}, False, False)),
            mock.patch.object(monitor.subprocess, "run", return_value=completed) as light,
        ):
            result = monitor.reconcile(runtime)
        light.assert_called_once()
        self.assertEqual(result["applied_color"], "yellow")

    def test_status_transition_plays_sound_once(self):
        monitor = load_monitor()
        sounds = self.state / "sounds"
        sounds.mkdir()
        (sounds / "working.wav").write_bytes(b"wave")
        runtime = {"desired_status": "idle", "desired_color": "green"}
        completed = subprocess.CompletedProcess([], 0, "COLOR_SET color=yellow\n", "")
        player = mock.Mock(pid=123)
        with (
            mock.patch.object(monitor, "STATE_ROOT", self.state),
            mock.patch.object(monitor, "MONITOR_STATE", self.state / "monitor.json"),
            mock.patch.object(monitor, "CONTROL_STATE", self.state / "control.json"),
            mock.patch.object(monitor, "WAKE_STATE", self.state / "wake.json"),
            mock.patch.object(monitor, "SOUND_ROOT", sounds),
            mock.patch.object(monitor, "codex_snapshot", return_value=(1, {}, False, False)),
            mock.patch.object(monitor.subprocess, "run", return_value=completed),
            mock.patch.object(monitor.subprocess, "Popen", return_value=player) as play,
        ):
            runtime = monitor.reconcile(runtime)
            runtime = monitor.reconcile(runtime)
        play.assert_called_once_with(
            ["/usr/bin/afplay", str(sounds / "working.wav")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.assertEqual(runtime["sound_event"], "working")

    def test_quiet_mode_suppresses_transition_sound(self):
        monitor = load_monitor()
        (self.state / "control.json").write_text('{"quiet": true}')
        runtime = {"desired_status": "idle", "desired_color": "green"}
        completed = subprocess.CompletedProcess([], 0, "COLOR_SET color=yellow\n", "")
        with (
            mock.patch.object(monitor, "STATE_ROOT", self.state),
            mock.patch.object(monitor, "MONITOR_STATE", self.state / "monitor.json"),
            mock.patch.object(monitor, "CONTROL_STATE", self.state / "control.json"),
            mock.patch.object(monitor, "WAKE_STATE", self.state / "wake.json"),
            mock.patch.object(monitor, "codex_snapshot", return_value=(1, {}, False, False)),
            mock.patch.object(monitor.subprocess, "run", return_value=completed),
            mock.patch.object(monitor.subprocess, "Popen") as play,
        ):
            result = monitor.reconcile(runtime)
        play.assert_not_called()
        self.assertTrue(result["quiet"])
        self.assertEqual(result["sound_output"], "quiet")

    def test_set_quiet_preserves_other_control_fields(self):
        monitor = load_monitor()
        control = self.state / "control.json"
        control.write_text('{"acknowledge_at": 123}')
        with (
            mock.patch.object(monitor, "STATE_ROOT", self.state),
            mock.patch.object(monitor, "CONTROL_STATE", control),
            mock.patch.object(monitor, "WAKE_STATE", self.state / "wake.json"),
        ):
            monitor.set_quiet(True)
        self.assertEqual(json.loads(control.read_text()), {"acknowledge_at": 123, "quiet": True})


if __name__ == "__main__":
    unittest.main()
