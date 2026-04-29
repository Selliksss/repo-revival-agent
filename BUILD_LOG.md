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

## Day 5 (redux) — the auth bug

**This is the most important entry in the entire log.**

After days of debugging why classifier accuracy kept regressing (4/9, 6/9, 8/9),
why retrying returned uncertain, why selfspy kept flipping verdict — I finally
checked the one thing nobody thinks to question: which model is actually running.

```bash
printenv | grep -iE 'anthropic|minimax'
```

```
ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic
ANTHROPIC_AUTH_TOKEN=sk-cp-<REDACTED>
ANTHROPIC_MODEL=MiniMax-M2.7
ANTHROPIC_SMALL_FAST_MODEL=MiniMax-M2.7
ANTHROPIC_DEFAULT_OPUS_MODEL=MiniMax-M2.7
```

Claude Code was injecting MiniMax proxy variables into every subprocess.
The Anthropic SDK reads `ANTHROPIC_BASE_URL` and silently routes all traffic
there. The SDK does not log which endpoint it is hitting.
The Python process never printed "Using MiniMax-M2.7".
There was no error — just slightly wrong answers and high variance.

**We ran the entire agent on MiniMax-M2.7 for 5 days, thinking it was Opus 4.7.**

All the "fixes" we made on Day 5 — reverting the health report, removing
read_repo_file, rolling back enrichment — were compensating for the weakness
of the wrong model, not fixing real problems.

**The fix:**
```python
from dotenv import load_dotenv
load_dotenv(override=True)  # CRITICAL: override shell env vars

import os
os.environ.pop("ANTHROPIC_BASE_URL", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
os.environ.pop("ANTHROPIC_MODEL", None)
os.environ.pop("ANTHROPIC_SMALL_FAST_MODEL", None)
os.environ.pop("ANTHROPIC_DEFAULT_OPUS_MODEL", None)
os.environ.pop("ANTHROPIC_DEFAULT_SONNET_MODEL", None)
os.environ.pop("ANTHROPIC_DEFAULT_HAIKU_MODEL", None)

client = Anthropic()  # now correctly routes to api.anthropic.com
```

**Lesson: when an SDK is silent about which endpoint it hits, log the resolved
base_url and model on every run.** The Anthropic SDK could have printed
"Using base_url: https://api.minimax.io/anthropic" on the first request.
It didn't. We spent 5 days debugging model behavior that was actually
proxy behavior.

**Result after fix:** 9/9 confirmed on true Opus 4.7 — all three verdict
categories (revive, fork, let_rest) classified correctly across the full 9-repo
test set. prashnts/hues (the borderline case) returned let_rest with 0.90
confidence.

Every previous accuracy measurement (4/9, 6/9, 8/9 on "Day 4 baseline")
was measuring MiniMax, not Opus.

**Final 9-repo baseline on Opus 4.7:**

| Repo | Expected | Got | Confidence |
|------|----------|-----|------------|
| obskyr/colorgram.py | revive | revive | 0.85 |
| bndr/pycycle | revive | revive | 0.82 |
| bfontaine/term2048 | revive | revive | 0.90 |
| Shahabks/my-voice-analysis | fork | fork | 0.75 |
| taraslayshchuk/es2csv | fork | fork | 0.78 |
| selfspy/selfspy | fork | fork | 0.78 |
| rholder/retrying | let_rest | let_rest | 0.95 |
| socialpoint-labs/sheetfu | let_rest | let_rest | 0.82 |
| prashnts/hues | let_rest | let_rest | 0.90 |

**Accuracy: 9/9 (100%)** — Baseline restored on real Opus 4.7.

---

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
- Classifier accuracy: 8/9 (confirmed on Opus 4.7)
- PRs opened: 1 — bfontaine/term2048#41 (MiniMax-era artifact)
- Issues opened: 1 — rholder/retrying#101 (MiniMax-era artifact)
- Maintainers spammed with low-quality output: 0

## What I'd tell someone starting Day 1

- **Tools beat rules.** If you're writing "if X then output Y" in your
  system prompt, you're probably losing accuracy.
- **Determinism is a property of the whole agent, not just `temperature`.**
  When tools are involved, the variance multiplies.
- **"Quality over quantity" sounds like a platitude until you're staring
  at 4 generated PRs that would each annoy a maintainer.** Then it costs
  you real scope.
- **Always verify which endpoint your SDK is hitting.** If your SDK doesn't
  log the resolved URL and model on startup, add logging. The Anthropic
  SDK silently accepts `ANTHROPIC_BASE_URL` and routes accordingly —
  with no indication in output that routing changed.

## Day 6 — README, LICENSE, and the first maintainer feedback

**Shipped:**
- README.md with quickstart, How it works, accuracy table (9/9), link to live artifact
- LICENSE (MIT) + `license = "MIT"` field in pyproject.toml
- CLI polish: `act` now prints formatted Verdict / Title / Body with separators instead of raw dict; debug logs gated behind `REPO_REVIVAL_DEBUG` env var; git clone stderr silenced

### The first maintainer feedback (term2048#41)

Three days after I opened bfontaine/term2048#41 (Day 3 revive PR, MiniMax-era
artifact), the maintainer responded:

> What was NOT tested
>
> Thanks but if you don't test your changes I can't accept them.
>
> Btw it would be better to run your agent under its own account or disclose
> that this PR was done by a LLM.

This is the most valuable feedback the project has received. Two distinct
problems, both real, both my fault:

**1. No automated test validation before opening a PR.**
The Day 3 revive pipeline bumped dependencies and opened a PR, but never
ran the target repo's test suite against the bumped versions. The PR body
honestly disclosed this in a "What was NOT tested" section — but honest
disclosure is not a substitute for actually testing. A maintainer cannot
merge changes that the author didn't validate.

**2. No LLM-authorship disclosure in revive PRs.**
The let_rest pipeline opens issues with a mandatory disclaimer header
("🤖 This issue was opened by repo-revival-agent..."). The revive pipeline
opens PRs with no such header. This is a policy gap I missed — different
action types had different disclosure rules.

**Closed term2048#41.** Reopening only after both gaps are fixed.

### New policies for the agent

1. **All PRs and issues from the agent must include a mandatory
   LLM-authorship disclaimer header.** Not optional, not configurable,
   not skippable. Same template as let_rest issues.
2. **Revive PRs must run the target repo's test suite against the bumped
   dependencies before opening, and include the test results in the PR
   body.** If the test suite fails or is missing, no PR is opened — the
   verdict becomes `uncertain` and the agent does nothing.

### Lessons

- **Build-in-public works as a feedback mechanism, not just a marketing
  channel.** One thoughtful maintainer comment is worth more than a hundred
  views. The whole point of opening real PRs on real repos is to find out
  what real maintainers think — and bfontaine just told me, clearly and
  for free.
- **Disclosure rules need to be uniform across action types.** I had a
  good policy for one action type and no policy for the other, which is
  worse than no policy at all because it looks intentional.
- **Honest disclosure of "what wasn't tested" is not a substitute for
  testing.** It's better than silence, but a maintainer's reasonable
  reaction is "then come back when you've tested it." That's exactly
  what happened.

### Code changes

- `src/repo_revival/revive/pr.py`: added `DISCLAIMER_HEADER` constant, prepended programmatically to every PR body. Header is **not** generated by the model — it is concatenated after generation, so it cannot be skipped, paraphrased, or omitted regardless of model behavior. The system prompt for the body generator was also updated to instruct the model not to include its own disclaimer (would be duplicated otherwise).
- `src/repo_revival/__main__.py`: replaced `typer.echo(result)` raw-dict output of `act` with formatted output — Verdict / Action / Title / horizontal separators / Body / dry-run hint. Critical for the demo GIF and for the CLI feeling like a finished tool rather than a debug script.
- `src/repo_revival/classifier/llm.py`: gated all `print()` debug statements behind `if os.environ.get("REPO_REVIVAL_DEBUG")`. The debug logs are still available for development by setting the env var, but invisible by default.
- `src/repo_revival/scanner/git.py`: `git clone` stderr redirected to `subprocess.DEVNULL` so it doesn't bleed into user-facing CLI output.
- `LICENSE` + `pyproject.toml`: MIT license added properly. Without a LICENSE file, the project was technically all-rights-reserved (no one could legally fork it), regardless of what the README said.

### Demo

`demo.gif` (223K, recorded with asciinema + agg) shows `act` running on rholder/retrying end-to-end. Embedded at the top of the README so it is the first thing a visitor sees.

## Day 7 — Bot identity

The most important architectural change since the auth-bug fix.

**Context.** When bfontaine reviewed term2048#41, his second comment was:

> Btw it would be better to run your agent under its own account or
> disclose that this PR was done by a LLM.

The first part of that — "run your agent under its own account" — is not
just an etiquette suggestion. It's how every legitimate bot on GitHub
operates: Dependabot, Renovate, pre-commit-ci. Maintainers know to expect
those identities; they have public track records visible on a single
profile page; opt-outs and rate limits target a stable identity rather
than a person.

Running the agent under @Selliksss conflates two things — my personal
contributions graph and the agent's actions. A maintainer looking at my
profile sees both, and can't tell which is which. That's bad for me
(my dev profile is full of bot artifacts) and bad for them (no clean
audit of the agent's behavior).

**What was built:**
- New GitHub account: **@repo-revival-agent** with profile README
  declaring what the agent does, what it doesn't do, and how to opt out
  (`[no-agent]` comment).
- **Classic PAT** (not fine-grained — fine-grained tokens can't act on
  repos outside the token owner's account, which is a hard blocker for
  cross-account agents).
- New module `src/repo_revival/bot_env.py` with `bot_env()` and
  `bot_user()` helpers. Every `gh` and `git push` subprocess in the
  agent passes `env=bot_env()` so the GH CLI authenticates as the bot.
- Hardcoded `Selliksss` references in `revive/pr.py` (`--head` arg)
  replaced with `bot_user()`.

**Side discovery — generator robustness.**

While testing on `Selliksss/test-bot-victim` (a deliberately empty
test repo named "test-bot-victim"), the model recognized the target
as a test and **refused to generate an issue** — explanation:
*"I should not generate this issue. The verdict is `let_rest`, meaning..."*

The generator parsed line 1 as the title and called `gh issue create`
with that as `--title`. GitHub rejected the >256-char title with a
cryptic CalledProcessError.

The right response is not to outwit the model — it's right to refuse.
Added three guards in `generator.py`:
1. Title >200 chars → `RuntimeError("...likely a refusal: ...")`
2. Title starts with "I should" / "I cannot" / "I won't" / "I refuse" →
   `RuntimeError("Generator refused to produce issue: ...")`
3. Title doesn't start with "Suggestion" → `RuntimeError(...)`

Now if the model refuses, the agent surfaces a clean error and does
nothing. The model's instinct here was correct — opening an issue on
"test-bot-victim" *would* be wrong. The fix is to make that refusal
machine-readable, not to silence it.

**Verification.**

Created `Selliksss/legacy-utils-archive` (realistic-looking dead Python
project: README + setup.py + "no longer actively maintained" status).
Ran `act --execute`. Bot opened a clean issue:
[Selliksss/legacy-utils-archive#1](https://github.com/Selliksss/legacy-utils-archive/issues/1).
Author: @repo-revival-agent. Disclaimer present, body well-structured,
title under length limit. End-to-end works.

**What this closes.**
- Policy #1 from Day 6 (mandatory LLM-disclaimer in PRs/issues): now
  closed in code on **two** levels — the disclaimer header in
  `revive/pr.py` *and* the bot identity itself, which is the more
  important signal.
- The "looks like a person spamming maintainers" failure mode of
  bfontaine#41. Future PRs are clearly authored by a bot.

**What's still open.**
- Policy #2: test-suite runner before opening revive PRs.
- Reopen term2048#41 with both fixes (now possible).
- Opt-out mechanism: read `[no-agent]` comments / `.no-agents` file
  / CONTRIBUTING.md before action.
- Throttling: max one action per maintainer per N days.

## Day 8 — test runner Stage 1 + revive pipeline integration

**Commit:** f860bb3

**What was built:**
- `src/repo_revival/revive/tester.py` — `detect_tests()` + `run_tests()`.
  `detect_tests()` checks in order: pytest.ini, `[tool.pytest]` in pyproject.toml,
  `tests/` dir, `test_*.py` files, `[tool:pytest]` in setup.cfg.
  `run_tests()` creates an isolated `.venv-test` venv (via `uv venv --seed --clear`),
  installs the target package (`pip install -e .`), then upgrades pytest
  (`pip install pytest --upgrade`) to avoid self-hosting-repo issues
  (pytest itself bundles an old pytest version). Runs the suite with
  `pytest -v --tb=short`, captures stdout/stderr tails, and parses
  pass/fail/errors/skipped counts using `finditer`-based regex that handles
  all pytest summary formats in any order.
- `revive/revive.py` — test runner called after bumper, before commit+push.
  If `status != "passed"`, abort with message. Policy gate is enforced
  at the pipeline level, not advisory.
- `revive/pr.py` — `format_test_results()` helper renders a markdown block
  (emoji header + stats + collapsible stdout tail). `generate_pr_description()`
  accepts optional `test_result` dict and appends the block after LLM body.
  Model prompt tells it not to generate its own "Test results" section
  (verified: LLM respects the instruction, no duplication).

**Key technical findings:**
- `uv venv` by default creates a bare venv with no pip/setuptools/wheel.
  Must use `--seed` flag to get pip included.
- `--clear` flag required on re-runs — `uv venv` refuses to overwrite
  an existing venv without it.
- Order matters: `pip install -e .` then `pip install pytest --upgrade`.
  Some self-hosting repos (like pytest itself) bundle an old pytest version
  as a dependency; without `--upgrade` after `pip install -e .`, the bundled
  old version wins and collection fails.
- Pytest summary format: `===== N passed in Xs =====` when clean;
  `===== N errors in Xs =====` when collection fails; `===== N failed, M passed in Xs =====`
  for mixed. Parser handles all via `finditer` on count+label pairs.

**What this closes.**
- Policy #2 from bfontaine/term2048#41: "Thanks but if you don't test your
  changes I can't accept them." — now enforced in code. Tests must pass
  before PR is opened.
- Both policies from the maintainer review are now closed: identity (Day 7)
  and test validation (Day 8).

**What's still open.**
- Reopen term2048#41 with both fixes in place (now possible).
- Fork pipeline MVP: Python 2 → 3 auto-fix via 2to3 + tests.
- Opt-out mechanism.
- Throttling.

### Still TODO

- Test-suite runner in revive pipeline (closes policy #2 in code — DONE f860bb3)
- Reopen term2048#41 with both fixes in place
- Fork pipeline MVP: Python 2 → 3 auto-fix via 2to3 + tests
- Extended dataset (15-20 repos)
- Distribution: X-thread or Telegram post about the auth-bug story

## Day 9 — LLM fixer + term2048 follow-up

**Commit:** d895f45

### What was built

**LLM-fixer module** (`src/repo_revival/revive/llm_fixer.py`):
- Opt-in `--use-llm-fixer` flag in revive CLI. Called from `revive.py` when
  test gate fails and flag is set.
- `attempt_loop()` runs up to 2 LLM-guided search/replace edit cycles.
  Each cycle: extract deepest non-test root-cause file from pytest ERROR
  block → build root-cause dict `{file, line, code, exception_type}` →
  call LLM with explicit root-cause context → verify SEARCH block is
  unique in file → write fix to disk → run tests → rollback if worse.
- Root-cause extraction: parses traceback to find `file:lineno:` line,
  the code line immediately after, and the exception class (via regex
  `r"^\s*(?:[\w.]+\.)?(\w+(?:Error|Exception|Operation|Failure)):\s+"`).
- LLM prompt rules: focus on the root-cause line, never touch files
  under `tests/`, return CANNOT_FIX if fix requires multi-file changes
  or changes runtime semantics.
- Search/replace blocks (not unified diff) with uniqueness guard:
  `file_content.count(search)` must be exactly 1.
- Apply-then-test order: fix is written to disk before pytest re-run.
  Rollback via in-memory original if errors increase.
- Early termination: `(failing_file, exception_type)` signature tracked
  across attempts; loop stops if signature repeats unchanged.

**PR integration** (`src/repo_revival/revive/pr.py`):
- `format_llm_fixes()` renders all applied LLM fixes as a separate PR
  section: "## LLM-assisted fixes ⚠️ REVIEW CAREFULLY" with per-file
  rationale and `git diff`-style diff blocks.
- All LLM fixes land in PR body only after human-review step — never
  silently merged.

### What was validated

**E2E on bfontaine/term2048 (fork clone at `/tmp/repo-revival-forks/bfontaine/term2048`):**
- Bumper + codemod fix 1 of 4 collection errors: `imp.reload` →
  `importlib.reload` in `tests/helpers.py`.
- LLM-fixer attempt 1 fixes 2 more: wraps `sys.stdin.fileno()` and
  `termios.tcgetattr` in `term2048/keypress.py` with try/except, since
  pytest redirects stdin at collection time.
- Final state: 1 error remains in `tests/test_keypress.py:23`:
  `keypress = kp._getRealModule()` → `AttributeError: module
  'term2048.keypress' has no attribute '_getRealModule'`.
- `_getRealModule` verified absent from every release tag 0.1.2 through
  0.2.7 — the test predates any release. The hard "never touch tests/"
  rule correctly prevents the agent from masking this latent bug.
- Agent gate aborts; no PR opened. Correct outcome.

### term2048#41 follow-up

**Bot comment posted** from `@repo-revival-agent`:
https://github.com/bfontaine/term2048/pull/41#issuecomment-4348072749

Comment is FYI / closing-the-loop. Details what the pipeline fixed,
flags the dormant `_getRealModule` test bug (with traceback excerpt),
explicitly does not ask for reopen. Pre-flight verified `gh api user`
returns `repo-revival-agent` identity before posting.

### Both maintainer policies from term2048#41 now closed in code

- **Policy #1** (bot identity): Day 7 commit. Verified pre-flight on
  every posting.
- **Policy #2** (test before PR): Day 8 commit (tester.py) + Day 9 commit
  (LLM-fixer as secondary defense).

### Known limitations (honest)

- LLM-fixer regex hardcodes `term2048/` prefix for root-cause extraction
  — works on term2048, will not extract root causes from other repos.
  Must generalize to any non-stdlib non-venv path before next target.
- `bot_user()` now raises RuntimeError if GH_BOT_USER is not set —
  footgun closed.
- `attempt_loop` intentionally leaves file in "applied but not passed" state
  between attempts; if interrupted mid-loop, local fork has uncommitted
  partial fixes.

### Still TODO

- Generalize root-cause regex (remove `term2048/` hardcode) before next
  target repo
- Fix bot_env.py footgun (GH_BOT_USER fallback — DONE, bot_user() now hard-fails)
- Second test target: Python repo where LLM-fixer can converge to passed
- Distribution: post-mortem writeup for X/Telegram on the term2048 arc