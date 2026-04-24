from pathlib import Path
import typer
from repo_revival.revive import fork, bumper, pr


def revive(repo_url: str, open_pr: bool = False) -> None:
    owner, repo = _parse_url(repo_url)
    typer.echo(f"🍴 Forking {owner}/{repo}...")
    repo_path = fork.fork_and_clone(owner, repo)

    typer.echo("🔧 Bumping Python version...")
    py_changes = bumper.bump_python_version(repo_path)

    typer.echo("🔧 Bumping dependencies...")
    dep_changes = bumper.bump_dependencies(repo_path)

    all_changes = py_changes + dep_changes
    if not all_changes:
        typer.echo("No changes needed. Repo is already modern.")
        return

    typer.echo("\n📋 Changes:")
    for c in all_changes:
        typer.echo(f"  - {c}")

    typer.echo("\n📊 Git diff:")
    import subprocess
    subprocess.run(["git", "diff"], cwd=repo_path)

    if not open_pr:
        typer.echo("\n[dry-run] Done. To open real PR: --open-pr")
        return

    typer.echo("\n📝 Generating PR description...")
    description = pr.generate_pr_description(all_changes, {"owner": owner, "repo": repo})
    typer.echo("\n--- PR DESCRIPTION ---")
    typer.echo(description)
    typer.echo("--- END ---\n")

    pr.commit_and_push(repo_path, all_changes)
    pr_url = pr.open_pr(owner, repo, description)
    typer.echo(f"✅ PR opened: {pr_url}")


def _parse_url(url: str):
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]
