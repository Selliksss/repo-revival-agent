import json
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

from repo_revival.classifier.prompts import SYSTEM_PROMPT, FEW_SHOT

# Load .env once at module import — override shell env vars (Claude Code MiniMax proxy)
_env_path = Path(__file__).parents[2] / ".env"
load_dotenv(_env_path, override=True)

# Remove MiniMax proxy vars — subprocess must talk directly to api.anthropic.com
os.environ.pop("ANTHROPIC_BASE_URL", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
os.environ.pop("ANTHROPIC_MODEL", None)
os.environ.pop("ANTHROPIC_SMALL_FAST_MODEL", None)
os.environ.pop("ANTHROPIC_DEFAULT_SONNET_MODEL", None)
os.environ.pop("ANTHROPIC_DEFAULT_OPUS_MODEL", None)
os.environ.pop("ANTHROPIC_DEFAULT_HAIKU_MODEL", None)

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
os.environ["ANTHROPIC_API_KEY"] = api_key

client = Anthropic()


def get_client() -> Anthropic:
    return client

SEARCH_SCHEMA = {
    "name": "search_github",
    "description": "Search GitHub for active alternatives to the repository being classified. Use to check if a modern replacement exists with more stars.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query for GitHub repositories"},
        },
        "required": ["query"],
    },
}

CLASSIFY_SCHEMA = {
    "name": "classify_repo",
    "description": "Output final classification of a repository",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["revive", "fork", "let_rest"]},
            "confidence": {"type": "number"},
            "reasoning": {"type": "string"},
        },
        "required": ["verdict", "confidence", "reasoning"],
    },
}


def search_github(query: str) -> list[dict]:
    if os.environ.get("REPO_REVIVAL_DEBUG"):
        print(f"[search] query={query!r}", flush=True)
    result = subprocess.run(
        [
            "gh", "api", "-X", "GET", "search/repositories",
            "-f", f"q={query}",
            "-f", "sort=stars",
            "--jq", ".items[:5] | map({name: .name, stars: .stargazers_count, pushed: .pushed_at, description: .description})",
        ],
        capture_output=True, text=True, check=True, timeout=15,
    )
    data = json.loads(result.stdout)
    if os.environ.get("REPO_REVIVAL_DEBUG"):
        print(f"[search] got {len(data)} results", flush=True)
    return data


def format_search_results(results: list[dict]) -> str:
    if not results:
        return "No alternatives found."
    lines = []
    for r in results:
        age = "recent" if r.get("pushed") and r["pushed"] > "2024-01-01" else "stale"
        lines.append(f"- {r['name']}: {r['stars']} stars, {age}, {r.get('description', 'no description')}")
    return "\n".join(lines)


def call_model(messages: list[dict]) -> list:
    return client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": FEW_SHOT, "cache_control": {"type": "ephemeral"}},
        ],
        messages=messages,
        tools=[SEARCH_SCHEMA, CLASSIFY_SCHEMA],
    ).content


def classify_with_retry(user_msg: str) -> dict:
    messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text": user_msg}]}]
    search_count = 0
    MAX_SEARCHES = 3
    MAX_ITERATIONS = 5
    search_calls: list[dict] = []

    for iteration in range(MAX_ITERATIONS):
        if os.environ.get("REPO_REVIVAL_DEBUG"):
            print(f"[iter {iteration}] calling model, messages={len(messages)}", flush=True)
        content = call_model(messages)
        if os.environ.get("REPO_REVIVAL_DEBUG"):
            print(f"[iter {iteration}] got blocks: {[b.type for b in content]}", flush=True)

        tool_use_blocks = [b for b in content if b.type == "tool_use"]
        if not tool_use_blocks:
            text_blocks = [b.text for b in content if b.type == "text"]
            raise RuntimeError(f"Model did not call any tool. Text: {text_blocks}")

        # Append the full assistant response (with thinking blocks) before tool_result
        messages.append({"role": "assistant", "content": [_block_to_dict(b) for b in content]})

        tool_results_content = []
        for block in tool_use_blocks:
            if block.name == "classify_repo":
                result = dict(block.input)
                result["search_calls"] = search_calls
                return result

            if block.name == "search_github":
                query = block.input.get("query", "")
                results = search_github(query)
                search_count += 1
                formatted = format_search_results(results)
                if search_count >= MAX_SEARCHES:
                    formatted += "\n\n[Maximum searches reached. You must now call classify_repo with your best judgment — do not call search_github again.]"
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": formatted,
                })
                search_calls.append({"query": query, "results": results[:3]})

        messages.append({"role": "user", "content": tool_results_content})

    raise RuntimeError("Failed to get classify_repo after max iterations")


def _block_to_dict(block) -> dict:
    # Preserve thinking / tool_use / text blocks across turns
    if block.type == "thinking":
        return {"type": "thinking", "thinking": block.thinking, "signature": block.signature}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if block.type == "text":
        return {"type": "text", "text": block.text}
    raise RuntimeError(f"Unknown block type: {block.type}")
