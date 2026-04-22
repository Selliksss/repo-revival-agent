from pathlib import Path


def detect_ci(repo_path: Path) -> dict[str, bool]:
    workflows_dir = repo_path / ".github" / "workflows"
    return {
        "github_actions": workflows_dir.exists() and any(workflows_dir.iterdir()),
        "travis": (repo_path / ".travis.yml").exists(),
        "circleci": (repo_path / ".circleci" / "config.yml").exists(),
    }


def read_readme_excerpt(repo_path: Path, max_chars: int = 500) -> str:
    for name in ["README.md", "README.rst", "README.txt"]:
        p = repo_path / name
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            return text[:max_chars]
    return ""


def detect_license(repo_path: Path) -> str | None:
    for name in ["LICENSE", "LICENSE.txt", "LICENSE.md", "LICENSE.rst"]:
        p = repo_path / name
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
    return None