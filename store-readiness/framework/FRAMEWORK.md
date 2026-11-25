# Goal framework

## 1. The goal

> A filter that gets **any type of app** ready for **Google Play and the App Store**: it examines the stores'
> requirements against the app and makes recommendations accordingly.

Constraints the owner set along the way:

- **Language agnostic**: works on any language or framework, from files and archives, not by parsing source code.
- **Runs on Linux, macOS and Windows**; the tool itself has no mobile app.
- **Input**: a GitHub link or a local folder (and built `.apk` / `.ipa`).
- **Local-first**: a local LLM may add explanations; nothing leaves the machine unless asked.
- **Recommendations, not verdicts**: it never claims an app will be approved.

### What "ready" means here

A static tool cannot decide everything a store reviewer decides. So readiness has three parts, and the tool must
report all three:

1. **Automated findings**: requirements it can decide from the package, each with the store's source and fix.
2. **Assisted answers**: drafts and hints for the forms only the developer can complete (privacy labels, ratings).
3. **Manual checklist**: requirements that need a human, the store console or a running app, listed so nothing is
   silently skipped.

## 2. Dimensions

Eight dimensions, each with a metric a script computes, a weight, and a **gate**. The goal is achieved only when
**every gate passes**, the real-app corpus was measured, and the last two recorded runs both passed.

| | Dimension | Weight | Gate | Metric |
|---|---|---|---|---|
| D1 | Requirement coverage | 25 | 80% | 0.7 x static coverage + 0.3 x checklist coverage of the requirements catalog |
| D2 | Correctness | 25 | 90% | 0.5 x synthetic benchmark + 0.5 x real-app benchmark |
| D3 | Verification | 10 | 90% | 0.6 x rules verified + 0.2 x rules fresh + 0.2 x SDK mappings verified |
| D4 | Actionability | 10 | 80% | 0.5 x rule schema complete + 0.5 x auto-fixable share (target 30% of rules) |
| D5 | Stack reach | 10 | 75% | stacks validated on at least 2 real apps (1 app counts half) over the target stack list |
| D6 | Portability and delivery | 10 | 90% | installable package, 3-OS CI, OSes observed passing, GUI test, stdlib-only |
| D7 | Safety and privacy | 5 | 100% | five static checks: network use, patches never written, GUI local and tokened, URL allowlist, tests |
| D8 | Robustness | 5 | 90% | no crashes, a note whenever a check is skipped, scan time within 10 s |

Overall = weighted average. It is a progress indicator; the **gates** decide whether the goal is met.

### D1 Requirement coverage

The denominator is the **requirements catalog** (`framework/requirements.json`), built from the stores' own
structure, not from what the tool already does:

- every numbered section of Apple's App Review Guidelines (parsed from the page; 125 on 2026-11-25),
- Google Play's Policy Center topics plus the specific Play policies read so far,
- Apple and Android technical requirements outside those lists (privacy manifest, deployment target, target API ...).

Each item has a class:

| Class | Weight | Meaning |
|---|---|---|
| `automated` | 1.0 | deterministic rule covering the whole statically testable requirement |
| `partial` | 0.5 | rule or hint covers part of it (heuristic, narrower scope, or draft only) |
| `unmapped` | 0 | statically checkable in principle, not built yet |
| `not_checkable` | excluded from static coverage | needs a human, console or running app; **a reason is required** |

- **Static coverage** = (automated + 0.5 x partial) / (items - not_checkable).
- **Checklist coverage** = share of `not_checkable` items the tool actually lists in its manual checklist.
- If more than 60% of the catalog is marked `not_checkable`, or any reference is broken, D1 is halved.

### D2 Correctness

- **Synthetic benchmark** (`benchmark/synthetic.json`): for every rule, a seeded-defect case that must fire and a
  near-miss case that must not, plus every false positive and silent miss real apps have taught us, plus corrupt
  inputs. Score = 0.4 x recall + 0.4 x (1 - false-positive rate) + 0.2 x share of rules having both a positive and a
  negative case.
- **Real benchmark** (`benchmark/real_apps.json`, pinned commits): each finding is labeled `tp`, `fp` or
  `unverified` with evidence. Precision = tp / (tp + fp + known false positives that came back). Known-issue recall =
  true issues the tool must find. Score = precision x recall x min(1, verified fraction / 0.8). **Any unlabeled
  finding halves the score** until it is triaged against the source.

### D3 Verification

Every rule carries the official source and the date it was checked. A rule marked "partly" counts half. Rules older
than 90 days are stale. SDK-to-data mappings count separately.

### D4-D8

As in the table. Exact formulas are in `storecheck/measure.py`; the data they read is in this folder.

## 3. Anti-gaming rules

The score is only useful if it cannot be improved by changing the ruler.

1. **The denominator comes from the stores.** Adding or reclassifying a catalog item needs a source URL; marking an
   item `not_checkable` needs a reason; the excluded share is capped (see D1).
2. **Labels need evidence.** A finding is `tp` or `fp` only if checked against the source code; otherwise
   `unverified`, which counts for nothing.
3. **Fix the tool, not the test.** A failing benchmark case is fixed in the tool unless the case itself is wrong, and
   then the reason is written in the review log.
4. **Weights, gates and targets change only with a logged reason** in `REVIEW_LOG.md`, and never in the same change
   that would raise the score.
5. **Real-world surprises go into the benchmark first.** When a real app exposes a false positive or a silent
   miss, add a case before fixing it.
6. **Unmeasured means zero.** A part that was not run (for example, no corpus) counts as 0 and is printed as
   NOT MEASURED.

## 4. Protocol: after every work command

1. Run the test suite.
2. Run the scorecard and record it:
   ```bash
   python -m storecheck.measure --corpus <corpus dir> \
       --log "<what was done>" --review "<framework re-evaluation>"
   ```
   (`framework/benchmark/fetch.sh` fetches the corpus at the pinned commits.)
3. Compare with the previous run (printed automatically; stored in `history.jsonl`).
4. If any dimension went down, fix it or write down why before reporting.
5. Report to the owner: the scorecard, what moved and why, and the **lowest-scoring weighted gaps**.
6. **Re-evaluate the framework itself** (the `--review` text is recorded in `REVIEW_LOG.md`):
   - Does every dimension still serve the goal? Is anything missing?
   - Did the work expose a requirement type not in the catalog? Add it.
   - Did a real app show a failure the benchmark would not have caught? Add a case.
   - Did any metric get easier to raise than the thing it stands for? Tighten it.
7. Choose the next work from the largest remaining gap x weight.

## 5. Known limits of this framework

- **Catalog completeness is not measurable.** It is anchored to the stores' own numbering, but the Google side and
  the technical list are only as complete as the pages read. Mitigation: audit it against the stores' indexes at each
  review.
- **Classification and labels are one reviewer's judgment**, recorded with reasons. A second reviewer should audit them.
- **The real corpus is 14 apps.** It proves nothing about rarer stacks; D5 measures that gap.
- **OS observation is manual** (`observations.json`) until CI runs on all three systems.
- **No store decisions are in the benchmark.** Precision is measured against the source code, not against what a
  store reviewer did.
