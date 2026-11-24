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

## Known gaps this did not cover
- Only one native-iOS app, no Unity, Expo-managed or Cordova app, and no app using Xcode-generated Info.plists
  (`INFOPLIST_KEY_*` in `project.pbxproj`), which the checker does not read yet and could report as missing keys.
- No app was checked against an actual store review outcome.
- macOS `Info.plist` files in cross-platform projects are checked with the same iOS rules.
