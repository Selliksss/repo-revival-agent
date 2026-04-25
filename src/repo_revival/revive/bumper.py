from pathlib import Path
import re
import ast
import configparser
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

_PY2_SIGNS = [
    (re.compile(r'^\s*print\s+["\']'), "print without parentheses"),
    (re.compile(r'\bxrange\('), "xrange()"),
    (re.compile(r'\burllib2\b'), "urllib2"),
    (re.compile(r'\bfrom\s+urlparse\b'), "from urlparse"),
    (re.compile(r'\.(iteritems|itervalues|iterkeys)\('), ".iter*()"),
    (re.compile(r'\.has_key\('), ".has_key()"),
    (re.compile(r'except\s+[a-zA-Z_]\w*\s*,\s*\w+\s*:'), "old except syntax"),
]


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
    line_orig = line
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("-"):
        return line_orig, None

    for pattern in _PIN_PATTERNS:
        m = pattern.match(line)
        if m:
            package = m.group(1)
            latest = _get_latest_version(package)
            if latest:
                return f"{package}>={latest}", f"{package}=={m.group(2)} → >={latest}"
            return line_orig, None
    return line_orig, None


def detect_python2_signs(repo_path: Path) -> list[str]:
    """Find Python 2 patterns in .py files. Returns list of 'file:line: description'."""
    py_files = list(repo_path.rglob("*.py"))
    py_files = py_files[:50]

    findings = []
    for f in py_files:
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            for pattern, desc in _PY2_SIGNS:
                if pattern.search(line):
                    fname = str(f.relative_to(repo_path))
                    findings.append(f"{fname}:{i}: {desc}")
                    break
            if len(findings) >= 20:
                return findings
    return findings


def _bump_install_requires_literal(content: str) -> tuple[str, list[str]]:
    """Handle install_requires=[...] literal."""
    changes = []
    install_requires_match = re.search(r"install_requires\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
    if not install_requires_match:
        return content, changes

    block = install_requires_match.group(0)
    inner = install_requires_match.group(1)

    new_inner_lines = []
    for line in inner.splitlines():
        stripped = line.strip().strip(",").strip()
        if not stripped or stripped.startswith("#"):
            new_inner_lines.append(line)
            continue

        m = re.match(r"['\"]([a-zA-Z0-9_.-]+)\s*([=<>!~]+)\s*([\d.]+)['\"]", stripped)
        if not m:
            new_inner_lines.append(line)
            continue

        package = m.group(1)
        op = m.group(2)
        if op not in ("==", "<", "<=", "~=", "!="):
            new_inner_lines.append(line)
            continue

        latest = _get_latest_version(package)
        if latest:
            new_line = line.replace(f"{package}{op}{m.group(3)}", f"{package}>={latest}")
            new_inner_lines.append(new_line)
            changes.append(f"setup.py: {package}{op}{m.group(3)} → >={latest}")
        else:
            new_inner_lines.append(line)

    if changes:
        new_block = "install_requires=[" + "".join(new_inner_lines) + "]"
        content = content.replace(block, new_block)

    return content, changes


def parse_install_requires_ast(repo_path: Path) -> tuple[list[str], dict] | None:
    """Try AST parsing for install_requires=VAR pattern.

    Returns (deps_list, var_info) if found, None otherwise.
    deps_list: list of dependency specs like ["foo==1.2", "bar>=3.0"]
    var_info: dict with name, lineno, end_lineno
    """
    setup_py = repo_path / "setup.py"
    if not setup_py.exists():
        return None

    try:
        tree = ast.parse(setup_py.read_text(encoding="utf-8"), filename="setup.py")
    except Exception:
        return None

    # Find module-level assignments: NAME = [...]
    module_assigns = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if isinstance(node.value, (ast.List, ast.ListComp)):
                # Collect string literals from the list
                elts = []
                if isinstance(node.value, ast.List):
                    elts = node.value.elts
                elif isinstance(node.value, ast.ListComp):
                    # Skip complex comprehensions
                    continue
                string_vals = []
                for elt in elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        string_vals.append(elt.value)
                    elif isinstance(elt, ast.FormattedValue):
                        continue
                if string_vals:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            module_assigns[target.id] = string_vals
                            break

    # Find setup() call and its install_requires keyword
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "setup":
                for keyword in node.keywords:
                    if keyword.arg == "install_requires":
                        value = keyword.value
                        if isinstance(value, ast.Name):
                            # Variable indirection: install_requires=NAME
                            var_name = value.id
                            if var_name in module_assigns:
                                # Get line numbers from the assignment
                                for assign_node in ast.walk(tree):
                                    if isinstance(assign_node, ast.Assign):
                                        for target in assign_node.targets:
                                            if isinstance(target, ast.Name) and target.id == var_name:
                                                return (
                                                    module_assigns[var_name],
                                                    {
                                                        "name": var_name,
                                                        "lineno": assign_node.lineno,
                                                        "end_lineno": getattr(assign_node, "end_lineno", assign_node.lineno + 1),
                                                    },
                                                )
                        elif isinstance(value, ast.List):
                            # Literal list: install_requires=[...] — let regex handle it
                            return None
                        else:
                            # Complex expression — skip
                            return None
                break

    return None


def _bump_variable_deps(content: str, deps: list[str], var_info: dict) -> tuple[str, list[str]]:
    """Bump deps that are pinned in a variable assignment."""
    changes = []
    new_deps = []
    for dep in deps:
        m = re.match(r"([a-zA-Z0-9_.-]+)\s*([=<>!~]+)\s*([\d.]+)", dep.strip())
        if m:
            package = m.group(1)
            op = m.group(2)
            if op in ("==", "<", "<=", "~=", "!="):
                latest = _get_latest_version(package)
                if latest:
                    new_deps.append(f"{package}>={latest}")
                    changes.append(f"{var_info['name']}: {package}{op}{m.group(3)} → >={latest}")
                else:
                    new_deps.append(dep)
            else:
                new_deps.append(dep)
        else:
            new_deps.append(dep)

    if changes:
        # Replace the variable assignment in content
        lines = content.splitlines(keepends=True)
        start = var_info["lineno"] - 1
        end = var_info.get("end_lineno", var_info["lineno"])
        indent = len(lines[start]) - len(lines[start].lstrip()) if lines[start].strip() else 0
        indent_str = " " * indent

        new_assignment_lines = [f"{indent_str}{var_info['name']} = ["]
        for d in new_deps:
            new_assignment_lines.append(f'{indent_str}    "{d}",')
        new_assignment_lines.append(f"{indent_str}]")

        new_lines = lines[:start] + ["\n".join(new_assignment_lines) + "\n"] + lines[end:]
        content = "".join(new_lines)

    return content, changes


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

        # Handle install_requires: try literal first, then AST
        new_content, dep_changes = _bump_install_requires_literal(content)
        if not dep_changes:
            # Try AST path for variable indirection
            result = parse_install_requires_ast(repo_path)
            if result:
                deps, var_info = result
                new_content, dep_changes = _bump_variable_deps(content, deps, var_info)
        if dep_changes:
            content = new_content
            changes.extend(dep_changes)

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
                    changes.append(f"setup.py: python_requires '{current}' → '>=3.9'")
        else:
            content = re.sub(
                r"setup\s*\(\s*\n",
                'setup(\n    python_requires=">=3.9",\n',
                content,
                count=1,
            )
            changes.append('setup.py: added python_requires=">=3.9"')

        with open(setup_py, "w") as f:
            f.write(content)

    elif setup_cfg.exists():
        cfg = configparser.ConfigParser()
        cfg.read(repo_path / "setup.cfg")

        needs_write = False
        if cfg.has_section("options"):
            if cfg.has_option("options", "python_requires"):
                current = cfg.get("options", "python_requires")
                new = ">=3.9"
                if current != new:
                    cfg.set("options", "python_requires", new)
                    needs_write = True
                    changes.append(f"setup.cfg: python_requires '{current}' → '{new}'")
            elif cfg.has_option("options", "install_requires"):
                cfg.set("options", "python_requires", ">=3.9")
                needs_write = True
                changes.append("setup.cfg: added python_requires '>=3.9'")

            if cfg.has_option("options", "install_requires"):
                raw_requires = cfg.get("options", "install_requires")
                req_lines = [l.strip() for l in raw_requires.split("\n") if l.strip()]
                new_req_lines = []
                req_changes = []
                for line in req_lines:
                    m = re.match(r"([a-zA-Z0-9_.-]+)\s*([=<>!~]+)\s*([\d.]+)", line)
                    if m:
                        package = m.group(1)
                        op = m.group(2)
                        latest = _get_latest_version(package)
                        if latest and op in ("==", "<", "<=", "~=", "!="):
                            new_req_lines.append(f"{package}>={latest}")
                            req_changes.append(f"setup.cfg: {package}{op}{m.group(3)} → >={latest}")
                        else:
                            new_req_lines.append(line)
                    else:
                        new_req_lines.append(line)
                if req_changes:
                    cfg.set("options", "install_requires", "\n" + "\n".join(new_req_lines))
                    needs_write = True
                    changes.extend(req_changes)

        if needs_write:
            with open(setup_cfg, "w") as f:
                cfg.write(f)

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
