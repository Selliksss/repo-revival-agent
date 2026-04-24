from pathlib import Path
import subprocess


def fork_and_clone(owner: str, repo: str) -> Path:
    dest = Path(f"/tmp/repo-revival-forks/{owner}/{repo}")
    if dest.exists():
        return dest

    subprocess.run(["gh", "repo", "fork", f"{owner}/{repo}", "--clone=false"], check=False)
    subprocess.run(["git", "clone", f"https://github.com/Selliksss/{repo}.git", str(dest)], check=True)
    subprocess.run(["git", "checkout", "-b", "revive/modernize-deps"], cwd=dest, check=True)
    return dest
