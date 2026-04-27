# repo-revival-agent

Autonomous agent that classifies dead GitHub repositories — and either revives them,
opens a modernization PR, or points users to modern alternatives.

## Live artifact

**[rholder/retrying#101](https://github.com/rholder/retrying/issues/101)** —
agent opened this issue on a real abandoned repo, pointing to tenacity as the modern successor.

## Demo

![demo](demo.gif)

Agent classifies `rholder/retrying` as `let_rest`, generates a polite issue suggesting `tenacity` as the maintained successor, and stops in dry-run mode.

## Quickstart

```bash
git clone https://github.com/Selliksss/repo-revival-agent
cd repo-revival-agent
uv sync

# Add your key to .env:
echo "ANTHROPIC_API_KEY=sk-ant-api03-..." >> .env

# Classify a repo:
uv run python -m repo_revival classify https://github.com/rholder/retrying

# Act on verdict (opens GitHub issue for let_rest, dry-run by default):
uv run python -m repo_revival act https://github.com/rholder/retrying --execute

# Batch mode:
uv run python -m repo_revival batch test-repos/dataset.yaml
```

## How it works

**Scanner** — collects GitHub metadata: stars, days inactive, issue counts,
license, CI systems, dependencies, README excerpt. No git clone needed for this step.

**Classifier** — a Claude Opus tool-use agent. It searches GitHub for
modern alternatives, then emits a verdict: `revive` (bump deps and reopen),
`fork` (worth porting, open a modernization PR), or `let_rest` (superseded by
better alternatives, point users to them). Runs 3 times. If all 3 agree — emit verdict.
If not — `uncertain`. An honest agent that refuses to act when it doesn't know.

**Actions** — `let_rest` verdicts open a GitHub issue linking to established
alternatives. Run `repo-revival act <url> --execute` to apply the verdict.
`revive` and `fork` pipelines are in progress.

## Accuracy

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

**9/9** — measured on Claude Opus with strict 3-run consensus.
Ground truth dataset: [test-repos/dataset.yaml](test-repos/dataset.yaml).

## Status

Day 6 of build. Built in public — see [BUILD_LOG.md](BUILD_LOG.md) for the full story.

## License

MIT
