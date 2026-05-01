import os
import re
from pathlib import Path

# APIs from imp module that are NOT reload — used for the safety guard
IMP_OTHER_APIS = {
    "load_source", "load_compiled", "load_dynamic", "load_module",
    "find_module", "find_modules", "get_suffixes",
    "acquire_lock", "release_lock", "lock_held",
    "new_module", "is_builtin", "init_builtin",
    "get_filelte", "_NULL BytesOutput",
}


def _scan_py_files(repo_path: Path):
    """Yield all .py files in repo, skipping venvs and build artifacts."""
    skip_dirs = {".venv", ".venv-test", ".git", "build", "dist", ".egg-info"}
    for root, dirs, files in os.walk(repo_path):
        # Prune skip dirs in-place so os.walk respects them
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in files:
            if name.endswith(".py"):
                yield Path(root) / name


def fix_imp_module(repo_path: Path) -> list[str]:
    """Replace deprecated imp.reload with importlib.reload.

    Scans all *.py files, replaces the two-line Python 2 compat shim:
        import imp
        reload = imp.reload
    with:
        from importlib import reload

    SAFETY: skips files that use any imp.* API other than reload.
    Returns list of human-readable change descriptions, one per file modified.
    Empty list if nothing changed."""
    changes = []
    for path in _scan_py_files(repo_path):
        # Bug 1 fix: skip test files — symmetry with LLM-fixer policy.
        # Maintainer-owned test code is out of scope for codemods.
        if "tests" in path.parts or path.name.startswith("test_"):
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if not re.search(r"\bimport imp\b|\bfrom imp import\b|\bimp\.", text):
            continue

        # Safety guard: check for imp.<non-reload> usage
        other_usage = re.findall(r"imp\.(\w+)", text)
        for api in other_usage:
            if api not in {"reload"}:
                print(f"[codemod] skipped {path}: uses imp.{api} which is out of B-narrow scope")
                break
        else:
            # Only process if we didn't break (no non-reload imp. usage found)
            if "from importlib import reload" in text:
                continue

            # Check if this file has the reload shim pattern
            has_import_imp = re.search(r"^\s*import imp\s*$", text, re.MULTILINE)
            has_imp_reload = re.search(r"\bimp\.reload\b", text)
            has_from_imp_reload = re.search(r"\bfrom imp import.*reload\b", text)

            if not has_import_imp and not has_from_imp_reload:
                continue

            if has_from_imp_reload:
                # Replace 'from imp import ... reload' with 'from importlib import reload'
                new_text = re.sub(
                    r"from imp import.*?reload",
                    "from importlib import reload",
                    text,
                    flags=re.MULTILINE,
                )
            elif has_import_imp and has_imp_reload:
                # Match the 'import imp' line + 'reload = imp.reload' line as a unit,
                # preserving indentation of the import line (the reload line indentation
                # shifts to align with the else: block — that is the correct Python
                # alignment for the replacement). The replacement is a single
                # from importlib import reload statement at the same indentation
                # as the original import imp line.
                import_line_m = re.search(r"^(\s*)import imp\s*$", text, re.MULTILINE)
                if import_line_m:
                    indent = import_line_m.group(1)
                    # Match both lines together so we replace the pair atomically
                    pair_pattern = re.compile(
                        rf"^{re.escape(import_line_m.group(0))}\n{re.escape(indent)}reload\s*=\s*imp\.reload\b",
                        re.MULTILINE
                    )
                    new_text = pair_pattern.sub(f"{indent}from importlib import reload", text)
                    # Clean up any double blank lines created by the replacement
                    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
                else:
                    new_text = text
            else:
                continue

            if new_text != text:
                path.write_text(new_text, encoding="utf-8")
                rel = path.relative_to(repo_path)
                changes.append(f"{rel}: imp.reload → importlib.reload")

    return changes
