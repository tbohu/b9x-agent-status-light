# Security policy

## Supported scope

The project sends only the documented fixed-color command to a Flydigi B9X.
Firmware update, fan control, and unknown BLE commands are out of scope.

## Data handling

All processing is local. Hook input arrives through stdin. The event recorder
does not persist prompt text, tool arguments, or command output. It stores only
minimal status metadata and Claude's transcript path under the user's
Application Support directory. To recover a missed completion hook, the
monitor reads a bounded tail of that local transcript and retains only the
latest matching main-agent timestamp and stop reason in memory.

The installer backs up Codex and Claude Code configuration before merging its
own hook entries. It does not change approval decisions or permissions.

## Reporting a vulnerability

Please open a GitHub Security Advisory instead of a public issue when a report
contains sensitive details. Include the affected version, reproduction steps,
and expected impact.
