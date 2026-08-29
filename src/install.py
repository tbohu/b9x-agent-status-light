#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Install or uninstall B9X Agent Status Light without external dependencies."""

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path


APP_NAME = "B9X Agent Status Light"
LABEL = "com.b9x.agent-status"
MARKER = "b9x_agent_event.py"
CODEX_EVENTS = ("UserPromptSubmit", "PermissionRequest", "Stop", "SessionEnd")
CLAUDE_EVENTS = (
    "UserPromptSubmit", "PermissionRequest", "PostToolUseFailure", "StopFailure",
    "Elicitation", "Stop", "SessionEnd",
)
SOUND_NAMES = ("working.wav", "attention.wav", "idle.wav")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def atomic_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path: Path, value: dict) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def backup(path: Path, backup_dir: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_dir / f"{path.parent.name}-{path.name}-{stamp}")


def remove_our_handlers(groups: list) -> list:
    cleaned = []
    for group in groups:
        if not isinstance(group, dict):
            cleaned.append(group)
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            cleaned.append(group)
            continue
        remaining = [
            handler for handler in handlers
            if MARKER not in str(handler.get("command", ""))
        ]
        if remaining:
            copy = dict(group)
            copy["hooks"] = remaining
            cleaned.append(copy)
    return cleaned


def merge_hooks(settings: dict, command: str, provider: str) -> dict:
    result = dict(settings)
    hooks = dict(result.get("hooks") or {})
    events = CODEX_EVENTS if provider == "codex" else CLAUDE_EVENTS
    for event in events:
        groups = remove_our_handlers(list(hooks.get(event) or []))
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 3}]})
        hooks[event] = groups
    if provider == "claude":
        groups = remove_our_handlers(list(hooks.get("Notification") or []))
        groups.append({
            "matcher": "permission_prompt|idle_prompt",
            "hooks": [{"type": "command", "command": command, "timeout": 3}],
        })
        hooks["Notification"] = groups
    result["hooks"] = hooks
    return result


def remove_hooks(settings: dict) -> dict:
    result = dict(settings)
    hooks = dict(result.get("hooks") or {})
    for event, groups in list(hooks.items()):
        remaining = remove_our_handlers(list(groups or []))
        if remaining:
            hooks[event] = remaining
        else:
            hooks.pop(event, None)
    if hooks:
        result["hooks"] = hooks
    else:
        result.pop("hooks", None)
    return result


def hook_command(event_script: Path, provider: str) -> str:
    escaped = str(event_script).replace("'", "'\\''")
    return f"/usr/bin/python3 '{escaped}' {provider}"


def launch_agent(app_root: Path) -> bytes:
    payload = {
        "Label": LABEL,
        "ProgramArguments": [
            "/usr/bin/python3", str(app_root / "src/b9x_agent_monitor.py"), "run",
        ],
        "WorkingDirectory": str(app_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(app_root / "monitor.stdout.log"),
        "StandardErrorPath": str(app_root / "monitor.stderr.log"),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False)


def write_wrapper(path: Path, target: Path, python: bool = False) -> None:
    if path.exists() and f"# {APP_NAME}" not in path.read_text(errors="ignore"):
        raise RuntimeError(f"refusing to replace unrelated executable: {path}")
    escaped = str(target).replace("'", "'\\''")
    prefix = "/usr/bin/python3 " if python else ""
    content = f"#!/bin/sh\n# {APP_NAME}\nexec {prefix}'{escaped}' \"$@\"\n"
    atomic_bytes(path, content.encode(), 0o755)


def copy_sounds(source_root: Path, app_root: Path) -> int:
    source = source_root / "local_sounds"
    destination = app_root / "sounds"
    copied = 0
    for name in SOUND_NAMES:
        path = source / name
        if path.is_file():
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination / name)
            copied += 1
    return copied


def launchctl(action: str, plist: Path) -> None:
    domain = f"gui/{os.getuid()}"
    if action == "stop":
        subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
        except subprocess.CalledProcessError:
            time.sleep(1)
            subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
        subprocess.run(["launchctl", "enable", f"{domain}/{LABEL}"], check=True)


def install(home: Path, source_root: Path, no_launch: bool) -> None:
    if os.uname().sysname != "Darwin":
        raise RuntimeError("B9X BLE control currently supports macOS only")
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise RuntimeError("swiftc was not found; install Apple Command Line Tools")

    app_root = home / "Library/Application Support" / APP_NAME
    source_dir = app_root / "src"
    bin_dir = home / ".local/bin"
    plist = home / "Library/LaunchAgents" / f"{LABEL}.plist"
    codex_hooks = home / ".codex/hooks.json"
    claude_settings = home / ".claude/settings.json"
    backup_dir = app_root / "backups"
    source_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)

    binary = app_root / "b9x-light"
    subprocess.run([
        swiftc, str(source_root / "src/b9x_light.swift"), "-o", str(binary),
    ], check=True)
    for name in ("b9x_agent_event.py", "b9x_agent_monitor.py"):
        shutil.copy2(source_root / "src" / name, source_dir / name)
        os.chmod(source_dir / name, 0o755)
    sounds_installed = copy_sounds(source_root, app_root)

    backup(codex_hooks, backup_dir)
    backup(claude_settings, backup_dir)
    event_script = source_dir / "b9x_agent_event.py"
    atomic_json(codex_hooks, merge_hooks(
        read_json(codex_hooks), hook_command(event_script, "codex"), "codex"
    ))
    atomic_json(claude_settings, merge_hooks(
        read_json(claude_settings), hook_command(event_script, "claude"), "claude"
    ))

    write_wrapper(bin_dir / "b9x-light", binary)
    write_wrapper(bin_dir / "b9x-agent-status", source_dir / "b9x_agent_monitor.py", python=True)
    atomic_bytes(plist, launch_agent(app_root))

    if not no_launch and home == Path.home():
        launchctl("stop", plist)
        time.sleep(1)
        launchctl("start", plist)
    print(f"INSTALLED={app_root}")
    print(f"CLI_DIR={bin_dir}")
    print(f"SOUNDS_INSTALLED={sounds_installed}")
    print("CODEX_HOOK_REVIEW_REQUIRED=use /hooks in Codex")


def uninstall(home: Path, no_launch: bool) -> None:
    app_root = home / "Library/Application Support" / APP_NAME
    plist = home / "Library/LaunchAgents" / f"{LABEL}.plist"
    if not no_launch and home == Path.home():
        launchctl("stop", plist)
    for path in (home / ".codex/hooks.json", home / ".claude/settings.json"):
        if path.exists():
            atomic_json(path, remove_hooks(read_json(path)))
    for path in (home / ".local/bin/b9x-light", home / ".local/bin/b9x-agent-status"):
        if path.exists() and f"# {APP_NAME}" in path.read_text(errors="ignore"):
            path.unlink()
    if plist.exists():
        plist.unlink()
    if app_root.exists():
        shutil.rmtree(app_root)
    print("UNINSTALLED=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "uninstall"), nargs="?", default="install")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--no-launch", action="store_true")
    args = parser.parse_args()
    if args.action == "install":
        install(args.home.resolve(), args.source_root.resolve(), args.no_launch)
    else:
        uninstall(args.home.resolve(), args.no_launch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
