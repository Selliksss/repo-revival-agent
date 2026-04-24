from pathlib import Path
import re
import tomllib
import httpx


PYPI_URL = "https://pypi.org/pypi/{package}/json"

_PIN_PATTERNS = (
    re.compile(r"^([a-zA-Z0-9_-]+)==([\d.]+)$"),
    re.compile(r"^([a-zA-Z0-9_-]+)>=([\d.]+)$"),
    re.compile(r"^([a-zA-Z0-9_-]+)<([\d.]+)$"),
    re.compile(r"^([a-zA-Z0-9_-]+)<=([\d.]+)$"),
    re.compile(r"^([a-zA-Z0-9_-]+)~=([\d.]+)$"),
    re.compile(r"^([a-zA-Z0-9_-]+)!=([\d.]+)$"),
    re.compile(r"^([a-zA-Z0-9_-]+)>=([\d.]+),<([\d.]+)$"),
)


def _get_latest_version(package: str) -> str | None:
    try:
        resp = httpx.get(PYPI_URL.format(package=package), timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data["info"]["version"]
    except Exception:
        return None


def _bump_requires_line(line: str) -> tuple[str, str | None]:
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("-") or line.startswith("-"):
        return "", None

    for pattern in _PIN_PATTERNS:
        m = pattern.match(line)
        if m:
            package = m.group(1)
            latest = _get_latest_version(package)
            if latest:
                return f"{package}>={latest}", f"{package}=={m.group(2)} → >={latest}"
            return "", None
    return "", None


def bump_requirements(repo_path: Path) -> list[str]:
    req_file = repo_path / "requirements.txt"
    if not req_file.exists():
        return []

    changes = []
    original = req_file.read_text()
    has_trailing_newline = original.endswith("\n")
    lines = original.splitlines()
    new_lines = []

    for line in lines:
        if line.strip().startswith("-r") or line.strip().startswith("-e"):
            new_lines.append(line)
            continue
        bumped, change = _bump_requires_line(line)
        if change:
            new_lines.append(bumped)
            changes.append(f"requirements.txt: {change}")
        else:
            new_lines.append(line)

    if changes:
        result = "\n".join(new_lines)
        if has_trailing_newline:
            result += "\n"
        req_file.write_text(result)
    return changes


def _bump_pyproject_deps(content: str) -> tuple[str, list[str]]:
    changes = []
    new_content = content

    dep_list_match = re.search(r"dependencies\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
    if not dep_list_match:
        return content, changes

    dep_block = dep_list_match.group(0)
    items_str = dep_list_match.group(1)

    new_items = []
    for line in items_str.splitlines():
        stripped = line.strip().strip(",").strip()
        if not stripped or stripped.startswith("#"):
            continue

        m = re.match(r'"([a-zA-Z0-9_-]+)([=!~<>]+[^"]+)"', stripped)
        if not m:
            m = re.match(r"'([a-zA-Z0-9_-]+)([=!~<>]+[^']+)'", stripped)
        if not m:
            new_items.append(line)
            continue

        package = m.group(1)
        op = m.group(2)
        latest = _get_latest_version(package)
        if latest:
            new_items.append(f'    "{package}>={latest}",')
            changes.append(f"pyproject.toml: {package}{op} → >={latest}")
        else:
            new_items.append(line)
    if changes:
        new_dep_block = "dependencies = [" + "\n".join(new_items) + "\n]"
        new_content = content.replace(dep_block, new_dep_block)
    return new_content, changes


def bump_python_version(repo_path: Path) -> list[str]:
    changes = []
    pyproject = repo_path / "pyproject.toml"
    setup_py = repo_path / "setup.py"
    setup_cfg = repo_path / "setup.cfg"

    if pyproject.exists():
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        current = None
        project = data.get("project", {})
        if "requires-python" in project:
            current = project["requires-python"]
        elif "python-requires" in project:
            current = project["python-requires"]

        new = ">=3.9"
        if current and current != new:
            content = pyproject.read_text()
            content = content.replace(f'requires-python = "{current}"', f'requires-python = "{new}"')
            content = content.replace(f"requires-python = '{current}'", f"requires-python = '{new}'")
            pyproject.write_text(content)
            changes.append(f"pyproject.toml: requires-python '{current}' → '{new}'")
        elif not current:
            content = pyproject.read_text()
            content = re.sub(
                r"(\[project\]\s*\n)",
                r"\1requires-python = \">=3.9\"\n",
                content
            )
            pyproject.write_text(content)
            changes.append("pyproject.toml: added requires-python '>=3.9'")

    elif setup_py.exists():
        with open(setup_py) as f:
            content = f.read()

        if "python_requires" in content:
            m = re.search(r"python_requires\s*=\s*[\'\"]([^\'\"]*)[\'\"]", content)
            if m:
                current = m.group(1)
                new = ">=3.9"
                if current != new:
                    content = re.sub(
                        r"python_requires\s*=\s*[\'\"][^\'\"]*[\'\"]",
                        'python_requires=">=3.9"',
                        content
                    )
                    with open(setup_py, "w") as f:
                        f.write(content)
                    changes.append(f"setup.py: python_requires '{current}' → '>=3.9'")
        else:
            content = re.sub(
                r"setup\s*\(\s*\n",
                'setup(\n    python_requires=">=3.9",\n',
                content,
                count=1,
            )
            with open(setup_py, "w") as f:
                f.write(content)
            changes.append('setup.py: added python_requires=">=3.9"')

    elif setup_cfg.exists():
        with open(setup_cfg) as f:
            content = f.read()
        m = re.search(r"python_requires\s*=\s*[\'\"]([^\'\"]*)[\'\"]", content)
        if m:
            current = m.group(1)
            new = ">=3.9"
            if current != new:
                content = re.sub(
                    r"python_requires\s*=\s*[\'\"][^\'\"]*[\'\"]",
                    f'python_requires="{new}"',
                    content
                )
                with open(setup_cfg, "w") as f:
                    f.write(content)
                changes.append(f"setup.cfg: python_requires '{current}' → '{new}'")

    return changes


def bump_dependencies(repo_path: Path) -> list[str]:
    changes = []
    changes.extend(bump_requirements(repo_path))

    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        new_content, dep_changes = _bump_pyproject_deps(content)
        if dep_changes:
            pyproject.write_text(new_content)
            changes.extend(dep_changes)

    return changes
