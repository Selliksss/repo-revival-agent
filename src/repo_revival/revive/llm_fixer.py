import os
import re
import subprocess
from pathlib import Path
from collections import Counter

from repo_revival.classifier.llm import get_client

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def attempt_loop(
    repo_path: Path,
    first_test_result: dict,
    max_attempts: int = 2,
    baseline_result: dict | None = None,
) -> dict:
    """
    Attempt to fix pytest collection errors via minimal LLM-guided edits.

    Returns:
        {
            "final_status": "passed" | "failed" | "cannot_fix",
            "fixes": list[dict],          # for PR body
            "attempts_log": list[dict],   # debug log
            "final_test_result": dict,
        }
    """
    fixes: list[dict] = []
    attempts_log: list[dict] = []
    current_test_result = first_test_result
    prev_signature: tuple | None = None

    for attempt_num in range(1, max_attempts + 1):
        errors_before = count_errors(current_test_result)

        # 1. Extract failing files and root cause details
        pytest_excerpt = _pytest_excerpt(current_test_result)
        root_causes = extract_root_causes(pytest_excerpt, repo_path)

        # 2. Filter out pre-existing failures if baseline provided
        if baseline_result:
            baseline_failed = baseline_result.get("failed_ids", [])
            baseline_error_sigs = baseline_result.get("error_signatures", [])

            if baseline_failed or baseline_error_sigs:
                # Build set of file names that had failures in baseline
                baseline_files: set[str] = set()
                for fid in baseline_failed:
                    parts = fid.split("::")[0]
                    baseline_files.add(Path(parts).name)
                for sig in baseline_error_sigs:
                    file_part = sig.split("::")[0]
                    baseline_files.add(Path(file_part).name)

                # Filter root_causes: exclude any where file.name matches baseline failure file
                new_root_causes = [rc for rc in root_causes if rc["file"].name not in baseline_files]
                if len(root_causes) != len(new_root_causes):
                    rc_removed = len(root_causes) - len(new_root_causes)
                    root_causes = new_root_causes

        top_root_cause = top_failing_root_cause(root_causes)

        if top_root_cause is None:
            log_entry = {
                "attempt_num": attempt_num,
                "file": None,
                "fix_brief": "no non-test failing files found",
                "status_after": "cannot_fix",
                "reason": "all failures in tests/ directory or pre-existing",
            }
            attempts_log.append(log_entry)
            break

        top_file = top_root_cause["file"]

        # 2. Early termination if error signature unchanged
        sig = error_signature(current_test_result, top_file)
        if prev_signature is not None and sig == prev_signature:
            log_entry = {
                "attempt_num": attempt_num,
                "file": str(top_file.relative_to(repo_path)),
                "fix_brief": "early termination: same error signature as previous attempt",
                "status_after": "unchanged",
                "reason": "signature unchanged",
            }
            attempts_log.append(log_entry)
            break
        prev_signature = sig

        # 3. LLM fix call
        relative_path = str(top_file.relative_to(repo_path))
        file_content = (repo_path / top_file).read_text(encoding="utf-8", errors="replace")
        llm_result = llm_fix_call(top_file, file_content, pytest_excerpt, root_cause=top_root_cause)

        log_entry = {
            "attempt_num": attempt_num,
            "file": relative_path,
            "fix_brief": None,
            "status_after": None,
            "rationale": llm_result.get("rationale"),
            "cannot_fix": llm_result.get("cannot_fix"),
        }
        attempts_log.append(log_entry)

        if llm_result.get("cannot_fix"):
            log_entry["fix_brief"] = f"CANNOT_FIX: {llm_result['cannot_fix']}"
            log_entry["status_after"] = "cannot_fix"
            # Don't roll back — nothing changed
            continue

        search = llm_result.get("search", "")
        replace = llm_result.get("replace", "")

        if not search or not replace:
            log_entry["fix_brief"] = "malformed response: missing search/replace"
            log_entry["status_after"] = "malformed"
            continue

        # 4. Verify match is unique
        occurrences = file_content.count(search)
        if occurrences == 0:
            log_entry["fix_brief"] = "ambiguous or missing match: search block not found in file"
            log_entry["status_after"] = "ambiguous"
            continue
        if occurrences > 1:
            log_entry["fix_brief"] = f"ambiguous match: search block found {occurrences} times"
            log_entry["status_after"] = "ambiguous"
            continue

        # 5. Backup and apply fix to disk
        original_content = file_content
        new_content = file_content.replace(search, replace, 1)
        top_file.write_text(new_content, encoding="utf-8")

        # 6. Re-run tests on disk (now with fix applied)
        new_test_result = _run_tests(repo_path)
        errors_after = count_errors(new_test_result)

        # 7. Handle outcome
        if new_test_result.get("status") == "passed":
            log_entry["fix_brief"] = f"applied: {relative_path} → passed"
            log_entry["status_after"] = "passed"
            fixes.append({
                "file": relative_path,
                "rationale": llm_result.get("rationale", ""),
                "search": search,
                "replace": replace,
            })
            current_test_result = new_test_result
            attempts_log[-1] = log_entry
            break

        if errors_after > errors_before:
            # Actively worse → revert
            top_file.write_text(original_content, encoding="utf-8")
            log_entry["fix_brief"] = f"rollback: errors increased ({errors_before} → {errors_after})"
            log_entry["status_after"] = "rolled_back"
            current_test_result = first_test_result
            continue

        # 8. Equal or fewer errors but not passed — keep file, update state for next iteration
        log_entry["fix_brief"] = f"applied, errors: {errors_before} → {errors_after}"
        log_entry["status_after"] = new_test_result.get("status")
        fixes.append({
            "file": relative_path,
            "rationale": llm_result.get("rationale", ""),
            "search": search,
            "replace": replace,
        })
        current_test_result = new_test_result

    # Determine final status
    final_status = current_test_result.get("status", "failed")
    if final_status != "passed":
        final_status = "cannot_fix"

    return {
        "final_status": final_status,
        "fixes": fixes,
        "attempts_log": attempts_log,
        "final_test_result": current_test_result,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _pytest_excerpt(test_result: dict, lines: int = 50) -> str:
    """Extract last N lines of pytest stdout from test result."""
    stdout = test_result.get("stdout_tail", "")
    if not stdout:
        return ""
    all_lines = stdout.splitlines()
    return "\n".join(all_lines[-lines:])


def extract_root_causes(pytest_output: str, repo_path: Path) -> list[dict]:
    """
    Parse pytest stdout for collection ERROR blocks.
    Returns list of root-cause dicts with file, line, code, exception_type.
    Each dict:
        {
            "file": Path,           # absolute path to failing file
            "line": int | None,     # line number from traceback ":lineno:"
            "code": str | None,     # code line content (after "→" or from next line)
            "exception_type": str | None,
        }
    """
    root_causes: list[dict] = []

    # Find all "ERROR collecting <path>" lines and their positions
    error_starts: list[tuple[int, str]] = []  # (line_index, path)
    lines = pytest_output.splitlines()
    for i, line in enumerate(lines):
        stripped = re.sub(r"_{5,}", "", line).strip()
        m = re.search(r"ERROR collecting\s+(.+)", stripped)
        if m:
            error_starts.append((i, m.group(1).strip()))

    if not error_starts:
        return []

    # For each error, find the block of lines belonging to it
    for idx, (start_idx, collection_path) in enumerate(error_starts):
        end_idx = error_starts[idx + 1][0] if idx + 1 < len(error_starts) else len(lines)
        block_lines = lines[start_idx:end_idx]
        block_text = "\n".join(block_lines)

        # Find deepest non-test .py file in this error's traceback
        deepest_file: Path | None = None
        deepest_lineno: int | None = None
        for line in reversed(block_lines):
            m = re.search(r"(\S+\.py):(\d+):", line)
            if m:
                fname = m.group(1)
                lineno = int(m.group(2))
                if ".venv" in fname:
                    continue
                full_path = repo_path / fname
                # Guard: skip if resolved path is outside the repo
                if not full_path.is_relative_to(repo_path):
                    continue
                if full_path.exists() and not _is_test_file(full_path):
                    deepest_file = full_path
                    deepest_lineno = lineno
                    break

        if deepest_file is None:
            continue

        # Extract code line: the line immediately after the ":lineno:" line
        code: str | None = None
        for i, line in enumerate(block_lines):
            if deepest_lineno is not None and re.search(rf"{deepest_lineno}:\s*in\s+<module>", line):
                if i + 1 < len(block_lines):
                    code = block_lines[i + 1].strip()
                break

        # Extract exception type from block — find last line matching exception pattern
        exception_type: str | None = None
        for line in reversed(block_lines):
            last_exc = re.search(r"^\s*(?:[\w.]+\.)?(\w+(?:Error|Exception|Operation|Failure|Interrupt)):\s+", line)
            if last_exc:
                exception_type = last_exc.group(1)
                break
        # Fallback: E-prefixed error in any line
        if exception_type is None:
            exc_m = re.search(r"E\s+(\w+Error|\w+Exception|\w+Operation|\w+Failure)", block_text)
            if exc_m:
                exception_type = exc_m.group(1)

        root_causes.append({
            "file": deepest_file,
            "line": deepest_lineno,
            "code": code,
            "exception_type": exception_type,
        })

    return root_causes


def extract_failing_files(pytest_output: str, repo_path: Path) -> list[Path]:
    """Legacy helper — now delegates to extract_root_causes."""
    root_causes = extract_root_causes(pytest_output, repo_path)
    return [rc["file"] for rc in root_causes]


def _is_test_file(path: Path) -> bool:
    """True if path is under a tests/ directory or matches test patterns."""
    parts = path.parts
    if "tests" in parts or "test_" in path.name or "_test.py" in path.name:
        return True
    for i, part in enumerate(parts):
        if part == "tests" and i > 0:
            return True
    return False


def top_failing_root_cause(root_causes: list[dict]) -> dict | None:
    """Most frequent non-test file in root_causes list, returned as full dict. None if empty."""
    if not root_causes:
        return None
    counts: Counter = Counter(str(rc["file"]) for rc in root_causes)
    top_str = counts.most_common(1)[0][0]
    for rc in root_causes:
        if str(rc["file"]) == top_str:
            return rc
    return None


def top_failing_file(failing_files: list[Path]) -> Path | None:
    """Legacy helper — now delegates to top_failing_root_cause."""
    if not failing_files:
        return None
    counts = Counter(str(p) for p in failing_files)
    most_common = counts.most_common(1)
    return Path(most_common[0][0])


def error_signature(test_result: dict, failing_file: Path) -> tuple[str, str]:
    """(failing_file_str, error_type) from pytest output."""
    pytest_output = test_result.get("stdout_tail", "")
    error_type = "unknown"
    for line in pytest_output.splitlines():
        # Look for exception class in traceback lines
        m = re.search(r"(E\s+\w+Error|UnsupportedOperation|ModuleNotFoundError|ImportError|AttributeError|TypeError|SyntaxError)", line)
        if m:
            error_type = m.group(1).lstrip("E ").strip()
            break
    return (str(failing_file), error_type)


def count_errors(test_result: dict) -> int:
    """Sum of failed + errors from test result."""
    tests = test_result.get("tests") or {}
    return tests.get("failed", 0) + tests.get("errors", 0)


def llm_fix_call(file_path: Path, file_content: str, pytest_excerpt: str, root_cause: dict | None = None) -> dict:
    """Call LLM to get a minimal fix for the given file."""
    client = get_client()
    relative_path = file_path.name  # just the filename for the prompt

    root_cause_block = ""
    if root_cause:
        parts = []
        if root_cause.get("line") is not None:
            parts.append(f"  Line {root_cause['line']}")
        if root_cause.get("code") is not None:
            parts.append(f"  Code: {root_cause['code']}")
        if root_cause.get("exception_type") is not None:
            parts.append(f"  Exception: {root_cause['exception_type']}")
        if parts:
            root_cause_block = "\nROOT CAUSE:\n" + "\n".join(parts) + "\n"

    system_prompt = """You fix Python collection errors that prevent pytest from importing test modules. You make MINIMAL changes — surgical fixes, not refactors.

IMPORTANT: prefer returning CANNOT_FIX over speculative wrapping. If you cannot identify the root cause of the failure with high confidence, return CANNOT_FIX. Do not wrap the failing line in try/except just to suppress the symptom — that masks the real bug and can introduce new failures downstream.

A genuine fix understands WHY the code fails and changes the logic or imports accordingly. A try/except around a failing line that you do not understand is not a fix; it is a bandage that will fail QA.

Return CANNOT_FIX whenever:
- You can identify the symptom but not the root cause
- The fix you would apply is just wrapping the failure in error handling
- You are unsure whether the surrounding code expects a non-None / non-error result

Output format strictly:
If you can fix the issue, respond exactly:
RATIONALE: <one sentence explaining why this fix is needed>
<<<<<<< SEARCH
<exact text from the file, must match byte-for-byte, must be unique>
=======
<replacement text>
>>>>>>> REPLACE
If you cannot safely fix, respond exactly:
CANNOT_FIX: <one sentence reason>
Rules:
- Focus your fix on the ROOT CAUSE LINE shown by the user. Do not modify other lines unless absolutely required (e.g., adding an import). If the root cause line cannot be fixed without changing module-load semantics or refactoring across files, return CANNOT_FIX.
- The SEARCH block must appear EXACTLY ONCE in the file. If unsure whether your match is unique, include more surrounding context.
- Do not invent imports unless required by your fix; if you add an import, include the import line in the SEARCH/REPLACE so it stays in the same diff.
- Keep the change as small as possible. Do not refactor unrelated code.
- If the fix requires changing more than one file, return CANNOT_FIX.
- If the file's behavior is intentionally written this way and your fix would change runtime semantics, return CANNOT_FIX."""

    user_prompt = f"""File: {relative_path}
{root_cause_block}```python
{file_content}
```
pytest collection error excerpt:

 pytest_excerpt

Provide a minimal fix or CANNOT_FIX."""

    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = ""
    for block in resp.content:
        if block.type == "text":
            text = block.text
            break

    return parse_llm_response(text)


def parse_llm_response(text: str) -> dict:
    """Parse LLM response into {rationale, search, replace, cannot_fix}."""
    if not text:
        return {"cannot_fix": "empty response from model", "rationale": None, "search": None, "replace": None}

    # CANNOT_FIX
    cannot_fix_m = re.search(r"CANNOT_FIX:\s*(.+?)(?:\n|$)", text, re.IGNORECASE | re.DOTALL)
    if cannot_fix_m:
        return {
            "cannot_fix": cannot_fix_m.group(1).strip(),
            "rationale": None,
            "search": None,
            "replace": None,
        }

    # RATIONALE
    rationale_m = re.search(r"RATIONALE:\s*(.+?)(?=\n|<)", text, re.IGNORECASE | re.DOTALL)
    rationale = rationale_m.group(1).strip() if rationale_m else ""

    # SEARCH / REPLACE block
    search_m = re.search(r"<{7} SEARCH\s*\n(.+?)\n={7}", text, re.DOTALL)
    replace_m = re.search(r"={7}\n(.+?)\n>{7}", text, re.DOTALL)

    if not search_m or not replace_m:
        return {
            "cannot_fix": "could not parse SEARCH/REPLACE block",
            "rationale": rationale or None,
            "search": None,
            "replace": None,
        }

    return {
        "cannot_fix": None,
        "rationale": rationale or "no rationale provided",
        "search": search_m.group(1),
        "replace": replace_m.group(1),
    }


def _run_tests(repo_path: Path) -> dict:
    """Re-run tester on the repo. Uses the already-created .venv-test if present."""
    # Import here to avoid circular dep — tester imports llm_fixer will not happen
    from repo_revival.revive.tester import run_tests
    return run_tests(repo_path, timeout_test=120)
