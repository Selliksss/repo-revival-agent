import shutil
import subprocess
from pathlib import Path
from datetime import date


def clone(url: str, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(["git", "clone", "--depth=1", url, str(dest)], check=True)
    return dest


def last_commit_date(repo_path: Path) -> date:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ci"],
        cwd=repo_path, capture_output=True, text=True, check=True
    )
    return date.fromisoformat(result.stdout.strip().split()[0])


def recent_authors(repo_path: Path, count: int = 5) -> list[str]:
    result = subprocess.run(
        ["git", "log", "-20", "--format=%ae"],
        cwd=repo_path, capture_output=True, text=True, check=True
    )
    seen = {}
    authors = []
    for email in result.stdout.splitlines():
        if email not in seen:
            seen[email] = True
            authors.append(email)
            if len(authors) >= count:
                break
    return authors