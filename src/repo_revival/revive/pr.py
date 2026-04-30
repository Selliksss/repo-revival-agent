import subprocess
from pathlib import Path

from repo_revival.bot_env import bot_env, bot_user
from repo_revival.classifier.llm import get_client


DISCLAIMER_HEADER = """## Disclaimer
🤖 This pull request was opened by [repo-revival-agent](https://github.com/Selliksss/repo-revival-agent), an experimental tool that analyzes inactive repositories and proposes modernization changes. A human reviewed this PR before opening. Feel free to close if not useful.

---

"""


COLLECTION_EXC_TYPES = {
    "ModuleNotFoundError", "ImportError", "SyntaxError", "IndentationError",
    "io.UnsupportedOperation", "UnsupportedOperation", "AttributeError",
}


def _is_collection_error(item: str) -> bool:
    """True if item's exception type is a known collection error type."""
    if "::" not in item:
        return False
    exc_type = item.split("::")[1]
    return exc_type in COLLECTION_EXC_TYPES


def format_test_results(test_result: dict, baseline_result: dict | None = None, comparison: dict | None = None) -> str:
    """Render a markdown block describing how the test suite ran against the bumped deps."""
    status = test_result.get("status")
    tests = test_result.get("tests") or {}
    stdout_tail = test_result.get("stdout_tail", "")
    verdict = comparison.get("verdict") if comparison else None

    preexisting_test_failures: list[str] = []
    preexisting_collection_errors: list[str] = []
    new_test_failures: list[str] = []
    new_collection_errors: list[str] = []
    if comparison and comparison.get("preexisting_failures"):
        for item in comparison["preexisting_failures"]:
            if _is_collection_error(item):
                preexisting_collection_errors.append(item)
            else:
                preexisting_test_failures.append(item)
    if comparison and comparison.get("new_failures"):
        for item in comparison["new_failures"]:
            if _is_collection_error(item):
                new_collection_errors.append(item)
            else:
                new_test_failures.append(item)

    improved_items: list[str] = comparison.get("fixed_failures", []) if comparison else []

    if status == "passed" and verdict in ("no_regression", "improvement", "all_passing"):
        header = "## Test results\n\n✅ No regression introduced."
        sub_parts = []
        if tests.get("passed", 0) > 0:
            sub_parts.append(f"- {tests['passed']} tests passing")
        if preexisting_test_failures:
            sub_parts.append(f"- Pre-existing test failures (NOT caused by these changes):\n  - " + "\n  - ".join(preexisting_test_failures))
        if preexisting_collection_errors:
            sub_parts.append(f"- Pre-existing collection errors (NOT caused by these changes):\n  - " + "\n  - ".join(preexisting_collection_errors))
        stats = "\n\n" + "\n".join(sub_parts) if sub_parts else ""
    elif verdict == "improvement":
        header = "## Test results\n\n✅ Improvements detected."
        sub_parts = []
        if improved_items:
            sub_parts.append(f"- Newly fixed:\n  - " + "\n  - ".join(improved_items))
        if preexisting_test_failures:
            sub_parts.append(f"- Still failing (pre-existing):\n  - " + "\n  - ".join(preexisting_test_failures))
        if preexisting_collection_errors:
            sub_parts.append(f"- Collection errors remaining (pre-existing):\n  - " + "\n  - ".join(preexisting_collection_errors))
        stats = "\n\n" + "\n".join(sub_parts) if sub_parts else ""
    elif status == "failed" and preexisting_test_failures and not preexisting_collection_errors and not new_test_failures and not new_collection_errors:
        header = "## Test results\n\n✅ No regression — all failures are pre-existing (NOT caused by these changes)."
        sub_parts = []
        if tests.get("passed", 0) > 0:
            sub_parts.append(f"- {tests['passed']} tests passing")
        sub_parts.append(f"- Pre-existing test failures:\n  - " + "\n  - ".join(preexisting_test_failures))
        stats = "\n\n" + "\n".join(sub_parts) if sub_parts else ""
    elif status == "failed" and preexisting_collection_errors and not preexisting_test_failures and not new_test_failures and not new_collection_errors:
        header = "## Test results\n\n✅ No regression — all failures are pre-existing collection errors (NOT caused by these changes)."
        sub_parts = []
        sub_parts.append(f"- Pre-existing collection errors:\n  - " + "\n  - ".join(preexisting_collection_errors))
        stats = "\n\n" + "\n".join(sub_parts) if sub_parts else ""
    elif status == "failed" and (preexisting_test_failures or preexisting_collection_errors or new_test_failures or new_collection_errors):
        header = "## Test results\n\n❌ Test suite failed — some new failures introduced alongside pre-existing ones."
        sub_parts = []
        if new_collection_errors:
            sub_parts.append(f"- NEW collection errors (caused by these changes):\n  - " + "\n  - ".join(new_collection_errors))
        if new_test_failures:
            sub_parts.append(f"- NEW test failures (caused by these changes):\n  - " + "\n  - ".join(new_test_failures))
        if preexisting_test_failures:
            sub_parts.append(f"- Pre-existing test failures (NOT caused by these changes):\n  - " + "\n  - ".join(preexisting_test_failures))
        if preexisting_collection_errors:
            sub_parts.append(f"- Pre-existing collection errors (NOT caused by these changes):\n  - " + "\n  - ".join(preexisting_collection_errors))
        stats = "\n\n" + "\n".join(sub_parts) if sub_parts else ""
    elif status == "passed" and verdict == "baseline_unknown":
        header = "## Test results\n\n✅ Test suite passed against bumped dependencies (no baseline available)."
        stats = ""
    elif status == "failed" and not preexisting_test_failures and not preexisting_collection_errors and not new_test_failures and not new_collection_errors:
        header = "## Test results\n\n❌ Test suite FAILED against bumped dependencies."
        stats = ""
    elif status == "no_tests":
        header = f"## Test results\n\n⚠️ No test suite detected ({test_result.get('reason', '')})."
        stats = ""
    elif status == "error":
        header = f"## Test results\n\n⚠️ Test runner errored at stage `{test_result.get('stage', '?')}` — could not verify."
        stats = ""
    else:
        header = f"## Test results\n\nUnknown status: {status}"
        stats = ""

    if tests and not stats.startswith("\n\n-"):
        stats += (
            f"\n\n- Passed: {tests.get('passed', 0)}"
            f"\n- Failed: {tests.get('failed', 0)}"
            f"\n- Errors: {tests.get('errors', 0)}"
            f"\n- Skipped: {tests.get('skipped', 0)}"
            f"\n- Duration: {tests.get('duration_s', 0)}s"
        )

    details = ""
    if stdout_tail:
        details = (
            "\n\n<details>\n<summary>pytest stdout tail</summary>\n\n"
            "```\n"
            f"{stdout_tail.strip()[-1500:]}\n"
            "```\n\n</details>"
        )

    return header + stats + details


def format_llm_fixes(fixes: list[dict]) -> str:
    """Render a markdown block for LLM-assisted fixes with diff."""
    if not fixes:
        return ""

    blocks = [
        "## LLM-assisted fixes ⚠️ REVIEW CAREFULLY\n"
        "The following changes were generated by an LLM in response to test collection errors. "
        "They are unverified — please review each diff carefully before merging."
    ]

    for fix in fixes:
        blocks.append(f"\n### {fix['file']}\n")
        blocks.append(f"**Rationale:** {fix.get('rationale', 'n/a')}\n")
        blocks.append("```diff\n")
        blocks.append(f"- {fix['search'].strip()}\n")
        blocks.append(f"+ {fix['replace'].strip()}\n")
        blocks.append("```\n")

    return "\n".join(blocks)


def generate_pr_description(
    changes: list[str],
    repo_info: dict,
    test_result: dict | None = None,
    llm_fixes: list[dict] | None = None,
    baseline_result: dict | None = None,
    comparison: dict | None = None,
) -> str:
    client = get_client()
    messages = [
        {
            "role": "user",
            "content": f"Write a PR description for modernizing repository {repo_info['owner']}/{repo_info['repo']}.\n\nChanges made:\n" + "\n".join(f"- {c}" for c in changes) + "\n\nOutput markdown. Include: (1) what was changed, (2) why, (3) what was NOT tested (e.g. manual smoke of CLI, integration with downstream services). Max 200 words. Do not oversell. Do NOT include a disclaimer, LLM-authorship section, or a 'Test results' section — those are appended automatically."
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

    llm_block = ""
    if llm_fixes:
        llm_block = "\n\n---\n\n" + format_llm_fixes(llm_fixes)

    test_block = ""
    if test_result is not None:
        test_block = "\n\n---\n\n" + format_test_results(test_result, baseline_result=baseline_result, comparison=comparison)

    return DISCLAIMER_HEADER + body + llm_block + test_block


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