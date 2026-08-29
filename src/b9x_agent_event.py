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
    error_kind = previous.get("error_kind")
    error_at = previous.get("error_at")
    now = int(time.time())

    if event == "UserPromptSubmit":
        status, latched = "working", False
        error_kind, error_at = None, None
    elif event == "PostToolUseFailure":
        status, latched = "working", False
        detail = "recovering_after_tool_failure"
        error_kind, error_at = None, None
    elif event in {
        "PermissionRequest",
        "StopFailure",
        "PermissionDenied",
        "Elicitation",
    }:
        status, latched = "error", True
        detail = str(payload.get("error") or payload.get("tool_name") or event)
        if event == "StopFailure" and detail == "rate_limit":
            error_kind, error_at = "rate_limit", now
        else:
            error_kind, error_at = None, None
    elif event == "Notification" and payload.get("notification_type") == "permission_prompt":
        status, latched = "error", True
        detail = "permission_prompt"
        error_kind, error_at = None, None
    elif event == "Notification" and payload.get("notification_type") == "idle_prompt":
        if not latched:
            status = "idle"
        detail = "idle_prompt"
    elif event == "Stop":
        if not latched:
            status = "idle"
            error_kind, error_at = None, None
    elif event == "SessionEnd":
        if not latched:
            status = "idle"
            error_kind, error_at = None, None
    else:
        return previous

    current = {
        "provider": provider,
        "session_id": session_id,
        "status": status,
        "latched": latched,
        "event": event,
        "detail": detail,
        "updated_at": now,
    }
    if error_kind:
        current.update({"error_kind": error_kind, "error_at": error_at})
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
