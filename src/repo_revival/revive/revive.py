from pathlib import Path
import typer
from repo_revival.revive import fork, bumper, pr, tester, codemod, llm_fixer


def revive(repo_url: str, open_pr: bool = False, use_llm_fixer: bool = False) -> None:
    owner, repo = _parse_url(repo_url)
    typer.echo(f"🍴 Forking {owner}/{repo}...")
    repo_path = fork.fork_and_clone(owner, repo)

    typer.echo("📏 Running baseline test suite (pre-bump)...")
    baseline_result = tester.run_tests(repo_path)
    baseline_status = baseline_result["status"]
    typer.echo(f"   baseline status: {baseline_status}")
    if baseline_result.get("tests"):
        typer.echo(f"   baseline tests:  {baseline_result['tests']}")
    if baseline_result.get("failed_ids"):
        typer.echo(f"   baseline failed_ids: {baseline_result['failed_ids']}")
    if baseline_result.get("error_signatures"):
        typer.echo(f"   baseline error_signatures: {baseline_result['error_signatures']}")

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
    if test_result.get("failed_ids"):
        typer.echo(f"   failed_ids: {test_result['failed_ids']}")
    if test_result.get("error_signatures"):
        typer.echo(f"   error_signatures: {test_result['error_signatures']}")

    typer.echo("\n📊 Comparing baseline vs post-bump...")
    comparison = tester.compare_results(baseline_result, test_result)
    typer.echo(f"   verdict: {comparison['verdict']}")
    typer.echo(f"   summary: {comparison['summary']}")
    if comparison.get("preexisting_failures"):
        typer.echo(f"   pre-existing: {comparison['preexisting_failures']}")
    if comparison.get("new_failures"):
        typer.echo(f"   new failures: {comparison['new_failures']}")
    if comparison.get("fixed_failures"):
        typer.echo(f"   fixed failures: {comparison['fixed_failures']}")

    # Sole gate: only "regression" + new_failures aborts. All other verdicts proceed.
    # But if LLM fixer is enabled and new_failures exist, give fixer a chance first.
    if comparison["verdict"] == "regression" and comparison.get("new_failures"):
        if not use_llm_fixer:
            typer.echo(
                f"\n❌ Aborting: regression introduced ({len(comparison['new_failures'])} new failures). "
                f"Per policy, revive PR is not opened when test suite fails."
            )
            return
        # will try fixer below, then re-check

    llm_fixes: list = []
    if status != "passed" and use_llm_fixer:
        typer.echo("\n🤖 Attempting LLM-assisted fixes...")
        fixer_result = llm_fixer.attempt_loop(repo_path, test_result, baseline_result=baseline_result)
        for entry in fixer_result["attempts_log"]:
            typer.echo(
                f" attempt {entry['attempt_num']}: "
                f"{entry.get('file', '?')} → {entry.get('fix_brief', '?')} → "
                f"status={entry.get('status_after', '?')}"
            )
        test_result = fixer_result["final_test_result"]
        status = test_result["status"]
        llm_fixes = fixer_result["fixes"]

        # Re-run comparison after fixer
        comparison = tester.compare_results(baseline_result, test_result)
        typer.echo(f"   post-fixer verdict: {comparison['verdict']}")
        if comparison.get("new_failures"):
            typer.echo(f"   new failures: {comparison['new_failures']}")
        if comparison.get("fixed_failures"):
            typer.echo(f"   fixed failures: {comparison['fixed_failures']}")

        # Re-check gate after fixer
        if comparison["verdict"] == "regression" and comparison.get("new_failures"):
            typer.echo(
                f"\n❌ Aborting: regression introduced ({len(comparison['new_failures'])} new failures). "
                f"Per policy, revive PR is not opened when test suite fails."
            )
            return

    if not open_pr:
        typer.echo("\n[dry-run] Pipeline reached PR step. To open real PR: --open-pr")
        return

    typer.echo("\n📝 Generating PR description...")
    description = pr.generate_pr_description(
        all_changes, {"owner": owner, "repo": repo},
        test_result=test_result, llm_fixes=llm_fixes,
        baseline_result=baseline_result, comparison=comparison,
    )
    typer.echo("\n--- PR DESCRIPTION ---")
    typer.echo(description)
    typer.echo("--- END ---\n")

    pr.commit_and_push(repo_path, all_changes)
    pr_url = pr.open_pr(owner, repo, description)
    typer.echo(f"✅ PR opened: {pr_url}")


def _parse_url(url: str):
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]