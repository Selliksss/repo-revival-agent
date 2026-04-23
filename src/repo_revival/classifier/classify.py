from pydantic import ValidationError

from repo_revival.classifier import llm
from repo_revival.classifier.models import ClassificationResult
from repo_revival.scanner import scan as scanner_scan


def classify(repo_url: str) -> ClassificationResult:
    health = scanner_scan(repo_url)
    user_msg = _format_health(health)

    raw = llm.classify_with_retry(user_msg)
    return ClassificationResult(**raw)


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