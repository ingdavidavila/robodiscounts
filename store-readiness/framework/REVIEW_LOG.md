
## 2026-11-25T15:16Z @ 29525a9: Baseline: defined the goal framework (FRAMEWORK.md), requirements catalog (173 items from the stores' own numbering), synthetic benchmark (72 cases) and labeled real-app benchmark (14 apps); built the scorecard

Overall 62.0%. Framework re-evaluation: First measurement. Replaces my earlier judgment-based percentages (73%) with computed ones. Findings about the framework itself: D1's catalog shows 66 unmapped items, so static coverage is far lower than I had claimed; D6 is low because the package has no pyproject or CI; synthetic benchmark exposed one real bug (single-line Gradle signing) and one bad case, both fixed. Weights and gates unchanged from the first draft.

## 2026-11-25T15:21Z @ 096251e: AAB manifest decoding (aapt2 protobuf, verified against Google's own compiled schema on 6 real bundle manifests), APK decoding verified on a real APK, missing targetSdk defaults to minSdk (verified in Android docs), build/outputs artifacts now scanned, base-module-only for bundles

Overall 62.0%. Framework re-evaluation: Work exposed three gaps the benchmark had not covered: built artifacts under build/outputs were skipped, the unknown-target check ignored archive manifests, and bundles reported the same target once per module. Each now has a synthetic case (75 to 79 cases). Catalog reasons updated for exported, 16 KB, app bundle and target API; no class changes, so D1 is unchanged, which is right: manifest decoding deepens existing items rather than adding requirements. Assumption recorded: only the bundle's base module is compared for targetSdk; not verified against a store source. Weights and gates unchanged.

## 2026-11-25T15:22Z @ 096251e: Framework change: added a 'file-format readers verified' sub-metric (10% of D2) with framework/readers.json

Overall 60.8%. Framework re-evaluation: Reason: the manifest work made the tool more trustworthy (decoders verified against Google's schema and androguard on real data) but the scorecard could not see it, so it did not move. The new sub-metric starts at 2 of 4 readers verified (axml, pbxml verified; ELF alignment and image sizes not), so it LOWERS D2 now; it cannot raise the score until the remaining readers are verified. Weights of the other D2 parts reduced from 0.5/0.5 to 0.45/0.45. No gate changed.
