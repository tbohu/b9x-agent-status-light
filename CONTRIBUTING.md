# Contributing

Contributions are welcome when they stay within the project's safety boundary.

Before opening a pull request:

1. Do not commit APKs, decompiled application code, captures, bugreports,
   Bluetooth addresses, account data, or device serials.
2. Do not add firmware, fan-control, or guessed BLE commands.
3. Add evidence for protocol changes and label unverified observations clearly.
4. Run the Python tests and compile the Swift controller.
5. Preserve existing user hook configuration in installer changes.

```bash
/usr/bin/python3 -m unittest discover -s tests -v
swiftc src/b9x_light.swift -o /tmp/b9x-light
```
