# Stable Installer Implementation Plan

> **For agentic workers:** Implement inline in this task. The user approved a fixed install directory and replacement of the desktop shortcut.

**Goal:** Replace manual ZIP extraction with a repeatable Windows installer while preserving the independent data directory.

**Architecture:** Keep the current PyInstaller directory and ZIP for the app updater. Add a per-user Inno Setup installer over the same directory, built and published by the Windows release workflow. Reject connection to an already-running different-version local server.

**Tech Stack:** Python, PyInstaller, Inno Setup, GitHub Actions.

---

- [ ] Add the installer script with fixed AppId, target directory, desktop shortcut and application-close behavior.
- [ ] Build installer after the existing frozen bundle; publish its SHA256 alongside the ZIP artifacts.
- [ ] Add and test a different-version running-instance guard.
- [ ] Update version and user guidance, run business and package checks.
- [ ] Publish a new version and verify its assets if GitHub access permits.
