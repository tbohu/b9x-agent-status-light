#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Aggregate Codex/Claude state and apply the highest-priority B9X color."""

import argparse
import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIGHT_CLI = Path(os.environ.get("B9X_LIGHT_CLI", str(PROJECT_ROOT / "b9x-light")))
STATE_ROOT = Path(
    os.environ.get(
        "B9X_AGENT_STATE_DIR",
        str(Path.home() / "Library/Application Support/B9X Agent Status Light"),
    )
)
CODEX_DB = Path(os.environ.get("B9X_CODEX_DB", str(Path.home() / ".codex/thread_history_1.sqlite")))
MONITOR_STATE = STATE_ROOT / "monitor.json"
CONTROL_STATE = STATE_ROOT / "control.json"
WAKE_STATE = STATE_ROOT / "wake.json"
SOUND_ROOT = Path(os.environ.get("B9X_SOUND_DIR", str(STATE_ROOT / "sounds")))
CLAUDE_PROJECTS = Path(
    os.environ.get("B9X_CLAUDE_PROJECTS", str(Path.home() / ".claude/projects"))
)
PRIORITY = {"idle": 0, "working": 1, "error": 2}
COLOR = {"idle": "green", "working": "yellow", "error": "red"}
SOUND_FILE = {"idle": "idle.wav", "working": "working.wav", "error": "attention.wav"}
RUNNING = True


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default.copy()


def codex_snapshot(known: dict) -> tuple:
    if not CODEX_DB.exists():
        return 0, known, False, False
    try:
        connection = sqlite3.connect(f"file:{CODEX_DB}?mode=ro", uri=True, timeout=1)
        rows = connection.execute(
            "SELECT rowid, status FROM thread_turns ORDER BY rowid DESC LIMIT 200"
        ).fetchall()
        connection.close()
    except sqlite3.Error:
        return 0, known, False, False

    current = {str(rowid): status for rowid, status in rows}
    new_failure = any(
        status == "failed" and known.get(str(rowid)) not in (None, "failed")
        for rowid, status in rows
    )
    new_start = any(status == "inProgress" and str(rowid) not in known for rowid, status in rows)
    active = sum(status == "inProgress" for _, status in rows)
    return active, current, new_failure, new_start


def iso_timestamp(value: object):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def latest_main_assistant(path: Path, session_id: str):
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            start = max(0, size - 1024 * 1024)
            stream.seek(start)
            if start:
                stream.readline()
            lines = stream.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if (
            value.get("type") != "assistant"
            or value.get("sessionId") != session_id
            or value.get("isSidechain")
        ):
            continue
        message = value.get("message")
        if not isinstance(message, dict):
            continue
        timestamp = iso_timestamp(value.get("timestamp"))
        if timestamp is not None:
            return timestamp, message.get("stop_reason")
    return None


def claude_transcript_completed(state: dict) -> bool:
    session_id = str(state.get("session_id") or "")
    configured = state.get("transcript_path")
    if configured:
        candidates = [Path(str(configured)).expanduser()]
    elif session_id and Path(session_id).name == session_id:
        candidates = list(CLAUDE_PROJECTS.glob(f"*/{session_id}.jsonl"))
    else:
        candidates = []
    observations = [
        observation
        for candidate in candidates
        if (observation := latest_main_assistant(candidate, session_id)) is not None
    ]
    if not observations:
        return False
    timestamp, stop_reason = max(observations, key=lambda item: item[0])
    threshold = float(state.get("updated_at") or 0)
    return stop_reason == "end_turn" and timestamp >= threshold


def session_states() -> list:
    states = []
    for path in (STATE_ROOT / "sessions").glob("*.json"):
        value = read_json(path, {})
        if value.get("status") in PRIORITY:
            if (
                value.get("provider") == "claude"
                and value.get("event") == "Stop"
                and value.get("status") == "working"
            ):
                value = dict(value, status="idle", latched=False, detail="Stop")
            if (
                value.get("provider") == "claude"
                and value.get("event") == "PostToolUseFailure"
            ):
                value = dict(
                    value,
                    status="working",
                    latched=False,
                    detail="recovering_after_tool_failure",
                )
            if (
                value.get("provider") == "claude"
                and value.get("status") == "working"
                and claude_transcript_completed(value)
            ):
                value = dict(value, status="idle", detail="transcript:end_turn")
            states.append(value)
    return states


def desired_status(states: list, codex_active: int, db_error: bool) -> tuple:
    candidates = []
    for state in states:
        if state.get("status") == "idle":
            continue
        # Codex's SQLite history is authoritative for working/idle. Hooks add
        # the information SQLite lacks: approval and other human-attention states.
        if state.get("provider") == "codex" and state.get("status") != "error":
            continue
        candidates.append((state["status"], f"{state.get('provider')}:{state.get('detail')}"))
    if codex_active:
        candidates.append(("working", f"codex:{codex_active}_active_turn(s)"))
    if db_error:
        candidates.append(("error", "codex:turn_failed"))
    if not candidates:
        return "idle", ["no active task"]
    level = max(PRIORITY[status] for status, _ in candidates)
    winning = [(status, reason) for status, reason in candidates if PRIORITY[status] == level]
    return winning[0][0], [reason for _, reason in winning]


def play_status_sound(status: str, runtime: dict) -> None:
    path = SOUND_ROOT / SOUND_FILE[status]
    runtime.update({"sound_event": status, "sound_at": int(time.time())})
    if not path.is_file():
        runtime["sound_output"] = f"missing:{path}"
        return
    try:
        process = subprocess.Popen(
            ["/usr/bin/afplay", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        runtime.update({"sound_output": "started", "sound_pid": process.pid})
    except OSError as error:
        runtime["sound_output"] = str(error)


def reconcile(runtime: dict, dry_run: bool = False, force: bool = False) -> dict:
    active, known, new_failure, new_start = codex_snapshot(runtime.get("codex_rows", {}))
    db_error = bool(runtime.get("codex_error_latched", False))
    control = read_json(CONTROL_STATE, {})
    wake_at = read_json(WAKE_STATE, {}).get("updated_at")
    if wake_at != runtime.get("processed_wake_at"):
        force = True
        runtime["processed_wake_at"] = wake_at
    acknowledge_at = control.get("acknowledge_at")
    if acknowledge_at != runtime.get("processed_acknowledge_at"):
        db_error = False
        runtime["processed_acknowledge_at"] = acknowledge_at
    reapply_at = control.get("reapply_at")
    if reapply_at != runtime.get("processed_reapply_at"):
        force = True
        runtime["processed_reapply_at"] = reapply_at
    if new_start:
        db_error = False
    if new_failure:
        db_error = True

    status, reasons = desired_status(session_states(), active, db_error)
    color = COLOR[status]
    previous_color = runtime.get("desired_color")
    previous_status = runtime.get("desired_status")
    quiet = bool(control.get("quiet", False))
    runtime.update(
        {
            "desired_status": status,
            "desired_color": color,
            "reasons": reasons,
            "codex_active_turns": active,
            "codex_rows": known,
            "codex_error_latched": db_error,
            "quiet": quiet,
            "updated_at": int(time.time()),
        }
    )

    if force or color != previous_color or runtime.get("light_output") == "dry-run":
        if dry_run:
            runtime.update({"simulated_color": color, "light_exit": 0, "light_output": "dry-run"})
        else:
            try:
                result = subprocess.run(
                    [str(LIGHT_CLI), color], capture_output=True, text=True, timeout=25
                )
                runtime.update(
                    {
                        "light_exit": result.returncode,
                        "light_output": (result.stdout + result.stderr).strip(),
                        "applied_color": color if result.returncode == 0 else runtime.get("applied_color"),
                        "applied_at": int(time.time()) if result.returncode == 0 else runtime.get("applied_at"),
                    }
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                runtime.update({"light_exit": 70, "light_output": str(error)})
    if previous_status in PRIORITY and status != previous_status:
        if quiet:
            runtime.update(
                {"sound_event": status, "sound_output": "quiet", "sound_at": int(time.time())}
            )
        elif dry_run:
            runtime.update(
                {"sound_event": status, "sound_output": "dry-run", "sound_at": int(time.time())}
            )
        else:
            play_status_sound(status, runtime)
    atomic_json(MONITOR_STATE, runtime)
    return runtime


def acknowledge() -> None:
    with (STATE_ROOT / "state.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path in (STATE_ROOT / "sessions").glob("*.json"):
            state = read_json(path, {})
            if state.get("status") == "error":
                state.update({"status": "idle", "latched": False, "detail": "acknowledged"})
                atomic_json(path, state)
        control = read_json(CONTROL_STATE, {})
        control["acknowledge_at"] = time.time()
        atomic_json(CONTROL_STATE, control)


def request_reapply() -> None:
    control = read_json(CONTROL_STATE, {})
    control["reapply_at"] = time.time()
    atomic_json(CONTROL_STATE, control)


def set_quiet(enabled: bool) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    with (STATE_ROOT / "state.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        control = read_json(CONTROL_STATE, {})
        control["quiet"] = enabled
        atomic_json(CONTROL_STATE, control)
        atomic_json(WAKE_STATE, {"updated_at": time.time()})


def stop_handler(_signum, _frame) -> None:
    global RUNNING
    RUNNING = False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("run", "once", "status", "acknowledge", "reapply", "quiet")
    )
    parser.add_argument("quiet_action", choices=("on", "off", "status"), nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    STATE_ROOT.mkdir(parents=True, exist_ok=True)

    if args.command == "status":
        runtime = read_json(MONITOR_STATE, {})
        runtime["quiet"] = bool(read_json(CONTROL_STATE, {}).get("quiet", False))
        fields = (
            "desired_status", "desired_color", "applied_color", "light_exit",
            "light_output", "reasons", "codex_active_turns", "quiet",
            "sound_event", "sound_output", "sound_at", "updated_at",
        )
        print(json.dumps({key: runtime.get(key) for key in fields}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "acknowledge":
        acknowledge()
        print("ATTENTION_ACKNOWLEDGED")
        return 0
    if args.command == "quiet":
        if args.quiet_action in (None, "status"):
            enabled = bool(read_json(CONTROL_STATE, {}).get("quiet", False))
            print(f"QUIET={'ON' if enabled else 'OFF'}")
        else:
            set_quiet(args.quiet_action == "on")
            print(f"QUIET={args.quiet_action.upper()}")
        return 0

    runtime = read_json(MONITOR_STATE, {})
    if args.command == "reapply":
        request_reapply()
        print("REAPPLY_REQUESTED")
        return 0
    if args.command == "once":
        reconcile(runtime, args.dry_run)
        return 0

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    while RUNNING:
        runtime = reconcile(runtime, args.dry_run)
        time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
