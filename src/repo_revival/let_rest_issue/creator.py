import subprocess

from repo_revival.bot_env import bot_env


def create_issue(owner: str, repo: str, title: str, body: str) -> str:
    result = subprocess.run(
        [
            "gh", "issue", "create",
            "--repo", f"{owner}/{repo}",
            "--title", title,
            "--body", body,
        ],
        capture_output=True, text=True, check=True, env=bot_env(),
    )
    return result.stdout.strip()
