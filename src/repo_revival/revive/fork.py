from pathlib import Path
import subprocess

from repo_revival.bot_env import bot_env, bot_user


def fork_and_clone(owner: str, repo: str) -> Path:
    dest = Path(f"/tmp/repo-revival-forks/{owner}/{repo}")
    if dest.exists():
        return dest

    b_env = bot_env()
    result = subprocess.run(
        ["gh", "repo", "fork", f"{owner}/{repo}", "--clone=false"],
        env=b_env, capture_output=True, text=True,
    )
    # gh repo fork returns nonzero if already forked, but stderr contains "already exists" — that's OK
    if result.returncode != 0 and "already exists" not in result.stderr.lower():
        raise RuntimeError(f"gh repo fork failed: {result.stderr}")
    subprocess.run(
        ["git", "clone", f"https://github.com/{bot_user()}/{repo}.git", str(dest)],
        env=b_env, check=True,
    )
    subprocess.run(["git", "checkout", "-b", "revive/modernize-deps"], cwd=dest, env=b_env, check=True)
    return dest
