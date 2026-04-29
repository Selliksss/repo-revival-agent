import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env so GH_BOT_TOKEN / GH_BOT_USER are available
_env_path = Path(__file__).parents[2] / ".env"
load_dotenv(_env_path, override=True)

# Remove MiniMax proxy vars (Claude Code injects these into shell env)
os.environ.pop("ANTHROPIC_BASE_URL", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
os.environ.pop("ANTHROPIC_MODEL", None)
os.environ.pop("ANTHROPIC_SMALL_FAST_MODEL", None)
os.environ.pop("ANTHROPIC_DEFAULT_OPUS_MODEL", None)
os.environ.pop("ANTHROPIC_DEFAULT_HAIKU_MODEL", None)
os.environ.pop("ANTHROPIC_DEFAULT_SONNET_MODEL", None)


def bot_env() -> dict:
    """Return env dict with bot's GH_TOKEN for subprocess calls.
    Falls back to current env if GH_BOT_TOKEN not set (dev mode)."""
    env = os.environ.copy()
    bot_token = os.environ.get("GH_BOT_TOKEN")
    if bot_token:
        env["GH_TOKEN"] = bot_token
        env["GITHUB_TOKEN"] = bot_token
    return env


def bot_user() -> str:
    """Return bot's GitHub username from GH_BOT_USER env var.
    Fails loudly if not set — must never silently fall back to a
    personal account."""
    user = os.environ.get("GH_BOT_USER")
    if not user:
        raise RuntimeError(
            "GH_BOT_USER not set. Refusing to use a fallback identity. "
            "Set GH_BOT_USER in .env or environment before running agent actions."
        )
    return user
