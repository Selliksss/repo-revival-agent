# repo-revival-agent

> Autonomous agent that revives dead open-source repos — or tells you to let them rest.

Built with Claude Opus 4.7 + Claude Managed Agents + extended thinking.

## What it does

Point it at any abandoned GitHub repo. It:

1. **Diagnoses** why the repo died — stale dependencies, broken build, outdated syntax, missing tests.
2. **Decides** between three verdicts:
   - `Revive` — worth fixing, here's the plan.
   - `Fork & Modernize` — core idea is good, needs a rewrite.
   - `Let it rest` — honest report on why resurrection isn't worth it.
3. **Executes** — if the verdict is Revive, the agent iteratively patches the code in a Docker sandbox, updates dependencies, modernizes syntax, regenerates docs, and opens a clean PR with a migration guide.

## Status

Under active development — built for the **Built with Opus 4.7** hackathon (April 21–27, 2026).

## Tech stack

- Claude Opus 4.7 via Claude Agent SDK
- Claude Managed Agents
- Python 3.12
- Docker (isolated execution sandbox)
- GitHub API

## License

MIT
