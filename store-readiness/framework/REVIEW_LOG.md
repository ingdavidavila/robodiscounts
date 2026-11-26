
## 2026-11-25T15:16Z @ 29525a9: Baseline: defined the goal framework (FRAMEWORK.md), requirements catalog (173 items from the stores' own numbering), synthetic benchmark (72 cases) and labeled real-app benchmark (14 apps); built the scorecard

Overall 62.0%. Framework re-evaluation: First measurement. Replaces my earlier judgment-based percentages (73%) with computed ones. Findings about the framework itself: D1's catalog shows 66 unmapped items, so static coverage is far lower than I had claimed; D6 is low because the package has no pyproject or CI; synthetic benchmark exposed one real bug (single-line Gradle signing) and one bad case, both fixed. Weights and gates unchanged from the first draft.

## 2026-11-25T15:21Z @ 096251e: AAB manifest decoding (aapt2 protobuf, verified against Google's own compiled schema on 6 real bundle manifests), APK decoding verified on a real APK, missing targetSdk defaults to minSdk (verified in Android docs), build/outputs artifacts now scanned, base-module-only for bundles

Overall 62.0%. Framework re-evaluation: Work exposed three gaps the benchmark had not covered: built artifacts under build/outputs were skipped, the unknown-target check ignored archive manifests, and bundles reported the same target once per module. Each now has a synthetic case (75 to 79 cases). Catalog reasons updated for exported, 16 KB, app bundle and target API; no class changes, so D1 is unchanged, which is right: manifest decoding deepens existing items rather than adding requirements. Assumption recorded: only the bundle's base module is compared for targetSdk; not verified against a store source. Weights and gates unchanged.

## 2026-11-25T15:22Z @ 096251e: Framework change: added a 'file-format readers verified' sub-metric (10% of D2) with framework/readers.json

Overall 60.8%. Framework re-evaluation: Reason: the manifest work made the tool more trustworthy (decoders verified against Google's schema and androguard on real data) but the scorecard could not see it, so it did not move. The new sub-metric starts at 2 of 4 readers verified (axml, pbxml verified; ELF alignment and image sizes not), so it LOWERS D2 now; it cannot raise the score until the remaining readers are verified. Weights of the other D2 parts reduced from 0.5/0.5 to 0.45/0.45. No gate changed.

## 2026-11-25T15:24Z @ 9150b71: Manual checklist feature (--checklist, GUI tab): lists all 63 requirements that need a human/console/running app and all 66 not yet checked, for the stores in scope; moved requirements.json into the package

Overall 68.3%. Framework re-evaluation: D1's checklist share is now measured by RUNNING the feature (checklist_ids), not read from a data flag, so it cannot be raised by editing data. Concern recorded: the checklist lists 'unmapped' items too, which the metric does not count (only not_checkable counts), so adding an unmapped item to the list cannot raise D1. Another concern: a long unprioritised list is less useful than a short one; the framework has no usefulness metric for it. Not changing the framework for this now; revisit when a second reviewer audits the catalog. Weights and gates unchanged.

## 2026-11-25T15:26Z @ 9150b71: Packaging and CI: pyproject.toml (stdlib only, console scripts storecheck and storecheck-gui, package data), 3-OS x 2-Python GitHub Actions workflow, installed-copy check in the scorecard; portability fixes: finding paths are POSIX on every OS, all file reads force UTF-8, patches written as bytes

Overall 74.3%. Framework re-evaluation: D6 rose because packaging exists and an installed copy was verified to work outside the repo. It cannot reach its gate yet: CI has not run on macOS or Windows, so os_observed stays at 1 of 3 (Linux). That is deliberate: observations.json is only updated from a real run. The portability fixes (backslash paths and the default Windows encoding would have broken the tests on Windows) were found by reasoning about the CI matrix, not by running it, so they are unconfirmed until CI runs. Python 3.10+ is declared but only 3.13 has been run. Weights and gates unchanged.

## 2026-11-25T15:28Z @ 9150b71: Verified the two remaining file-format readers against independent references on real data: ELF alignment vs readelf and pyelftools on 5 real libraries; PNG/JPEG sizes vs Pillow on 78 generated and 274 real images (0 mismatches). Removed a circular import between checks and checks_extra.

Overall 75.6%. Framework re-evaluation: D2's readers sub-metric rose from 2/4 to 4/4 verified, restoring the points the framework change took away; it can only be raised by running a reference on real data, not by editing the data. Gap noticed: the readers list is itself hand-maintained, so a new reader could be added to the tool without being listed. Mitigation to add later: a test that greps the package for struct.unpack/zipfile readers and fails if one is missing from readers.json. Weights and gates unchanged.

## 2026-11-26T16:47Z @ d6d3e65: Requirement coverage batch 1 (Apple, verified from official sources): required-reason API declarations vs the app's own native code (Apple's per-category API lists), Apple's third-party SDK privacy-manifest list (87 SDKs), private APIs (2.5.1), non-WebKit browser engines (2.5.6), iPad support (2.4.1), IAP restore (3.1.1). 6 rules, 22 benchmark cases, 5 catalog items moved from unmapped to partial.

Overall 76.5%. Framework re-evaluation: Real-app triage found and fixed 5 false positives (Linux/macOS code, fastlane config, SKOverlay-only StoreKit, Expo config declarations, func stat); each is now a must-not case. 12 new findings on the real corpus were labeled; 11 verified true, the rest are dependency-list advisories. Concern: required_reason_api is a text search of native code, so Flutter/React Native apps whose iOS side is mostly plugins get little from it; stays 'partial'. Concern: I only moved items to 'partial', none to 'automated'. Framework unchanged.

## 2026-11-26T16:52Z @ a6f0c16: Requirement coverage batch 2 (policy-conflict checks, each verified from the official page): ads in extension targets (2.5.18), health data with ad SDKs (5.1.3), third-party SDKs in child-directed apps (1.3, 5.1.4, Google Families), VPN apps (5.4), screen recording consent (2.5.14), remote-website wrapper apps (Apple 4.2/4.2.2, Play Spam policy), WebView JavaScript interface (Play). 7 rules, 13 benchmark cases, 10 catalog items to partial, 1 new Google item.

Overall 76.9%. Framework re-evaluation: Honest caveat: on the 14 real apps only one of the 7 new rules fires (NewPipe addJavascriptInterface), so six rules are verified on synthetic cases only and their real-world false-positive rate is unknown. The framework counts a rule toward D1 once it has a benchmark case and a source, but nothing measures how often it fires in the real world; considering a 'rules exercised by the real corpus' sub-metric. Also: D4 falls as rules are added without new automatic fixes, which pulls against D1; recorded as a known tension, not changed. Catalog gained one Google item (WebView JS interface) with its source.

## 2026-11-26T20:10Z @ 5f5482c: Perf: skip translation/vector/data suffixes (.strings,.svg,.pdf,...) when loading signal text; slowest real scan was 9.8s of 10s

Overall 77.0%. Framework re-evaluation: Framework still fits. D8 gain expected; D2 must not move (watch for lost findings). Next: D1 remaining items.

## 2026-11-26T20:12Z @ 5f5482c: Requirement coverage batch 3: MusicKit usage key (4.5.2, added to usage-strings rule, key doc verified via DocC), crypto wallet/mining note (3.1.5), keyboard extension note (4.4.1); text verified from guidelines page; 7 synthetic cases; new generic ios_signal_note check

Overall 77.2%. Framework re-evaluation: Framework fits. Still note-style advisory rules: partial credit only. None expected to fire on real corpus; need real-corpus-exercised sub-metric. D4 unchanged.
