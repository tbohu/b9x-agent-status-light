#!/usr/bin/python3
import importlib.util
import plistlib
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INSTALL_PATH = ROOT / "src/install.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("installer", INSTALL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.installer = load_installer()

    def test_merge_is_idempotent_and_preserves_existing_hook(self):
        original = {
            "theme": "dark",
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]
            },
        }
        command = "/usr/bin/python3 '/tmp/B9X Agent Status Light/src/b9x_agent_event.py' codex"
        once = self.installer.merge_hooks(original, command, "codex")
        twice = self.installer.merge_hooks(once, command, "codex")
        handlers = [
            handler
            for group in twice["hooks"]["Stop"]
            for handler in group["hooks"]
        ]
        self.assertEqual(sum(h["command"] == "echo existing" for h in handlers), 1)
        self.assertEqual(sum("b9x_agent_event.py" in h["command"] for h in handlers), 1)
        self.assertEqual(twice["theme"], "dark")

    def test_remove_preserves_unrelated_settings(self):
        command = "/usr/bin/python3 '/tmp/B9X Agent Status Light/src/b9x_agent_event.py' claude"
        original = {"theme": "dark", "hooks": {}}
        merged = self.installer.merge_hooks(original, command, "claude")
        cleaned = self.installer.remove_hooks(merged)
        self.assertEqual(cleaned, {"theme": "dark"})

    def test_launch_agent_uses_supplied_home(self):
        with tempfile.TemporaryDirectory() as directory:
            app_root = Path(directory) / "Library/Application Support/B9X Agent Status Light"
            value = plistlib.loads(self.installer.launch_agent(app_root))
            self.assertEqual(value["Label"], "com.b9x.agent-status")
            self.assertTrue(value["ProgramArguments"][1].startswith(directory))

    def test_wrapper_refuses_to_replace_unrelated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "b9x-light"
            path.write_text("#!/bin/sh\necho unrelated\n")
            with self.assertRaises(RuntimeError):
                self.installer.write_wrapper(path, Path("/tmp/example"))

    def test_copy_sounds_only_installs_named_alerts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            private = source / "local_sounds"
            private.mkdir(parents=True)
            for name in ("working.wav", "attention.wav", "idle.wav", "reference_16k.wav"):
                (private / name).write_bytes(name.encode())
            app_root = root / "app"
            count = self.installer.copy_sounds(source, app_root)
            self.assertEqual(count, 3)
            self.assertEqual(
                sorted(path.name for path in (app_root / "sounds").glob("*.wav")),
                ["attention.wav", "idle.wav", "working.wav"],
            )


if __name__ == "__main__":
    unittest.main()
