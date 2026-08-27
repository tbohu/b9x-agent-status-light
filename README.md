# B9X Agent Status Light

Turn a Flydigi B9X magnetic phone cooler into a physical status light for
Codex and Claude Code on macOS.

把飞智 B9X 磁吸散热器变成 Codex / Claude Code 的桌面状态灯：

- 🟡 Yellow / 黄灯 — at least one agent task is running
- 🔴 Red / 红灯 — an agent failed or needs human attention
- 🟢 Green / 绿灯 — every task is complete or idle

Status priority is **red > yellow > green**. Error states are latched so a
later stop event cannot immediately hide a failure.

> This is an independent community project. It is not affiliated with or
> endorsed by Flydigi, OpenAI, or Anthropic.

## What is verified

The following were verified on a real Flydigi B9X and an Apple Silicon Mac:

- BLE discovery through service `FFE0`
- color writes to characteristic `FFE1`
- state acknowledgement from characteristic `FFE4`
- green → yellow → red → green, three complete visual cycles
- independent Mac control with the Android app inactive
- powered-off device returns an explicit non-zero error
- automatic Codex working → yellow
- synthetic agent failure → red, then acknowledgement → yellow

Tested host: Apple Silicon, macOS 26.6.1. Older macOS releases and Intel Macs
are currently unverified.

## Requirements

- macOS with Bluetooth enabled
- Flydigi B9X powered on and not controlled by the phone app
- Apple Command Line Tools (`swiftc`)
- system Python 3
- Codex and/or Claude Code for automatic status integration

No Homebrew package or Python package is required.

## Install

```bash
git clone https://github.com/tbohu/b9x-agent-status-light.git
cd b9x-agent-status-light
./install.sh
```

The installer:

1. compiles the Swift CoreBluetooth controller locally;
2. installs runtime files under `~/Library/Application Support/`;
3. installs `b9x-light` and `b9x-agent-status` in `~/.local/bin`;
4. merges, rather than replaces, existing Codex and Claude Code hooks;
5. saves configuration backups;
6. starts a per-user macOS LaunchAgent.

If `~/.local/bin` is not on your `PATH`, add it to your shell configuration.

Codex requires new hooks to be reviewed before they run. Start Codex, enter
`/hooks`, inspect the B9X commands, then trust them. This is the official Codex
hook security flow. See the official [Codex Hooks documentation](https://developers.openai.com/codex/hooks).

## Use

Direct B9X control:

```bash
b9x-light scan
b9x-light status
b9x-light green
b9x-light yellow
b9x-light red
```

Agent status service:

```bash
b9x-agent-status status
b9x-agent-status acknowledge
b9x-agent-status reapply
```

- `acknowledge` clears latched red states.
- `reapply` performs one explicit retry after the B9X is powered back on.
- The monitor writes only when the desired color changes. It does not loop on
  BLE reconnects.

## How it works

Codex working/completed/failed turns are observed from its local SQLite history
in read-only mode. Codex hooks add immediate approval-needed events. Claude
Code uses lifecycle hooks for prompt start, stop, failures, permissions, and
elicitation. A local LaunchAgent aggregates all sessions and calls the verified
BLE CLI only when the aggregate color changes.

See [architecture](docs/architecture.md) and the
[verified B9X protocol](docs/protocol.md).

## Current limitation

This Codex Desktop build exposes arbitrary `waitingOnUserInput` only through an
in-memory app-server flag. Its Desktop-owned app-server does not expose a
read-only control socket, and the current Codex hook set has no equivalent
event. Therefore approval requests and failed turns become red, but an
arbitrary mid-turn question may remain yellow until the turn resolves.

Claude Code permission, elicitation, tool-failure, and API-failure states are
covered by its hooks. See the official [Claude Code Hooks reference](https://code.claude.com/docs/en/hooks).

## Privacy and safety

- No network request is made by this project.
- Hook payloads stay local; prompts and tool inputs are not stored.
- The Codex database is opened read-only.
- Only the verified RGB command is sent to the B9X.
- The project does not control fan speed or firmware.
- APKs, phone bugreports, HCI captures, and device identifiers are not included.

See [SECURITY.md](SECURITY.md).

## Development

```bash
/usr/bin/python3 -m unittest discover -s tests -v
swiftc src/b9x_light.swift -o /tmp/b9x-light
```

## Uninstall

```bash
./uninstall.sh
```

The uninstaller removes only this project's hook handlers, wrappers,
LaunchAgent, runtime, and state. Other Codex/Claude settings are preserved.

## License

MIT. See [LICENSE](LICENSE).
