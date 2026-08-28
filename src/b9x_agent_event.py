#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Record one Codex or Claude Code lifecycle event for the B9X monitor."""

import argparse
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path


STATE_ROOT = Path(
    os.environ.get(
        "B9X_AGENT_STATE_DIR",
        str(Path.home() / "Library/Application Support/B9X Agent Status Light"),
    )
)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def state_path(provider: str, session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode()).hexdigest()[:24]
    return STATE_ROOT / "sessions" / f"{provider}-{digest}.json"


def update_state(provider: str, payload: dict) -> dict:
    event = payload.get("hook_event_name", "")
    session_id = str(payload.get("session_id") or payload.get("thread_id") or "unknown")
    path = state_path(provider, session_id)
    try:
        previous = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        previous = {"status": "idle", "latched": False}

    status = previous.get("status", "idle")
    latched = bool(previous.get("latched", False))
    detail = event

    if event == "UserPromptSubmit":
        status, latched = "working", False
    elif event in {
        "PermissionRequest",
        "PostToolUseFailure",
        "StopFailure",
        "PermissionDenied",
        "Elicitation",
    }:
        status, latched = "error", True
        detail = str(payload.get("error") or payload.get("tool_name") or event)
    elif event == "Notification" and payload.get("notification_type") in {
        "permission_prompt",
        "idle_prompt",
    }:
        status, latched = "error", True
        detail = str(payload.get("notification_type"))
    elif event == "Stop":
        if not latched:
            status = "working" if payload.get("background_tasks") else "idle"
    elif event == "SessionEnd":
        if not latched:
            status = "idle"
    else:
        return previous

    current = {
        "provider": provider,
        "session_id": session_id,
        "status": status,
        "latched": latched,
        "event": event,
        "detail": detail,
        "updated_at": int(time.time()),
    }
    transcript_path = payload.get("transcript_path") or previous.get("transcript_path")
    if transcript_path:
        current["transcript_path"] = str(transcript_path)
    atomic_json(path, current)
    atomic_json(STATE_ROOT / "wake.json", {"updated_at": time.time()})
    return current


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("codex", "claude"))
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as error:
        print(f"invalid hook JSON: {error}", file=sys.stderr)
        return 2

    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    with (STATE_ROOT / "state.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        update_state(args.provider, payload)
    # Hook stdout must stay empty so it never injects context or changes execution.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
