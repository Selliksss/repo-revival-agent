import subprocess


def fetch_repo_metadata(owner: str, repo: str) -> dict:
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}", "--jq", "{stargazers_count, archived, default_branch, license, language}"],
        capture_output=True, text=True, check=True
    )
    return _parse_jq_json(result.stdout)


def fetch_languages(owner: str, repo: str) -> list[str]:
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/languages"],
        capture_output=True, text=True, check=True
    )
    import json
    lang_dict = json.loads(result.stdout)
    return sorted(lang_dict.keys(), key=lambda k: lang_dict[k], reverse=True)


def fetch_open_issues_count(owner: str, repo: str) -> int:
    return _search_count(owner, repo, "is:issue+is:open")


def fetch_closed_issues_count(owner: str, repo: str) -> int:
    return _search_count(owner, repo, "is:issue+is:closed")


def fetch_open_prs_count(owner: str, repo: str) -> int:
    return _search_count(owner, repo, "is:pr+is:open")


def _search_count(owner: str, repo: str, query_suffix: str) -> int:
    query = f"repo:{owner}/{repo}+{query_suffix}"
    result = subprocess.run(
        ["gh", "api", f"search/issues?q={query}", "--jq", ".total_count"],
        capture_output=True, text=True, check=True
    )
    return int(result.stdout.strip())


def _parse_jq_json(output: str) -> dict:
    """Parse --jq output that is a JSON object without outer quotes."""
    import json
    return json.loads(output)


def _parse_jq_keys(output: str) -> list[str]:
    """Parse --jq keys output which is newline-separated keys."""
    return [line.strip() for line in output.splitlines() if line.strip()]