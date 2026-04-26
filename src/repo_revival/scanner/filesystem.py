from pathlib import Path
import re
import subprocess
import httpx


def detect_ci(repo_path: Path) -> dict[str, bool]:
    workflows_dir = repo_path / ".github" / "workflows"
    return {
        "github_actions": workflows_dir.exists() and any(workflows_dir.iterdir()),
        "travis": (repo_path / ".travis.yml").exists(),
        "circleci": (repo_path / ".circleci" / "config.yml").exists(),
    }


PY2_PATTERNS = [
    (re.compile(r'^\s*print\s+["\']'), "print without parentheses"),
    (re.compile(r'\bxrange\('), "xrange()"),
    (re.compile(r'\burllib2\b'), "urllib2"),
    (re.compile(r'\bfrom\s+urlparse\b'), "from urlparse"),
    (re.compile(r'\.(iteritems|itervalues|iterkeys)\('), ".iter*()"),
    (re.compile(r'\.has_key\('), ".has_key()"),
    (re.compile(r'except\s+[a-zA-Z_]\w*\s*,\s*\w+\s*:'), "old except syntax"),
]


def detect_python2_syntax(repo_path: Path) -> tuple[bool, list[str]]:
    """Scan *.py files for Python 2 syntax. Returns (found, samples)."""
    py_files = list(repo_path.rglob("*.py"))[:50]
    samples = []
    for f in py_files:
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            for pattern, desc in PY2_PATTERNS:
                if pattern.search(line):
                    rel = str(f.relative_to(repo_path))
                    samples.append(f"{rel}:{i}: {desc}")
                    if len(samples) >= 10:
                        return True, samples
    return bool(samples), samples


DEAD_DEPS = {
    "theano", "pycrypto", "gmusicapi", "msgpack-python", "python-vxi11",
    "pyobjc-framework", "librtmp", "python-ldap", "M2Crypto", "swig",
    "pycurl", "ujson", "ujson", "simplejson", "demjson", "metlog",
    "pyOpenSSL", "TLSLite", "tlslite",
}


def detect_dead_deps(repo_path: Path) -> list[str]:
    """Check requirements.txt / setup.py for known dead dependencies."""
    found = []
    for pattern_name in ["requirements*.txt", "setup.py", "setup.cfg", "pyproject.toml"]:
        for p in repo_path.glob(pattern_name):
            try:
                content = p.read_text(encoding="utf-8", errors="replace").lower()
            except Exception:
                continue
            for dep in DEAD_DEPS:
                if dep in content:
                    found.append(dep)
    return list(set(found))


SUCCESSOR_PATTERNS = [
    re.compile(r"use\s+(\w+)\s+instead", re.I),
    re.compile(r"deprecated\s+in\s+favor\s+of\s+(\w+)", re.I),
    re.compile(r"see\s+(\w+)\s+instead", re.I),
    re.compile(r"superseded\s+by\s+(\w+)", re.I),
    re.compile(r"migrat(e|ed|ing)\s+to\s+(\w+)", re.I),
    re.compile(r"consider\s+(using\s+)?(\w+)", re.I),
]


def detect_successor_mentions(repo_path: Path) -> list[str]:
    """Find mentions of alternative/successor libraries in README."""
    mentions = []
    for name in ["README.md", "README.rst", "README.txt"]:
        p = repo_path / name
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for pattern in SUCCESSOR_PATTERNS:
            for m in pattern.finditer(text):
                lib = m.group(1) or m.group(2)
                mentions.append(lib)
                if len(mentions) >= 10:
                    return mentions
    return mentions


def read_readme_excerpt(repo_path: Path, max_chars: int = 8000) -> str:
    for name in ["README.md", "README.rst", "README.txt"]:
        p = repo_path / name
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            return text[:max_chars]
    return ""


def detect_license(repo_path: Path) -> str | None:
    for name in ["LICENSE", "LICENSE.txt", "LICENSE.md", "LICENSE.rst"]:
        p = repo_path / name
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
    return None


def fetch_recent_issue_titles(owner: str, repo: str, limit: int = 5) -> list[str]:
    """Fetch titles of recent open issues via gh api."""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/issues", "--limit", str(limit), "--state", "open",
             "--jq", ".[].title"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    return []
