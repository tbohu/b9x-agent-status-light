# Release checklist

- [x] Replace `YOUR_NAME` in the README clone URL.
- [ ] Confirm the MIT license is the intended public license.
- [ ] Create a public GitHub repository named `b9x-agent-status-light`.
- [ ] Push the local `main` branch.
- [ ] Confirm the GitHub Actions macOS job passes.
- [ ] Add repository topics: `flydigi`, `b9x`, `corebluetooth`, `codex`,
      `claude-code`, `macos`, `ble`.
- [ ] Create release `v0.1.0` from the initial commit.
- [ ] Do not upload local captures, bugreports, APKs, or decompiled sources to
      issues or releases.

## Publish commands

Set your real Git author identity first. A GitHub-provided `noreply` email is
fine if you do not want to expose a personal address.

```bash
git config user.name "YOUR_GITHUB_NAME"
git config user.email "YOUR_GITHUB_NOREPLY_EMAIL"
git commit -m "Initial open-source release"
```

If GitHub CLI is installed and authenticated:

```bash
gh repo create b9x-agent-status-light --public --source=. --remote=origin --push
```

Without GitHub CLI, create an empty public repository on github.com, then run:

```bash
git remote add origin https://github.com/tbohu/b9x-agent-status-light.git
git push -u origin main
```
