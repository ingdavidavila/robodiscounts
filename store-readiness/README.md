# storecheck

Checks an app against Google Play and Apple App Store requirements and recommends fixes. **Language-agnostic**: it never parses source code. It reads what the stores inspect (manifests, `Info.plist`, Gradle files, privacy manifests, `.so` libraries, built `.apk`/`.aab`/`.ipa`) and runs text-pattern searches that work in any language or framework (native, Flutter, React Native, Capacitor, Unity, Rust, Go, ...).

Runs on Linux, macOS and Windows. Python 3.9+, standard library only.

```bash
python -m storecheck path/to/project            # or a built .apk / .aab / .ipa
python -m storecheck path --store apple --format json
python -m storecheck path --explain             # advisory notes from a local LLM (Ollama etc.)
```
Exit code is 1 when any blocker is found (usable in CI).

## Privacy label draft
```bash
python -m storecheck path --privacy-draft              # Markdown draft
python -m storecheck path --privacy-draft --format json
python -m storecheck path --privacy-draft --explain    # + local-LLM 'Data we collect' wording ([CONFIRM] on guesses)
```
Maps evidence (known SDKs in dependency files, Android permissions, iOS usage-description keys, sensitive API names) to Google Data safety categories and Apple App Privacy types, flags likely tracking, and lists the questions only you can answer (purposes, sharing, linked to identity, encryption, deletion). SDK-sent data is "likely collected"; permission/API-only evidence is "possible" because the stores only count data that leaves the device. Mappings live in `storecheck/privacy_data.json` and use verified Apple and Google category/type names; the SDK-to-data mappings are not verified.

## Severity
- **blocker**: the store will reject the build
- **likely**: commonly rejected or flagged
- **advisory**: heuristic; confirm by hand

## Rules are data
`storecheck/rules/*.json`. Each rule has a check type and parameters, a fix, a source URL and a `verified` flag. Store thresholds change often (for example the minimum targetSdk), so each rule carries a `verified` date (empty = not verified) and the report shows it. Verified 2026-11-24: Play target API (36), 16 KB page sizes, AAB requirement, Apple privacy-manifest/required-reason enforcement, Apple privacy type names. Also verified: Play account-deletion rule and Data safety names/purposes. Not yet verified: most of the Play restricted-permission list (only SMS and Call Log confirmed), and Apple ATS and export-compliance pages (returned no content), plus the full text of guidelines 4.8/5.1.1 (only a summary was readable). Add your own rules with `--rules-dir`.

## Local LLM
`--explain` sends the findings (not your source code) to any OpenAI-compatible endpoint (default Ollama at `localhost:11434`) for plain-language explanations. It is advisory and never changes findings.

## Known limits
- Cannot guarantee approval; review is human.
- AndroidManifest inside `.apk`/`.aab` is binary XML and is not decoded; scan the source project for manifest checks.
- Signal-based checks (usage strings, Sign in with Apple, account deletion) are text heuristics and can false-positive or miss.
- No server-side, metadata, screenshot, Data safety or privacy policy checks yet; no iOS code-signing validation (needs a Mac).
- `build/`, `node_modules/`, `Pods/` and similar directories are skipped when scanning a folder.

## Tests
```bash
python -m unittest discover -s tests
```
