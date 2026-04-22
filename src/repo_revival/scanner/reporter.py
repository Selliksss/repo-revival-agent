import re
from pathlib import Path
from datetime import datetime

from repo_revival.scanner.models import RepoHealth


def write_report(health: RepoHealth, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{health.owner}_{health.name}_{timestamp}.md"
    filepath = output_dir / filename

    md = _build_markdown(health)
    filepath.write_text(md, encoding="utf-8")
    return filepath


def _build_markdown(h: RepoHealth) -> str:
    ci_items = "\n".join(f"- {k}: {v}" for k, v in h.has_ci.items())
    dep_items = "\n".join(f"- `{d.name}` ({d.source})" for d in h.dependencies)

    return f"""# Repo Health Report: {h.owner}/{h.name}

**URL:** {h.url}
**Clone path:** {h.clone_path}
**Archived:** {h.archived}
**Default branch:** {h.default_branch}
**License:** {h.license or "None"}

---

## Metrics

| Metric | Value |
|--------|-------|
| Stars | {h.stars} |
| Open Issues | {h.open_issues_count} |
| Closed Issues | {h.closed_issues_count} |
| Open PRs | {h.open_prs_count} |
| Last Commit | {h.last_commit_date} |
| Days Inactive | {h.days_since_last_commit} |
| Languages | {", ".join(h.languages) if h.languages else "None"} |

---

## CI Systems

{ci_items or "None detected"}

---

## Dependencies ({len(h.dependencies)})

{dep_items or "No dependencies found"}

---

## Recent Commit Authors

{chr(10).join(f"- {a}" for a in h.recent_commit_authors) or "Unknown"}

---

## README Excerpt

{h.readme_excerpt[:500]}...

---

## Verdict

**TODO: Day 2 — LLM classifier will fill this in**
"""