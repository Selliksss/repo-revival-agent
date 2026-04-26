from pathlib import Path
from datetime import date
from typing import Literal

from pydantic import BaseModel


class DependencyInfo(BaseModel):
    name: str
    version: str | None
    source: Literal["pyproject.toml", "requirements.txt", "setup.py"]


class RepoHealth(BaseModel):
    name: str
    owner: str
    url: str
    clone_path: Path

    stars: int
    archived: bool
    default_branch: str
    license: str | None
    languages: list[str]

    open_issues_count: int
    closed_issues_count: int
    open_prs_count: int

    last_commit_date: date
    days_since_last_commit: int
    recent_commit_authors: list[str]

    has_ci: dict[str, bool]
    readme_excerpt: str

    dependencies: list[DependencyInfo]

    # New signals
    has_python2_syntax: bool = False
    python2_samples: list[str] = []
    uses_dead_deps: list[str] = []
    successor_mentions: list[str] = []
    recent_issue_titles: list[str] = []
