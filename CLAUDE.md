# repo-revival-agent

Autonomous agent that analyzes dead GitHub repositories and outputs one of three verdicts: Revive, Fork & Modernize, or Let It Rest. Built for "Built with Opus 4.7" hackathon (April 21-26, 2026).

## Architecture

CLI entry → Scanner → Classifier → Pipeline (Revive/Fork/Let-rest) → Report

## Stack

- Python 3.12, uv for deps
- anthropic SDK with Claude Opus 4.7
- typer for CLI
- pydantic for data models
- gh CLI for GitHub operations
- Docker (via subprocess) for isolated test execution
- httpx for PyPI/GitHub API calls

## Code conventions

- Functions under 40 lines
- Type hints everywhere
- No try/except around normal code paths — let it crash loud
- CLI output uses emojis for visual parsing (🔍 📊 🎯 🔧 🍴 🪦)
- All LLM calls go through src/repo_revival/llm.py (central logging + caching)
- Dead-repo test dataset lives in test-repos/dataset.yaml
- Use `uv add <pkg>` never `pip install`

## Current day focus

Day -1 (April 20): Scaffolding + reading docs. No LLM calls yet.

## What NOT to do

- Don't add web UI
- Don't write tests for my code (we test on real repos in dataset)
- Don't refactor working code
- Don't add CI/CD
- Don't support non-Python repos
- Don't add features not in today's plan

## Commands

- Help: `uv run python -m repo_revival --help`
- Analyze: `uv run python -m repo_revival analyze <url>`
- Batch: `uv run python -m repo_revival batch test-repos/dataset.yaml`
- Install deps: `uv add <pkg>`

## External refs

- Plan by day: ~/Obsidian/Startup-Journey/10-Хакатон дневной план.md
- Project overview: ~/Obsidian/Startup-Journey/06-Проект repo-revival-agent.md