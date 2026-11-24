# Desktop-only plan (Linux, macOS, Windows)

Incorporates lessons from the VoxVerba project (an offline audio transcriber). Caveat from that team: they had **not** shipped a Windows installer, signed anything, or run GPU/CUDA/DirectML. Items marked "expected" are from docs, not executed.

## Stack
- **UI:** one Flutter desktop codebase (or Tauri 2 for a web UI).
- **Engine:** a native core behind a **C ABI** called through `dart:ffi`.
  - Prefer **C++ or Rust** for the core. VoxVerba's Swift engine built on Mac and Ubuntu, but not natively on Windows (it needed WSL2). Swift on Windows needs MSVC + Windows SDK and was not attempted.
  - Version the ABI and check symbol/version equality in CI, since a stale native library gives "undefined symbol".
- **Rejected by VoxVerba:** per-platform engine rewrites (parity drift), Electron/web for native audio, per-OS UIs.

## Hurdles and fixes
| Hurdle | Fix |
|---|---|
| Golden image tests differ per OS (fonts); 13 failed on Windows | Per-OS goldens, or run goldens on one pinned OS |
| Date-dependent fixtures expired | Inject a clock; pin dates |
| CI covered only macOS | Three-OS CI matrix before feature work |
| Linux packages need root | Container/VM with root (`wsl -u root`), no sudo prompts |
| Flutter on Windows needs symlinks | User enables Developer Mode once (never change system settings automatically) |
| Git Bash rewrites `/paths` | `MSYS_NO_PATHCONV=1`, or use PowerShell/WSL scripts |
| Windows PATH leaks into WSL bash | Use script files with an explicit PATH |
| rsync from Windows drops exec bits | Call scripts with `bash script.sh` |
| FFmpeg has no easy MSVC build | Use Media Foundation on Windows, AVFoundation on macOS, FFmpeg on Linux (or solve the MSVC build early) |
| Linux link flags (`-lstdc++`, `-lgomp`); glibc vs musl static builds differ | Capture flags in the build script; pick glibc dynamic first |
| Flutter CLI regenerates other platforms' plugin registrants | Revert with `git checkout` in the build script |
| Model files are large; a loaded model costs ~3x its file size in RAM | Decide bundling vs download, and RAM budget, before any UI |
| App couldn't find its model (looked relative to cwd) | The host passes an explicit data directory; never guess from cwd |
| A global setting that latches on first read caused startup failures | Inject configuration; avoid latching globals |
| Failed jobs showed an empty result and hid the real error | Test failure paths; surface engine error text |

## Steps
1. Decide the data/model location and delivery design first (bundle vs download; this affects offline/privacy claims).
2. Pick the stack above; define the C ABI and version it.
3. Bootstrap scripts per OS with pinned toolchains (Flutter, compiler, CMake).
4. Three-OS CI matrix (ubuntu, windows, macos): build, unit tests, UI tests, ABI check.
5. Agent rules file: build and test after every change, no sudo prompts, never blindly regenerate goldens, pin dates and versions.
6. Hello-world green on all three OSes.
7. Features in small commits, CI-gated.
8. Package: Windows MSIX/Inno Setup, macOS signed and notarized DMG, Linux AppImage (deb/rpm later).
9. Sign: Windows code-signing cert (SmartScreen), Apple Developer ID (notarization, hardened runtime, mic permission strings, arm64 + x86_64 slices). Linux needs none.
10. Test on real machines: audio capture (PulseAudio/PipeWire on Linux), permissions, GPU drivers.

## Local LLM setup
Ollama (or llama.cpp / LM Studio) running a Qwen-Coder class 14B-32B model, driven by Aider, Cline or OpenHands. Needs ~16-24 GB VRAM, or a 32 GB+ Mac. A Mac is mandatory for macOS signing and notarization.
