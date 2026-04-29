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
                # Replace 'import imp\nreload = imp.reload' with 'from importlib import reload'
                # Remove the 'import imp' line
                new_text = re.sub(r"^\s*import imp\s*$", "", text, flags=re.MULTILINE)
                # Replace reload = imp.reload
                new_text = re.sub(r"\breload\s*=\s*imp\.reload\b", "from importlib import reload", new_text)
                # Clean up double blank lines that may result from removing 'import imp'
                new_text = re.sub(r"\n\n\n+", "\n\n", new_text)
            else:
                continue

            if new_text != text:
                path.write_text(new_text, encoding="utf-8")
                rel = path.relative_to(repo_path)
                changes.append(f"{rel}: imp.reload → importlib.reload")

    return changes
