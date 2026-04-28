import subprocess
from pathlib import Path

from repo_revival.bot_env import bot_env, bot_user
from repo_revival.classifier.llm import get_client


DISCLAIMER_HEADER = """## Disclaimer
🤖 This pull request was opened by [repo-revival-agent](https://github.com/Selliksss/repo-revival-agent), an experimental tool that analyzes inactive repositories and proposes modernization changes. A human reviewed this PR before opening. Feel free to close if not useful.

---

"""


def generate_pr_description(changes: list[str], repo_info: dict) -> str:
    client = get_client()
    messages = [
        {
            "role": "user",
            "content": f"Write a PR description for modernizing repository {repo_info['owner']}/{repo_info['repo']}.\n\nChanges made:\n" + "\n".join(f"- {c}" for c in changes) + "\n\nOutput markdown. Include: (1) what was changed, (2) why, (3) what was NOT tested. Max 200 words. Do not oversell. Do NOT include a disclaimer or LLM-authorship section — that will be prepended automatically."
        }
    ]
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system="You write honest, concise PR descriptions for repository modernization. Output markdown.",
        messages=messages,
    )
    body = ""
    for block in resp.content:
        if block.type == "text":
            body = block.text
            break
    return DISCLAIMER_HEADER + body


def commit_and_push(repo_path: Path, changes: list[str], dry_run: bool = False) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    msg = "Modernize dependencies and Python version\n\n" + "\n".join(f"- {c}" for c in changes)
    subprocess.run(["git", "commit", "-m", msg], cwd=repo_path, check=True)
    if dry_run:
        typer.echo("[dry-run] Skipping git push")
        return
    subprocess.run(["git", "push", "-u", "origin", "revive/modernize-deps"], cwd=repo_path, env=bot_env(), check=True)


def open_pr(owner: str, repo: str, description: str, dry_run: bool = False) -> str | None:
    if dry_run:
        typer.echo("[dry-run] Skipping PR creation")
        return None
    result = subprocess.run(
        ["gh", "pr", "create", "--repo", f"{owner}/{repo}", "--head", f"{bot_user()}:revive/modernize-deps",
         "--title", "Modernize dependencies", "--body", description],
        capture_output=True, text=True, check=True, env=bot_env(),
    )
    return result.stdout.strip()
