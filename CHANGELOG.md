# Changelog

## 0.2.1 - 2026-08-29

- Keep Claude `rate_limit` failures red for five minutes, then remove that
  expired error from status aggregation.
- Continue latching all other terminal failures and human-attention states.

## 0.2.0 - 2026-08-29

- Add optional local voice alerts for working, attention, and idle transitions.
- Add persistent `quiet on`, `quiet off`, and `quiet status` commands.
- Keep playback failures independent from B9X light updates.
- Keep reference and generated voice audio outside the public repository.

## 0.1.5 - 2026-08-29

- Simplify Claude state: `UserPromptSubmit` is working and `Stop` or
  `SessionEnd` is idle, regardless of background helper processes.
- Treat `idle_prompt` as idle instead of human attention.
- Normalize working Stop states written by older versions.

## 0.1.4 - 2026-08-28

- Treat a recoverable Claude `PostToolUseFailure` as continued work instead of
  a permanently latched red error.
- Preserve red for terminal `StopFailure` events and states that need human
  permission or input.
- Normalize red states written by older versions for recoverable tool failures.

## 0.1.3 - 2026-08-28

- Stop treating a long-running background shell, such as a development server,
  as continued Agent execution after Claude reaches `end_turn`.
- Continue treating subagents, workflows, teammates, monitors, and unknown
  background task types as active work.
- Clear legacy Stop states when the matching main-agent `end_turn` occurred
  within five seconds before the hook.

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
