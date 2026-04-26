# Build Log

# Build log — repo-revival-agent

Daily log of building an autonomous agent that classifies dead GitHub
repos and either revives them, opens fork-and-modernize PRs, or politely
suggests archival.

Building in public over a 6-day sprint.

## Day 1 — scanner

Built the scanner. Given a repo URL: shallow clone, parse `pyproject.toml`
/ `setup.py` / `setup.cfg` / `requirements.txt`, extract README excerpt,
license, default branch, CI systems. Pull GitHub metadata via `gh api`
(stars, days inactive, issue/PR counts). Output: a structured `HealthReport`
that downstream stages consume.

## Day 2 — classifier (4/9 → 8/9)

Three-verdict classifier on top of Claude Opus: revive / fork / let_rest.
Gave the model `gh search` as a tool to find modern alternatives.

**First run on a 9-repo test set: 4/9.** Disaster.

Diagnosis: I had hardcoded "CRITICAL RULES" in the system prompt — things
like "if deps are mainstream, output revive". These rules contradicted
ground truth on 5/9 cases. The model was obeying instructions over evidence.

**Fix: deleted every rule. Kept tool access. 8/9.**

Lesson: with a capable model and good tools, prescriptive rules become a
liability. Let the model reason from evidence.

Two API gotchas along the way:
- Opus 4.7 broke `thinking.type=enabled` — removed extended thinking entirely
- `gh search` timed out on queries with spaces — wrong URL encoding,
  fixed with `-f q={query}` form

## Day 3 — revive pipeline

End-to-end: fork via `gh repo fork`, clone fork, bump deps, open PR.

The bumper:
- Replaces `python_requires`, injects it if missing
- Bumps pinned versions in pyproject.toml / requirements.txt / setup.py
- Only touches real pins (`==`, `<`, `<=`, `~=`, `!=`). Skips `>=` because
  `>=` is already a relaxed constraint — bumping it would be cosmetic.

Two bugs while building:
- setup.py classifier list regex matched `]` of `setup()` instead of the
  list. Fix: don't touch classifiers at all (they're PyPI metadata, not
  scope).
- Bumper was adding/removing trailing whitespace, polluting diffs. Fix:
  preserve original lines for non-bumped strings.

**Outcome: bfontaine/term2048#41 — 4 lines changed, honest PR description
including a "what was NOT tested" section.**

## Day 4 — let_rest pipeline + the consensus discovery

Original plan: 9 artifacts across all 3 verdicts. Cut down fast.

Why: the "fork candidates" in my dataset (colorgram, pycycle) used `>=`
specs. The bumper correctly did nothing. The "PRs" would have been
single-line cosmetic changes. I almost shipped them anyway. Pulled back —
committed to a quality-over-quantity principle. Reduced scope to 1 quality
artifact.

Built the let_rest pipeline:
- Generator: produces title + body via Opus, polite/factual tone
- Creator: opens the issue via `gh issue create`
- Every issue includes an acknowledgment section: "this is a suggestion,
  closing is a valid response"

**Then I hit the real problem.**

Classifying `prashnts/hues` 5 times in a row gave: let_rest, let_rest,
let_rest, revive, revive. Assumed it was LLM sampling. Added
`temperature=0`. Ran 5 more times: let_rest, let_rest, revive, revive,
**fork**.

The variance wasn't in LLM sampling. It was in the **tool-use trajectory**:
different runs picked different search queries, found different evidence,
reached different verdicts. `temperature=0` cannot fix path-dependent
variance through an agent loop.

**Fix: strict consensus.** classify() now runs N=3. If all 3 agree, emit
the verdict. If not, emit `verdict="uncertain"` and the agent does nothing.
No issue, no PR, no guess.

This is the principle I'm most proud of from the sprint:

> An honest agent refuses to act on uncertain knowledge.

For demos, "I'm not sure about this one" is a stronger story than a
confident wrong answer. For maintainers, it's the difference between
thoughtful suggestions and noise.

**Outcome: rholder/retrying#101 — polite suggestion to archive or link
to tenacity (8.5k★) as the established successor.** retrying has been
silent for 10 years; tenacity literally documents itself as the fork
replacement of retrying.

3/3 consensus on rholder/retrying. prashnts/hues returned uncertain and
was correctly skipped.

## Day 5 — scanner enrichment + read_repo_file tool

Goal: enrich scanner signals and give the classifier the ability to read source files directly.

**Scanner enrichment (models.py, filesystem.py, analyze.py):**
- `has_python2_syntax` + `python2_samples`: scan `*.py` files for print-without-parens, xrange, urllib2, `.iter*()`, old except syntax
- `uses_dead_deps`: check requirements.txt/setup.py/pyproject.toml against a 18-item dead-pkg list (theano, pycrypto, pycurl, etc.)
- `successor_mentions`: regex scan README for "use X instead", "deprecated in favor of", "migrating to", "superseded by", "consider X"
- `recent_issue_titles`: fetch last 5 open issue titles via `gh issue list`
- README excerpt: 8000 chars (was 300)

**Classifier tool: read_repo_file(path)**
- Model can read any file from the cloned repo — setup.py, src/, examples/
- Returns first 4000 chars, truncated with marker if longer
- Max 8 tool-use iterations (up from 5) to allow deeper exploration

**Accuracy test on 9-repo dataset: 4/9**
- revive: 3/3 ✅ (colorgram, pycycle, term2048)
- fork: 1/3 ✅ (es2csv), 2 uncertain (my-voice-analysis, selfspy)
- let_rest: 0/3 — all three returned fork or uncertain

Root cause: 4/9 uncertain verdicts. The new signals are being fed to the model
but the strict consensus bar is too high for borderline cases. The model
was choosing fork for my-voice-analysis in some runs and uncertain in others.
selfspy and retrying similarly fell into disagreement.

This is a regression from Day 4's 8/9 baseline. Analysis:
- The model sees the new signals but the prompt wasn't updated to weight them
- The read_repo_file tool gives the model more rope to explore — and more rope
  sometimes means more confusion
- The enriched health report (now 8k chars README) shifts the model's focus
  away from the core signals

**Action plan for Day 6:**
1. Revert the enriched health format change (keep the signals available via read_repo_file instead)
2. Reduce unnecessary context — README excerpt back to 300 chars
3. Or: accept lower strictness, move to majority-vote consensus (2/3)

Scanner enrichment is committed. The classifier needs prompt tuning to
make use of the new signals, not be distracted by them.

## What's left (Day 6)

- README + GIF demo — the project looks dead from the outside without it
- fork pipeline: bumper learns Python 2 → 3 fixes (xrange, print, urllib2)
- One real fork-PR

## Counts so far

- Repos analyzed: 9 (test dataset)
- Classifier accuracy: 8/9
- PRs opened: 1 — bfontaine/term2048#41
- Issues opened: 1 — rholder/retrying#101
- Maintainers spammed with low-quality output: 0

## What I'd tell someone starting Day 1

- **Tools beat rules.** If you're writing "if X then output Y" in your
  system prompt, you're probably losing accuracy.
- **Determinism is a property of the whole agent, not just `temperature`.**
  When tools are involved, the variance multiplies.
- **"Quality over quantity" sounds like a platitude until you're staring
  at 4 generated PRs that would each annoy a maintainer.** Then it costs
  you real scope.