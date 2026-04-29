"""repo-revival-agent CLI entry point."""
import json
import yaml
from pathlib import Path
from datetime import datetime

import typer

from repo_revival.scanner import scan as scanner_scan
from repo_revival.classifier import classify
from repo_revival.revive.revive import revive as revive_do
from repo_revival.let_rest_issue.act import act as act_do

app = typer.Typer(
    name="repo-revival",
    help="Autonomous agent that revives dead GitHub repositories.",
    no_args_is_help=True,
)


@app.command()
def analyze(repo_url: str):
    """Analyze a repo and output health report + verdict."""
    health = scanner_scan(repo_url)
    typer.echo(f"✅ Report written: reports/{health.owner}_{health.name}_*.md")


@app.command(name="classify")
def classify_cmd(repo_url: str):
    """Classify a repo (scan + LLM verdict)."""
    result = classify(repo_url)
    typer.echo(f"🔍 Verdict: {result.verdict} (confidence: {result.confidence:.2f})")
    typer.echo(f"💬 {result.reasoning}")


@app.command(name="batch")
def batch(
    dataset_path: str,
    start: int = typer.Option(0, "--start", help="Starting index (0-based)"),
    count: int = typer.Option(0, "--count", help="Number of repos to process (0 = all)"),
):
    """Process repos in a dataset.yaml file. Use --start/--count for batching."""
    with open(dataset_path) as f:
        dataset = yaml.safe_load(f)

    results = []
    all_repos = []
    for category in ["revive", "fork", "let_rest"]:
        for repo in dataset.get(category, []):
            all_repos.append((repo["url"], category, repo["name"]))

    end = start + count if count > 0 else len(all_repos)
    slice_repos = all_repos[start:end]
    total = len(all_repos)

    for i, (url, expected, name) in enumerate(slice_repos, start + 1):
        owner = url.split("/")[-2]
        typer.echo(f"[{i}/{total}] 🔍 {owner}/{name}...", nl=False)
        result = classify(url)

        correct = result.verdict == expected
        results.append({
            "name": name,
            "owner": owner,
            "expected": expected,
            "verdict": result.verdict,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "correct": correct,
        })

        _write_classification_report(owner, name, url, result)
        _save_progress(results, total)

        mark = "✓" if correct else "✗"
        status = "✅" if correct else "❌"
        typer.echo(f" {status} {result.verdict} (expected: {expected}) {mark}")

    if count > 0:
        _write_accuracy_report(results, start=start, total=total)
    else:
        _write_accuracy_report(results)


def _write_classification_report(owner: str, name: str, url: str, result):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = Path("reports") / f"{owner}_{name}_classification.md"
    filepath.parent.mkdir(parents=True, exist_ok=True)

    health = scanner_scan(url)
    health_md = _build_health_table(health)

    md = f"""# Classification: {owner}/{name}

**Verdict: {result.verdict.upper()}** (confidence: {result.confidence:.2f})

**Reasoning:** {result.reasoning}

---

{health_md}

---

## Verdict

**{result.verdict.upper()}** — {result.reasoning}

**Confidence:** {result.confidence:.2f}
"""
    filepath.write_text(md, encoding="utf-8")


def _build_health_table(h) -> str:
    ci_items = "\n".join(f"- {k}: {v}" for k, v in h.has_ci.items() if v)
    dep_names = [d.name for d in h.dependencies]
    dep_items = "\n".join(f"- `{d}`" for d in dep_names) or "No dependencies"

    return f"""## Health Metrics

| Metric | Value |
|--------|-------|
| Stars | {h.stars} |
| Days Inactive | {h.days_since_last_commit} |
| Archived | {h.archived} |
| Default Branch | {h.default_branch} |
| License | {h.license or "None"} |
| Open Issues | {h.open_issues_count} |
| Closed Issues | {h.closed_issues_count} |
| Open PRs | {h.open_prs_count} |
| Languages | {", ".join(h.languages) if h.languages else "None"} |

## CI Systems

{ci_items or "None detected"}

## Dependencies ({len(h.dependencies)})

{dep_items}

## README Excerpt

{h.readme_excerpt[:300]}"""


def _save_progress(results: list, total: int):
    """Save intermediate results to test-repos/last_run.json."""
    progress = {
        "results": results,
        "completed": len(results),
        "total": total,
    }
    path = Path("test-repos/last_run.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_accuracy_report(results: list, start: int = 0, total: int = 0):
    if total == 0:
        total = len(results)
    correct = sum(1 for r in results if r["correct"])
    accuracy = correct / len(results) if results else 0

    lines = [f"# Batch Classification Results\n"]
    lines.append(f"**Accuracy: {correct}/{len(results)} ({accuracy:.1%})**\n\n")
    if start > 0 or len(results) < total:
        lines.append(f"*Partial run: repos {start+1}-{start+len(results)} of {total}*\n\n")
    lines.append("| Repo | Expected | Got | Correct |")
    lines.append("|------|----------|-----|---------|")
    for r in results:
        mark = "✓" if r["correct"] else "✗"
        lines.append(f"| {r['owner']}/{r['name']} | {r['expected']} | {r['verdict']} | {mark} |")

    summary_path = Path("reports/accuracy.md")
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"\n📊 Accuracy: {correct}/{len(results)} ({accuracy:.1%})")
    typer.echo(f"📄 Summary: {summary_path}")


@app.command(name="revive")
def revive_cmd(
    repo_url: str,
    open_pr: bool = typer.Option(False, "--open-pr"),
    use_llm_fixer: bool = typer.Option(False, "--use-llm-fixer", help="Allow LLM to attempt minimal fixes when test gate fails (experimental, opt-in)"),
):
    """Fork, bump deps, show diff (default dry-run)."""
    revive_do(repo_url, open_pr=open_pr, use_llm_fixer=use_llm_fixer)


@app.command()
def fork(repo_url: str):
    """Generate a modernized skeleton fork of a legacy repo."""
    typer.echo(f"TODO: fork {repo_url}")


@app.command(name="act")
def act_cmd(repo_url: str, execute: bool = typer.Option(False, "--execute")):
    """Scan, classify, and act based on verdict (dry-run by default)."""
    result = act_do(repo_url, execute=execute)
    _print_act_result(result)


def _print_act_result(result: dict):
    verdict = result.get("verdict", "unknown")
    action = result.get("action", "")
    typer.echo("")
    typer.echo(f"Verdict: {verdict.upper()}")
    typer.echo(f"Action:  {action}")
    if verdict == "let_rest":
        if action == "dry_run":
            typer.echo("")
            typer.echo("─" * 70)
            typer.echo(f"Title: {result.get('title', '')}")
            typer.echo("─" * 70)
            typer.echo("")
            typer.echo(result.get("body", ""))
            typer.echo("")
            typer.echo("─" * 70)
            typer.echo("(dry-run — pass --execute to open this issue on GitHub)")
        elif action == "issue_opened":
            typer.echo(f"URL:     {result.get('url', '')}")
    elif verdict == "uncertain":
        typer.echo(f"Reason:  {result.get('reasoning', '')}")


def main():
    app()


if __name__ == "__main__":
    main()