from repo_revival.scanner import scan as scanner_scan
from repo_revival.classifier import classify
from repo_revival.revive.revive import revive
from repo_revival.let_rest_issue import generator, creator


def act(repo_url: str, execute: bool = False) -> dict:
    health = scanner_scan(repo_url)
    classification = classify(repo_url)
    verdict = classification.verdict

    if verdict == "revive":
        return {"verdict": "revive", "action": "delegated to revive pipeline"}
    elif verdict == "let_rest":
        search_results = classification.search_calls
        title, body = generator.generate_issue_body(health, classification, search_results)
        if execute:
            owner = repo_url.rstrip("/").split("/")[-2]
            repo = repo_url.rstrip("/").split("/")[-1]
            url = creator.create_issue(owner, repo, title, body)
            return {"verdict": "let_rest", "action": "issue_opened", "url": url}
        return {"verdict": "let_rest", "action": "dry_run", "title": title, "body": body}
    elif verdict == "uncertain":
        return {"verdict": "uncertain", "action": "skipped, no consensus", "reasoning": classification.reasoning}
    elif verdict == "fork":
        return {"verdict": "fork", "action": "fork pipeline not implemented yet"}
