# Verified B9X RGB protocol

This document describes only the command path verified on a real Flydigi B9X.

## GATT

| Role | UUID | Properties |
|---|---|---|
| Service | `FFE0` | primary service |
| Command | `FFE1` | write with response |
| State | `FFE4` | notify |

## Fixed-color transaction

Each color change performs two `FFE1` writes:

1. a 20-byte configuration packet;
2. the apply packet `51 0B`.

Configuration packet:

```text
offset  0: 50          command
offset  1: 0B          always-on LED mode
offset  2: 00          period
offset  3: 01          enabled
offset  4: 01          color count
offset  5: RR          red
offset  6: GG          green
offset  7: BB          blue
offset  8..16: 00      unused for one-color mode
offset 17: 14          brightness (20)
offset 18: 00          reserved
offset 19: checksum    sum of offsets 0..18 modulo 256
```

Verified payloads:

```text
GREEN  50 0B 00 01 01 00 FF 00 00 00 00 00 00 00 00 00 00 14 00 70
YELLOW 50 0B 00 01 01 FF FF 00 00 00 00 00 00 00 00 00 00 14 00 6F
RED    50 0B 00 01 01 FF 00 00 00 00 00 00 00 00 00 00 00 14 00 70
APPLY  51 0B
```

The CLI does not report success until both writes complete and an `FFE4`
notification matches the requested mode, RGB values, and brightness.

## Scope

This project intentionally does not implement fan control, firmware update,
lighting effects, arbitrary brightness, or unverified commands.
