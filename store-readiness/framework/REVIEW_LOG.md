
## 2026-11-25T15:16Z @ 29525a9: Baseline: defined the goal framework (FRAMEWORK.md), requirements catalog (173 items from the stores' own numbering), synthetic benchmark (72 cases) and labeled real-app benchmark (14 apps); built the scorecard

Overall 62.0%. Framework re-evaluation: First measurement. Replaces my earlier judgment-based percentages (73%) with computed ones. Findings about the framework itself: D1's catalog shows 66 unmapped items, so static coverage is far lower than I had claimed; D6 is low because the package has no pyproject or CI; synthetic benchmark exposed one real bug (single-line Gradle signing) and one bad case, both fixed. Weights and gates unchanged from the first draft.
