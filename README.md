# repo-revival-agent

> Autonomous agent that revives dead GitHub repositories — or tells you to let them rest.

Built with Claude Opus 4.7 for the [Built with Opus 4.7](https://cerebralvalley.ai/e/built-with-4-7-hackathon) hackathon (April 21–26, 2026).

![demo](./docs/demo.gif)

## The problem

There are thousands of useful open-source repositories with 100+ stars that have been abandoned. Good ideas, dead code. Most are salvageable if you know what to do with them — but figuring out *which* ones are worth the effort takes hours of manual triage.

## How it works

Point the agent at a dead repo. It returns one of three verdicts with reasoning:

### 🔧 Revive
The repo is fixable. The agent bumps dependencies, patches deprecated APIs, and runs the existing tests inside a Docker sandbox until they pass. Outputs a `.patch` file ready to PR upstream.

### 🍴 Fork & Modernize
The core logic is valuable but the stack is too far gone (Python 2, Django 1.x, unsupported frameworks). The agent generates a skeleton on a modern stack (Python 3.12, pydantic v2, httpx, pytest) and writes a migration guide mapping old modules to new ones.

### 🪦 Let it rest
Active alternatives already exist with the same functionality. The agent searches GitHub for maintained replacements, verifies functional parity, and writes a RIP report with a migration table.

## Quick start

```bash
# Analyze a dead repo (verdict + reasoning, no changes made)
uv run python -m repo_revival analyze https://github.com/rholder/retrying

# Attempt to revive (runs Docker sandbox, produces .patch)
uv run python -m repo_revival revive https://github.com/obskyr/colorgram.py

# Generate a modernized skeleton fork
uv run python -m repo_revival fork https://github.com/selfspy/selfspy

# Batch process a dataset of repos
uv run python -m repo_revival batch test-repos/dataset.yaml
```

## Architecture

```
CLI (typer)
    ↓
repo_fetcher  →  gh clone into tmp
    ↓
health_scanner  →  git log + gh api + PyPI API
    ↓
classifier (Opus 4.7 + extended thinking)
    ↓
┌───────────┬───────────┬─────────────┐
revive       fork         let_rest
(Docker)    (skeleton)    (GH search)
```

## Opus 4.7 features used

- **Extended thinking** — classifier reasoning over health metrics and README
- **Tool use loops** — Revive pipeline iterates patch → test → repeat (max 3 iterations)
- **Prompt caching** — system prompts reused across batch runs for cost efficiency

## Results

Tested on 9 real abandoned repos spanning all three verdict categories.

*(Full results table coming Day 5 — stay tuned.)*

## Install from source

```bash
git clone https://github.com/Selliksss/repo-revival-agent
cd repo-revival-agent
uv sync
export ANTHROPIC_API_KEY=sk-ant-...
```

Requires:
- Python 3.12+
- `uv` package manager
- Docker Desktop (for Revive pipeline)
- `gh` CLI authenticated

## Why this project

Dead repos are a graveyard of good ideas. Manually auditing which are revivable, forkable, or obsolete is tedious. Opus 4.7 with extended thinking turns out to be surprisingly good at this triage — which is exactly the kind of multi-step reasoning task modern agent loops were designed for.

## License

MIT — see [LICENSE](./LICENSE)

---

Built in public during the hackathon. Follow progress on [@Selliks](https://x.com/Selliks).