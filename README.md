# repo-revival-agent

Autonomous agent that classifies dead Python repos and either opens a modernization PR,
files a polite "use this instead" issue, or **refuses to do anything** — whichever the
evidence supports.

The most useful thing this agent did during the build was refuse to open a PR.
Not because it crashed — because it ran the test suite, compared signatures
against the baseline, and correctly concluded its changes would make things worse.

## Live artifact

**[rholder/retrying#101](https://github.com/rholder/retrying/issues/101)** —
agent opened this issue on a real abandoned repo, pointing to `tenacity`
as the maintained successor.

## Demo

![demo](demo.gif)

Agent classifies `rholder/retrying` as `let_rest`, generates a polite issue
suggesting `tenacity` as the maintained successor, and stops in dry-run mode.

## What it does

**Scan.** Collects GitHub metadata: stars, days inactive, issue counts, license,
CI, dependencies, README excerpt. No clone needed at this stage.

**Classify.** A Claude Opus tool-use agent searches GitHub for modern alternatives
and emits one of: `revive` (deps need bumping, repo is otherwise fine),
`fork` (worth porting, open a modernization PR), `let_rest` (superseded — point
users to the successor). Runs three times; only emits a verdict if all three agree.
Otherwise: `uncertain`. The agent refuses to act when it doesn't know.

**Act.** `let_rest` opens a polite GitHub issue. `revive` clones the repo into
a bot-owned fork, runs the dependency bumper and codemods, runs the test suite
in an isolated venv before *and* after changes, compares failure signatures
between the two runs, and only opens a PR if no regressions were introduced.
All actions run under a separate bot account (`@repo-revival-agent`), not under
a personal identity.

## What it explicitly won't do

- **Open a PR if tests regress against the baseline.** Comparison is by
  signature (`file_path::ExceptionType` for collection errors, full nodeid
  for test failures), not by count — so going from 4 errors to 3 in different
  files is correctly identified as a regression, not an improvement.
- **Claim credit for pre-existing failures.** PR bodies explicitly disclose
  "(NOT caused by these changes)" for any failure that was already in the
  baseline. No silent masking.
- **Act on uncertain classifier verdicts.** Three-run consensus required;
  no agreement → `uncertain` → no action.
- **Run under a personal GitHub account.** Issues and PRs are authored by
  a separate bot account so there's no doubt about whether a human reviewed
  the change.
- **Modify files under `tests/`.** Both the codemod layer and the LLM-fixer
  layer reject test files. Maintainers' test code is not the agent's to edit.
- **Wrap failing code in `try/except` to silence it.** The LLM-fixer is
  prompted to prefer `CANNOT_FIX` over speculative compliance fixes.
  When it does try a fix, the post-fix tester gate catches symptom-suppression
  attempts and rolls them back.

## Quickstart

```bash
git clone https://github.com/Selliksss/repo-revival-agent
cd repo-revival-agent
uv sync

# Add your keys to .env:
echo "ANTHROPIC_API_KEY=sk-ant-api03-..." >> .env
echo "GH_BOT_TOKEN=ghp_..." >> .env      # bot account PAT (public_repo scope)
echo "GH_BOT_USER=repo-revival-agent" >> .env  # your bot account's username

# Classify a repo:
uv run python -m repo_revival classify https://github.com/rholder/retrying

# Open let_rest issue (dry-run by default; --execute to actually open):
uv run python -m repo_revival act https://github.com/rholder/retrying --execute

# Try the revive pipeline (fork → bump → codemod → test gate → diff):
uv run python -m repo_revival revive https://github.com/bndr/pycycle

# Same, but open the PR if the test gate passes:
uv run python -m repo_revival revive https://github.com/bndr/pycycle --open-pr

# Opt-in: let the LLM attempt minimal fixes for collection errors:
uv run python -m repo_revival revive https://github.com/bndr/pycycle --use-llm-fixer

# Batch classify a dataset:
uv run python -m repo_revival batch test-repos/dataset.yaml
```

## Architecture

- **`scanner/`** — GitHub metadata + README excerpt, no clone.
- **`classifier/`** — Claude Opus tool-use agent with 3-run consensus.
- **`revive/`** — fork → bumper → codemod → tester (baseline + current) → optional
  LLM-fixer → signature comparison → PR. Each stage gates the next.
- **`let_rest_issue/`** — generates and opens the "use this instead" issue.

The revive pipeline runs the test suite *twice* (before any changes, and after
all changes) and compares the two failure sets at the signature level. This
is the only way to distinguish "we fixed it" from "we replaced one bug with a
different one" — error counts alone aren't enough.

## Accuracy (classifier)

| Repo | Expected | Agent |
|------|----------|-------|
| obskyr/colorgram.py | revive | revive ✓ |
| bndr/pycycle | revive | revive ✓ |
| bfontaine/term2048 | revive | revive ✓ |
| Shahabks/my-voice-analysis | fork | fork ✓ |
| taraslayshchuk/es2csv | fork | fork ✓ |
| selfspy/selfspy | fork | fork ✓ |
| rholder/retrying | let_rest | let_rest ✓ |
| socialpoint-labs/sheetfu | let_rest | let_rest ✓ |
| prashnts/hues | let_rest | let_rest ✓ |

**9/9** on Claude Opus with strict 3-run consensus.
Ground truth: [test-repos/dataset.yaml](test-repos/dataset.yaml).

## Status

Day 11 of build — closed. See [BUILD_LOG.md](BUILD_LOG.md) for the full
day-by-day story, including the maintainer feedback that drove the test gate,
the bot identity split, and the term2048 case where the agent correctly
refused to open a PR.

## License

MIT
