# Local App Builder

Plan for a local LLM setup that prepares an app for Android, iOS, Linux, Windows and macOS.

The model is the smallest part. You need an open coding model running locally, an agent loop around it, and real build toolchains. Don't train a model.

## 1. Model
Run an existing open-weights coding model (Qwen-Coder, DeepSeek-Coder or Codestral class) through **Ollama**, **llama.cpp** or **LM Studio**.
- A 14B-32B model at 4-bit quantization needs about 16-24 GB of VRAM, or a Mac with 32 GB+ unified memory.
- 7B models can write snippets but fail at multi-file, multi-platform work.

## 2. Agent layer
A bare LLM only produces text. Wrap it in an agent that can read and edit files, run shell commands and read build errors: **Aider**, **OpenHands** or **Cline**, pointed at the local Ollama endpoint.
Loop: plan, edit, build, read the error, fix, repeat.

## 3. One codebase, not five

| Framework | Android | iOS | Windows | macOS | Linux |
|---|---|---|---|---|---|
| **Flutter** | yes | yes | yes | yes | yes |
| **Kotlin Multiplatform + Compose** | yes | yes | yes | yes | yes |
| **.NET MAUI** | yes | yes | yes | yes | no |
| **React Native + desktop** | yes | yes | yes | yes | partial |
| **Tauri 2** (web UI) | yes | yes | yes | yes | yes |

Recommended: **Flutter** or **Tauri 2**.

## 4. Build machines
- **Android:** Android SDK (runs on Linux).
- **Linux / Windows:** containers or VMs.
- **iOS / macOS:** require Xcode on Apple hardware (Mac mini, or macOS runners on GitHub Actions / Codemagic).
- Use a CI matrix (Linux, Windows, macOS). The agent edits code, CI reports results.

## 5. What the AI can't do alone
- Apple Developer account ($99/year), signing certificates, provisioning profiles
- Google Play / App Store submission, Windows code signing
- Testing on real devices

Set these up once; the agent can then drive builds and signing via scripts like `fastlane`.

## 6. Workflow
1. Give it an app idea or an existing repo.
2. It scaffolds or ports to the chosen framework.
3. It runs `flutter build apk/ios/windows/macos/linux` (or the Tauri equivalent), reads errors, fixes them.
4. It pushes to CI and checks all five targets.
5. It produces installers: APK/AAB, IPA, MSI, DMG, AppImage/deb.

## Start small
Get Ollama + Aider building a Flutter hello-world for Android and Linux locally. Then add the CI matrix for Windows, macOS and iOS.
