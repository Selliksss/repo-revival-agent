import subprocess


def create_issue(owner: str, repo: str, title: str, body: str) -> str:
    result = subprocess.run(
        [
            "gh", "issue", "create",
            "--repo", f"{owner}/{repo}",
            "--title", title,
            "--body", body,
        ],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()
