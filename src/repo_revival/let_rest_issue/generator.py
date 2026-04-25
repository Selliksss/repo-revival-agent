from repo_revival.classifier.llm import get_client


SYSTEM_PROMPT = """You write polite, factual GitHub issues suggesting that a repository may be superseded by better-maintained alternatives. Output markdown. Include these exact sections:

## Disclaimer
Start with: 🤖 This issue was opened by repo-revival-agent, an experimental tool that analyzes inactive repositories and suggests next steps. A human reviewed this suggestion before opening. Feel free to close if not useful.

## Why this issue
Explain the context: last commit date (in years/days), and what alternatives exist with specific star counts from search results. Keep to 2-3 concise bullet points.

## Suggested actions
Offer exactly 2 options (not demands): updating the README to point to an alternative, and archiving the repository. Frame as "you might consider" not "you must".

## Acknowledgment
End with: This is a suggestion based on automated analysis. The maintainer knows their project's context better than the agent. Closing without action is a perfectly valid response.

Keep the total body under 300 words. Be factual, not emotional. Do not oversell alternatives."""


def generate_issue_body(scan_result, classification_result, search_results) -> tuple[str, str]:
    health = scan_result
    classification = classification_result

    # Format search results for the prompt
    search_context = ""
    if search_results:
        search_context = "\n\nSearch results for alternatives:\n"
        for r in search_results[:3]:
            stars = r.get("stars", "?")
            name = r.get("name", r.get("full_name", "?"))
            desc = r.get("description", "")
            search_context += f"- **{name}** ({stars} stars): {desc[:100]}\n"

    user_prompt = f"""Write a GitHub issue for repository: {classification.verdict.upper()} verdict.

Repository metrics:
- Stars: {health.stars}, Days inactive: {health.days_since_last_commit}, Archived: {health.archived}
- Languages: {", ".join(health.languages) if health.languages else "None"}
- Open issues: {health.open_issues_count}, Closed: {health.closed_issues_count}
- License: {health.license or "None"}
- Dependencies: {", ".join(d.name for d in health.dependencies) if health.dependencies else "(none detected)"}
- CI systems: {", ".join(k for k, v in health.has_ci.items() if v) if health.has_ci else "none"}
- README excerpt: {health.readme_excerpt[:300]}

Classification verdict: {classification.verdict}
Reasoning: {classification.reasoning}
Confidence: {classification.confidence:.0%}
{search_context}

Output ONLY: first line is the issue title (max 80 chars, no # prefix, format: "Suggestion: ..."), then a blank line, then the markdown body. Follow the section structure from the system prompt. Keep "Why this issue" to exactly 2 bullet points."""

    client = get_client()
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = ""
    for block in resp.content:
        if block.type == "text":
            text = block.text
            break

    lines = text.split("\n", 1)
    if len(lines) == 2:
        title = lines[0].strip()
        body = lines[1].strip()
    else:
        title = f"{health.languages[0] if health.languages else 'Repo'} repository suggestion"
        body = text

    return title, body
