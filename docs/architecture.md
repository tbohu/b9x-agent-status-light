# Architecture

```text
Codex local history (read-only) ─┐
Codex lifecycle hooks ───────────┤
                                 ├─ state files ─ monitor ─ b9x-light ─ BLE ─ B9X
Claude hooks + transcript tail ──┘                red > yellow > green
```

## Components

- `src/b9x_light.swift` — native CoreBluetooth scan, GATT validation, RGB write,
  and FFE4 acknowledgement validation.
- `src/b9x_agent_event.py` — receives hook JSON on stdin and records only the
  provider, session ID, transcript path, event, status, and a short
  error/event label.
- `src/b9x_agent_monitor.py` — reads session states and Codex's local turn
  database, checks the tail of active Claude transcripts for a missed
  `end_turn`, calculates the aggregate state, and invokes the BLE controller.
- `src/install.py` — compiles and installs the runtime, merges hook settings,
  and creates the user LaunchAgent.

## State rules

| Event/state | Result |
|---|---|
| Any latched error or attention request | red |
| Otherwise, one or more active turns | yellow |
| Otherwise | green |

Red is latched across `Stop`. It is cleared by a new prompt for that session or
by `b9x-agent-status acknowledge`.

A Claude `PostToolUseFailure` is recoverable and stays yellow while Claude
continues. A terminal `StopFailure`, permission request, or elicitation remains
red because the turn ended or human attention is required.

Codex SQLite is authoritative for Codex working/idle state. Hook state adds the
approval information absent from SQLite. Historical failed turns present at
first monitor startup are ignored; only a newly observed transition to
`failed` is latched.

Claude hooks are authoritative for task start and attention states. For a
working session only, a matching main-agent `end_turn` at or after the recorded
start/stop event clears stale working state. Older turns, sidechains, and other
session IDs are ignored.

At Claude `Stop`, background shell processes are not Agent activity: a server
may intentionally outlive the turn. Subagents, workflows, teammates, monitors,
and unrecognized background task types continue to count as working.

## Failure behavior

The BLE CLI returns non-zero for discovery, permission, connection, GATT,
notification, write, timeout, and disconnect errors. The monitor records that
result and waits for a state change or explicit `reapply`; it does not retry in
an infinite loop.
