import re
from pathlib import Path

from repo_revival.scanner.models import DependencyInfo


def parse(repo_path: Path) -> list[DependencyInfo]:
    deps = []
    for name in ["pyproject.toml", "requirements.txt", "setup.py"]:
        p = repo_path / name
        if not p.exists():
            continue
        content = p.read_text(encoding="utf-8", errors="replace")
        parsed = _parse_content(name, content)
        deps.extend(parsed)
    return deps


def _parse_content(source: str, content: str) -> list[DependencyInfo]:
    if source == "pyproject.toml":
        return _parse_pyproject(content)
    elif source == "requirements.txt":
        return _parse_requirements(content)
    elif source == "setup.py":
        return _parse_setup(content)
    return []


def _parse_pyproject(content: str) -> list[DependencyInfo]:
    deps = []
    in_deps = False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("dependencies:"):
            in_deps = True
            continue
        if in_deps:
            if line.startswith("  - "):
                name = line[4:].strip()
                deps.append(DependencyInfo(name=name, version=None, source="pyproject.toml"))
            elif line and not line.startswith(" ") and not line.startswith("#"):
                break
    return deps


def _parse_requirements(content: str) -> list[DependencyInfo]:
    deps = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"([a-zA-Z0-9_-]+)([=<>!~]+)?(.*)", line)
        if match:
            name, op, version = match.groups()
            deps.append(DependencyInfo(name=name, version=version or None, source="requirements.txt"))
    return deps


def _parse_setup(content: str) -> list[DependencyInfo]:
    deps = []
    for line in content.splitlines():
        match = re.search(r'^\s*([A-Z_]+)\s*=\s*\[(.*)\]\s*$', line)
        if match:
            varname, array_content = match.groups()
            for dep_match in re.finditer(r'["\']([a-zA-Z0-9_-]+)', array_content):
                deps.append(DependencyInfo(name=dep_match.group(1), version=None, source="setup.py"))
        elif "install_requires=" in line and "=" in line:
            m = re.search(r'install_requires\s*=\s*([A-Z_]+)', line)
            if m:
                varname = m.group(1)
                var_match = re.search(rf'^{varname}\s*=\s*\[(.*)\]', content, re.DOTALL)
                if var_match:
                    for dep_match in re.finditer(r'["\']([a-zA-Z0-9_-]+)', var_match.group(1)):
                        deps.append(DependencyInfo(name=dep_match.group(1), version=None, source="setup.py"))
    return deps