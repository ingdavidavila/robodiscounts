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

## Verifying the SDK-to-data mappings (2026-11-25)

Read each vendor's own disclosure page (Firebase, AdMob, Sentry, Facebook, Adjust, Mixpanel, OneSignal, RevenueCat; the
Facebook post is from 2022). Not read: Stripe (pages need JavaScript), AppsFlyer (HTTP 403 to automated fetching), Branch,
Amplitude, Segment, PostHog, Google/Apple sign-in. Those stay marked unverified.

Corrections the vendor pages forced:

| Mapping | Was | Now |
|---|---|---|
| Adjust | "advertising data" | Adjust says it does NOT collect advertising data, location or diagnostics |
| AppsFlyer + Adjust + Branch | one group | split; only Adjust verified |
| Firebase Analytics | interactions, device ID | also coarse location (masked IP), in-app purchase events, advertising ID |
| AdMob | no crash logs | Apple's page lists crash logs |
| Firebase Auth | email, user ID | also name and phone (only depending on use) and IP address |
| Mixpanel | interactions, device ID | also user ID and coarse location (city, region, country by default) |
| OneSignal | device ID | Apple: identifier yes; Google: device IDs not collected by default (store-specific now) |
| RevenueCat | purchases, user ID | user ID and device ID only depending on use; no location or diagnostics |
| Sentry | analytics + app functionality purposes | App functionality only (its published manifest example) |

Two more problems found by running the draft on Mattermost:

| # | Problem | Fix |
|---|---|---|
| 17 | `firebase_analytics_collection_deactivated = true` in the manifest still produced "likely collected" | collection-disabled flags (Firebase Analytics, Crashlytics) downgrade to "possible" with a note that it still counts if turned on later; the flag names are from memory of the Firebase docs |
| 18 | Evidence cited `jest.config.js` instead of the `package.json` dependency | dependency files are preferred as the evidence location |

## The 11 missing requirement areas (2026-11-25)

Each area was built from the official source (Android 12 and 14 behavior pages, Android signing docs, Apple's Human
Interface Guidelines, upcoming-requirements page, entitlement and Info.plist docs, App Store Connect limits and
screenshot specs, Google Play listing, Payments, UGC and User Data policies, Apple guidelines 1.2, 2.5.4, 3.1.1),
then run on the 14 apps and every new finding was checked against the source.

APK manifests: a binary-manifest decoder (`storecheck/axml.py`) was cross-checked against two independent libraries
(pyaxml to encode, androguard to decode) with UTF-8 and UTF-16 string pools and typed attributes. Not verified on a
real aapt2-built APK (none was reachable). AAB manifests are protobuf and are **not** decoded.

New findings that were true: NewPipe has 9 Play phone screenshots (limit 8); Gallery's iOS targets are 11.0 and 12.0
(below 13); Gallery and nowinandroid sign release builds with the debug key (nowinandroid's own comments say so).

| # | Problem found by running on real apps | Fix |
|---|---|---|
| 19 | NewPipe: "user-generated content" from a GitHub Actions script | CI and repo-automation folders are not app code |
| 20 | Tusky, Gallery: "payment SDK" from the word "stripe" in drawables and product names | payment SDKs are judged from dependency files only |
| 21 | Mattermost, Gallery: debug signing flagged although it was only a fallback next to a real release key | only flag when the debug key is the release build's sole signing config |
| 22 | Gallery: iOS 11 target from a commented-out Podfile line | comments are stripped before matching |
| 23 | IceCubes: launch screen "missing" because Xcode stores the key as `"INFOPLIST_KEY_UILaunchScreen_Generation[sdk=iphoneos*]"` | parse conditional and quoted build-setting keys |
| 24 | Foreground-service advisory fired on framework, system-bound and disabled services | only when code starts foreground services; library/permission-bound/disabled services skipped |
| 25 | ARFoundation: "Amplitude" analytics from a `.unity` scene value (older privacy-draft bug) | SDK evidence only from code, manifests and dependency files |

Known gaps: AAB manifests; Play App Signing and keystore handling; icon alpha rule (Apple's page does not state it);
Play screenshot pixel sizes; whether Apple's upload validation rejects a missing launch screen or push entitlement (not
stated on the pages read); Google's IARC questionnaire wording; only 5 kinds of fix patch.
