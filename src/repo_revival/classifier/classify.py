from collections import Counter
from typing import Literal
from pydantic import BaseModel

from repo_revival.classifier import llm
from repo_revival.classifier.models import ClassificationResult
from repo_revival.scanner import scan as scanner_scan


class ClassificationResult(BaseModel):
    verdict: Literal["revive", "fork", "let_rest", "uncertain"]
    confidence: float
    reasoning: str
    search_calls: list[dict] = []


def classify(repo_url: str) -> ClassificationResult:
    health = scanner_scan(repo_url)
    user_msg = _format_health(health)

    # Strict consensus: 3 runs, all 3 must agree
    raw_runs = []
    for _ in range(3):
        raw = llm.classify_with_retry(user_msg)
        raw_runs.append(raw)

    verdicts = [r["verdict"] for r in raw_runs]
    if len(set(verdicts)) == 1:
        # All 3 identical — use the highest confidence run
        winning_run = max(raw_runs, key=lambda r: r["confidence"])
        return ClassificationResult(**winning_run)
    else:
        # No consensus — return uncertain
        counts = Counter(verdicts)
        disagreement = ", ".join(f"{v}({c})" for v, c in counts.items())
        return ClassificationResult(
            verdict="uncertain",
            confidence=0.0,
            reasoning=f"3 runs gave: {disagreement} — model does not agree on this repository.",
            search_calls=[],
        )


def _format_health(h) -> str:
    ci_active = [k for k, v in h.has_ci.items() if v]
    dep_names = [d.name for d in h.dependencies]

    return f"""Repository metrics:
- Stars: {h.stars}, Days inactive: {h.days_since_last_commit}, Archived: {h.archived}
- Languages: {", ".join(h.languages) if h.languages else "None"}
- Open issues: {h.open_issues_count}, Closed: {h.closed_issues_count}, Open PRs: {h.open_prs_count}
- License: {h.license or "None"}, Default branch: {h.default_branch}
- Dependencies: {", ".join(dep_names) if dep_names else "(none detected)"}
- CI systems: {", ".join(ci_active) if ci_active else "none"}
- README excerpt: {h.readme_excerpt[:300]}"""
