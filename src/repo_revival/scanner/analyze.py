import re
import subprocess
from pathlib import Path
from datetime import date

from repo_revival.scanner import models, github, git, filesystem, dependencies, reporter


def scan(repo_url: str) -> models.RepoHealth:
    subprocess.run(["gh", "auth", "status"], check=True, capture_output=True)

    owner, repo = _parse_github_url(repo_url)
    clone_dest = Path(f"/tmp/repo-revival/{owner}/{repo}")

    basic = github.fetch_repo_metadata(owner, repo)
    languages = github.fetch_languages(owner, repo)

    open_issues = github.fetch_open_issues_count(owner, repo)
    closed_issues = github.fetch_closed_issues_count(owner, repo)
    open_prs = github.fetch_open_prs_count(owner, repo)

    git.clone(repo_url, clone_dest)
    last_commit = git.last_commit_date(clone_dest)
    authors = git.recent_authors(clone_dest)

    has_ci = filesystem.detect_ci(clone_dest)
    readme_excerpt = filesystem.read_readme_excerpt(clone_dest)
    license_name = filesystem.detect_license(clone_dest)

    deps = dependencies.parse(clone_dest)

    health = models.RepoHealth(
        name=repo,
        owner=owner,
        url=repo_url,
        clone_path=clone_dest,
        stars=basic["stargazers_count"],
        archived=basic["archived"],
        default_branch=basic["default_branch"],
        license=basic["license"]["spdx_id"] if basic["license"] else license_name,
        languages=languages,
        open_issues_count=open_issues,
        closed_issues_count=closed_issues,
        open_prs_count=open_prs,
        last_commit_date=last_commit,
        days_since_last_commit=(date.today() - last_commit).days,
        recent_commit_authors=authors,
        has_ci=has_ci,
        readme_excerpt=readme_excerpt,
        dependencies=deps,
    )

    reporter.write_report(health, Path("reports/"))
    return health


def _parse_github_url(url: str) -> tuple[str, str]:
    pattern = r"github\.com/([^/]+)/([^/]+)"
    match = re.search(pattern, url)
    if not match:
        raise ValueError(f"Invalid GitHub URL: {url}")
    return match.group(1), match.group(2)