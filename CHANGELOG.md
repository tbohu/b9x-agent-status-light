# Changelog

## 0.1.2 - 2026-08-28

- Recover Claude Code completion when a background task ends without a final
  lifecycle hook by checking the matching local transcript's latest main-agent
  stop reason.
- Reject stale, sidechain, mismatched-session, and pre-prompt completion data.

## 0.1.1 - 2026-08-28

- Reapply the current B9X color when a new agent lifecycle event arrives, even
  when the aggregate status did not change.
- Prevent a powered-on or reconnected B9X from remaining green while Claude
  Code is already working.

## 0.1.0 - 2026-08-27

- Add verified B9X fixed-color control over CoreBluetooth.
- Add green, yellow, red, status, and scan commands.
- Add Codex and Claude Code lifecycle integration.
- Add red-over-yellow-over-green aggregation and error latching.
- Add safe hook merge, per-user LaunchAgent, and uninstall support.
- Add protocol, architecture, privacy, safety, and contribution documentation.
- Add macOS GitHub Actions validation.
