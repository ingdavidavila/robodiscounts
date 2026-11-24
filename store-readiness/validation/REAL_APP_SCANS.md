# Real-app scans (2026-11-24)

Eight public open-source mobile apps, shallow-cloned at the commits below and scanned with storecheck.
Every finding (and every silence) was checked by hand against the source. "Ground truth" here is my own
reading of the code, not a store decision: none of these apps were submitted, and the Play/App Store outcome is unknown.

| App | Stack | Commit | Final result |
|---|---|---|---|
| android/nowinandroid | Kotlin, Compose | 2982e63cb6 | clean; targetSdk 36 found in Kotlin build-logic |
| TeamNewPipe/NewPipe | Kotlin Multiplatform + iosApp | 2f295de282 | **blocker** targetSdk 35 (true, constant in buildSrc); no privacy manifest (true) |
| tuskyapp/Tusky | Kotlin | 43ae0bb455 | clean; targetSdk 36 |
| wikimedia/wikipedia-ios | Swift/ObjC | 4969cba667 | clean (has privacy manifest, usage strings, export key) |
| mattermost/mattermost-mobile | React Native | 786e122899 | ATS opt-out (true), cleartext allowed (true) |
| localsend/localsend | Flutter | 44f48f18a5 | QUERY_ALL_PACKAGES, REQUEST_INSTALL_PACKAGES, cleartext, no privacy manifest (all true) |
| ionic-team/ionic-conference-app | Ionic/Capacitor | 55eaea28f2 | no privacy manifest, no export key, sign-up without deletion (all true) |
| flutter/gallery | Flutter | d12640d4b0 | no privacy manifest, no export key (true); targetSdk inherited from Flutter (reported as undeterminable) |

## What the first scan got wrong, and the fix

| # | Problem | Kind | Fix |
|---|---|---|---|
| 1 | Camera/location "use" found in a unit-test mock (Wikipedia) | false positive | text signals skip test/mock paths |
| 2 | Export-compliance flagged on a framework's Info.plist (Wikipedia) | false positive | plists with `CFBundlePackageType` FMWK/BNDL are not apps |
| 3 | "Camera use" from `image_picker` in `pubspec.lock` (LocalSend) | false positive | lockfiles don't trigger requirement checks; `image_picker` alone is not camera use |
| 4 | Sign-up code found in `README.md` (Mattermost, ionic) | false positive | docs are not scanned |
| 5 | `'signup'` in a reserved-words list counted as account creation (Mattermost) | false positive | pattern requires a call-like form (`signUp(`, `createUser(`, ...) |
| 6 | targetSdk in `variables.gradle` / Kotlin build-logic / root `build.gradle` ext never read, so the rule passed silently | silent miss | read those files; skip only library modules |
| 7 | `targetSdk { version = release(CONST) }` block syntax (NewPipe) not parsed | silent miss | parse the block and resolve constants |
| 8 | Silent pass when targetSdk could not be found at all | silent miss | new advisory `play.target_sdk_unknown`; reports now list checks that ran clean |
| 9 | `pubspec.yaml` treated as a test file (name ends in "spec") | self-inflicted bug found by tests | stricter test-file pattern |

Each fix has a regression test (`tests/test_storecheck.py`, `RealWorldRegressions`).

## Correction to round one
Wikipedia iOS showed "clean" in round one. That was an accidental silent pass: its app plist is named
`Wikipedia-Info.plist`, which discovery never looked at, so every plist rule was skipped. NewPipe's iOS plist
rules were skipped the same way (its real plist has only one non-standard key). Both are fixed in round two.

## Round two: generated and framework-managed config (2026-11-24)

Stacks the first round had not touched: Xcode-generated plists, Expo, Unity, Cordova. Same method: every finding and
every silence checked against the source.

| App | Stack | Commit | Final result |
|---|---|---|---|
| Dimillian/IceCubesApp | SwiftUI, generated plists | 98098b9c4b | no privacy manifest (true) |
| mastodon/mastodon-ios | Swift, localized usage strings | f3dc8d37ad | no privacy manifest (true) |
| bluesky-social/social-app | Expo (`app.config.js`) | b4a2740871 | clean: targetSdk 36, privacy manifests, usage strings all found in config |
| obytes/react-native-template-obytes | Expo template (`app.config.ts`) | fd9b358ed1 | privacy manifest not configured, targetSdk undeterminable (both true) |
| Unity-Technologies/arfoundation-samples | Unity | 16489599d1 | export key missing, no privacy manifest, `AndroidTargetSdkVersion: 0` reported as undeterminable (all true) |
| phonegap/phonegap-app-developer | Cordova | 0ae5e3daf3 | export key missing, no privacy manifest, targetSdk undeterminable (all true) |
| apache/cordova-app-harness, cordova-app-hello-world | Cordova templates | 3b3c7d3359, 257a2e6b32 | no platforms configured in the repo, so nothing to check |

| # | Problem | Kind | Fix |
|---|---|---|---|
| 10 | Mastodon: "photo library use, no `NSPhotoLibraryUsageDescription`" for code that only *saves* photos | false positive | add-only access needs `NSPhotoLibraryAddUsageDescription`; either key satisfies the check |
| 11 | Mastodon: camera key exists only in localized `InfoPlist.strings` | false positive | keys in `InfoPlist.strings` (UTF-16 or UTF-8) count |
| 12 | IceCubes: real `Info.plist` has no `CFBundleIdentifier` (build setting supplies it), so it was discarded | silent miss | any non-extension, non-framework, non-test plist counts; Firebase config files excluded |
| 13 | Wikipedia: `Wikipedia-Info.plist`-style names never discovered | silent miss | match `*Info*.plist` names |
| 14 | Wikipedia: ATS finding from `Local-Info.plist`, a local dev variant | false positive | Local/Debug/Dev plists ignored when a release plist exists, with a note |
| 15 | Unity `AndroidTargetSdkVersion: 0` (automatic) passed silently | silent miss | reported as undeterminable |
| 16 | No Info.plist at all in an iOS project made every plist rule skip without saying so | silent miss | note: "checks were skipped" |

New support, each with tests: Xcode `INFOPLIST_KEY_*` and `MARKETING_VERSION` (project.pbxproj/xcconfig), Expo
`app.json` / `app.config.*` (read as text, never executed), Unity `ProjectSettings.asset`, Cordova `config.xml`.
Findings that rely on a plist inferred from config are reported as "likely", not "blocker".

## Known gaps this did not cover
- 14 apps in total, but still only a handful per stack; no Godot, Kotlin/Native-only, NativeScript or MAUI app.
- Expo plugin option names, Unity field names and Cordova plugin variable names are from memory of those tools'
  docs and are not verified. Expo plugin-added Android permissions are not modeled.
- `INFOPLIST_KEY_*` and `MARKETING_VERSION` from all targets are merged, so an extension's keys can hide a missing
  key in the main app.
- No app was checked against an actual store review outcome.
- macOS `Info.plist` files in cross-platform projects are checked with the same iOS rules.
