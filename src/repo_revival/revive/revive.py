from pathlib import Path
import typer
from repo_revival.revive import fork, bumper, pr, tester, codemod


def revive(repo_url: str, open_pr: bool = False) -> None:
    owner, repo = _parse_url(repo_url)
    typer.echo(f"🍴 Forking {owner}/{repo}...")
    repo_path = fork.fork_and_clone(owner, repo)

    typer.echo("🔧 Bumping Python version...")
    py_changes = bumper.bump_python_version(repo_path)

    typer.echo("🔧 Bumping dependencies...")
    dep_changes = bumper.bump_dependencies(repo_path)

    typer.echo("🔧 Applying codemods...")
    codemod_changes = codemod.fix_imp_module(repo_path)
    if codemod_changes:
        typer.echo("📋 Codemod changes:")
        for c in codemod_changes:
            typer.echo(f"  - {c}")

    all_changes = py_changes + dep_changes + codemod_changes
    if not all_changes:
        typer.echo("No changes needed. Repo is already modern.")
        return

    typer.echo("\n📋 Changes:")
    for c in all_changes:
        typer.echo(f"  - {c}")

    typer.echo("\n📊 Git diff:")
    import subprocess
    subprocess.run(["git", "diff"], cwd=repo_path)

    typer.echo("\n🧪 Running test suite against bumped deps...")
    test_result = tester.run_tests(repo_path)
    status = test_result["status"]
    typer.echo(f"   status: {status}")
    if test_result.get("tests"):
        typer.echo(f"   tests:  {test_result['tests']}")
    if test_result.get("reason"):
        typer.echo(f"   reason: {test_result['reason']}")
    if status == "error":
        typer.echo(f"   stage:  {test_result.get('stage')}")
        typer.echo(f"   stderr tail:\n{test_result.get('stderr_tail', '')}")

    if status != "passed":
        typer.echo(
            f"\n❌ Aborting: tests did not pass (status={status}). "
            f"Per policy, revive PR is not opened when test suite fails or is missing."
        )
        return

    if not open_pr:
        typer.echo("\n[dry-run] Tests passed. To open real PR: --open-pr")
        return

    typer.echo("\n📝 Generating PR description...")
    description = pr.generate_pr_description(all_changes, {"owner": owner, "repo": repo}, test_result=test_result)
    typer.echo("\n--- PR DESCRIPTION ---")
    typer.echo(description)
    typer.echo("--- END ---\n")

    pr.commit_and_push(repo_path, all_changes)
    pr_url = pr.open_pr(owner, repo, description)
    typer.echo(f"✅ PR opened: {pr_url}")


def _parse_url(url: str):
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]
