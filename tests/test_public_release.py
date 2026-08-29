#!/usr/bin/python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class PublicReleaseTests(unittest.TestCase):
    def test_private_voice_directory_is_ignored(self):
        self.assertIn("local_sounds/", (ROOT / ".gitignore").read_text().splitlines())

    def test_private_artifacts_are_absent(self):
        self.assertFalse((ROOT / "captures").exists())
        self.assertFalse((ROOT / "work").exists())
        forbidden_suffixes = {".apk", ".db", ".zip"}
        leaked = [path for path in ROOT.rglob("*") if path.is_file() and path.suffix in forbidden_suffixes]
        self.assertEqual(leaked, [])

    def test_no_personal_absolute_paths_or_device_ids(self):
        forbidden = [
            "/" + "Users/",
            "PNM" + "-AN20",
            "com.fdg." + "flashplay.farsee",
        ]
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts or path.name == __file__.split("/")[-1]:
                continue
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            for fragment in forbidden:
                if fragment in text:
                    hits.append((str(path.relative_to(ROOT)), fragment))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
