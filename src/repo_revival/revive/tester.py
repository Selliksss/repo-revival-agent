import subprocess
import re
from pathlib import Path


def detect_tests(repo_path: Path) -> str | None:
    """Return the test configuration found, or None if no tests."""
    if (repo_path / "pytest.ini").exists():
        return "pytest.ini"
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists() and "[tool.pytest" in pyproject.read_text():
        return "pyproject.toml [tool.pytest]"
    if (repo_path / "tests").is_dir():
        return "tests/ dir"
    if list(repo_path.glob("test_*.py")):
        return "test_*.py files"
    setup_cfg = repo_path / "setup.cfg"
    if setup_cfg.exists() and "[tool:pytest]" in setup_cfg.read_text():
        return "setup.cfg [tool:pytest]"
    return None


def parse_pytest_summary(output: str) -> dict:
    """Parse pytest summary line at end of output."""
    # Extract duration first
    dur_m = re.search(r"in\s+(?P<duration>[\d.]+)s", output)
    duration = float(dur_m.group("duration")) if dur_m else None

    # Extract all count+label pairs in any order
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    pattern = re.compile(
        r"(?:(?P<passed>\d+)\s+passed)|"
        r"(?:(?P<failed>\d+)\s+failed)|"
        r"(?:(?P<errors>\d+)\s+errors?)|"
        r"(?:(?P<skipped>\d+)\s+skipped)"
    )
    for m in pattern.finditer(output):
        for k in ["passed", "failed", "errors", "skipped"]:
            if m.group(k):
                counts[k] = int(m.group(k))

    if any(counts.values()) and duration is not None:
        return {**counts, "duration_s": duration}
    return {}


def extract_collection_error_signatures(output: str) -> list[str]:
    """
    Extract collection-error signatures from pytest verbose output.

    Matches ERROR collecting blocks like:
      ___________ ERROR collecting tests/test_keypress.py ___________
      ImportError while importing test module 'tests/test_keypress.py'.
      ...
      E   ImportError: cannot import name '_getRealModule'

    Returns list of "file_path::ExceptionType" strings like:
      ["tests/test_keypress.py::ImportError", ...]
    """
    signatures: list[str] = []
    lines = output.splitlines()

    # Find all ERROR collecting blocks
    i = 0
    while i < len(lines):
        line = lines[i]
        # Match "_______ ERROR collecting <path> _______"
        m = re.search(r"_{5,}\s+ERROR collecting\s+(\S+\.py)\s+_{5,}", line)
        if m:
            file_path = m.group(1)
            # Collect this block's lines
            block_start = i
            # Find end of block: next "ERROR collecting" or end of output
            j = i + 1
            while j < len(lines) and not re.match(r"_{5,}\s+ERROR collecting", lines[j]):
                j += 1
            block = "\n".join(lines[block_start:j])

            # Find exception type: last line matching "E   <ExceptionType>:"
            exc_m = re.search(r"^E\s+((?:[\w.]+\.)*\w+(?:Error|Exception|Operation|Failure|Interrupt)):\s+", block, re.MULTILINE)
            if exc_m:
                exc_type = exc_m.group(1)
            else:
                exc_type = "CollectionError"

            signatures.append(f"{file_path}::{exc_type}")
            i = j
            continue
        i += 1

    return signatures


def parse_failed_test_ids(output: str) -> list[str]:
    """Extract FAILED test identifiers from pytest verbose output.

    Matches lines like:
      FAILED tests/test_foo.py::test_bar - AssertionError
      FAILED tests/test_foo.py::TestClass::test_baz
    Returns list of identifiers like ["tests/test_foo.py::test_bar", ...].
    """
    ids = []
    for line in output.splitlines():
        if line.startswith("FAILED "):
            # Strip the trailing " - ErrorType" part
            parts = line[len("FAILED "):].split(" - ", 1)
            test_id = parts[0]
            ids.append(test_id)
    return ids


def run_tests(repo_path: Path, timeout_install: int = 120, timeout_test: int = 300) -> dict:
    """
    Run target repo's test suite in a fresh venv with current code state.

    Returns dict:
      - {"status": "passed", "tests": {...stats...}, "stdout_tail": "..."}
      - {"status": "failed", "tests": {...stats...}, "stdout_tail": "...", "stderr_tail": "..."}
      - {"status": "no_tests", "reason": "..."}
      - {"status": "error", "stage": "venv|install|run", "stderr_tail": "..."}
    """
    test_marker = detect_tests(repo_path)
    if not test_marker:
        return {"status": "no_tests", "reason": f"no pytest config and no tests/ dir (checked: pytest.ini, [tool.pytest] in pyproject.toml, tests/, test_*.py, [tool:pytest] in setup.cfg)"}

    venv_path = repo_path / ".venv-test"

    # Step 1: create venv
    result = subprocess.run(
        ["uv", "venv", "--seed", "--clear", str(venv_path)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return {"status": "error", "stage": "venv", "stderr_tail": result.stderr[-500:]}

    pip = venv_path / "bin" / "pip"

    # Step 2: install target package in editable mode
    result = subprocess.run(
        [str(pip), "install", "-e", "."],
        cwd=repo_path, capture_output=True, text=True, timeout=timeout_install,
    )
    if result.returncode != 0:
        return {"status": "error", "stage": "install", "stderr_tail": result.stderr[-500:]}

    # Step 3: install pytest (upgrade to latest) — do this AFTER pip install -e .
    # because some repos (like pytest itself) bundle old pytest as a dep,
    # overwriting whatever version pip installed
    result = subprocess.run(
        [str(pip), "install", "pytest", "--upgrade"],
        cwd=repo_path, capture_output=True, text=True, timeout=timeout_install,
    )
    if result.returncode != 0:
        return {"status": "error", "stage": "install", "stderr_tail": result.stderr[-500:]}

    # Step 4: run pytest
    pytest_bin = venv_path / "bin" / "pytest"
    result = subprocess.run(
        [str(pytest_bin), "-v", "--tb=short"],
        cwd=repo_path, capture_output=True, text=True, timeout=timeout_test,
    )

    stdout_tail = result.stdout[-2000:] if result.stdout else ""
    stderr_tail = result.stderr[-500:] if result.stderr else ""
    tests = parse_pytest_summary(result.stdout or "")
    failed_ids = parse_failed_test_ids(result.stdout or "") if result.returncode != 0 else []
    error_sigs = extract_collection_error_signatures(result.stdout or "") if result.returncode != 0 else []

    if result.returncode == 0:
        return {"status": "passed", "tests": tests, "stdout_tail": stdout_tail}
    else:
        return {
            "status": "failed",
            "tests": tests,
            "failed_ids": failed_ids,
            "error_signatures": error_sigs,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }


def compare_results(baseline: dict, current: dict) -> dict:
    """
    Compare baseline (pre-bump) vs current (post-bump) test results.
    Handles both test failures (failed_ids) and collection errors (error_signatures).
    Collection errors are uniquely identified as "file_path::ExceptionType" strings.

    Returns dict:
      - verdict: "all_passing" | "no_regression" | "regression" | "improvement" | "baseline_unknown"
      - new_failures: list of items that failed post-bump but not pre-bump
      - fixed_failures: list of items that passed post-bump but failed pre-bump
      - preexisting_failures: list of items that failed in BOTH baseline and current
      - summary: human-readable one-liner
    """
    baseline_keys = set(baseline.get("failed_ids", [])) | set(baseline.get("error_signatures", []))
    current_keys = set(current.get("failed_ids", [])) | set(current.get("error_signatures", []))

    new_failures = sorted(current_keys - baseline_keys)
    fixed_failures = sorted(baseline_keys - current_keys)
    preexisting_failures = sorted(baseline_keys & current_keys)

    if baseline.get("status") == "no_tests":
        verdict = "baseline_unknown"
        summary = "no baseline (no tests detected pre-bump)"
    elif not current_keys and not baseline_keys:
        verdict = "all_passing"
        summary = "all tests passing in both baseline and current"
    elif not current_keys:
        verdict = "improvement"
        summary = f"tests improved: {len(fixed_failures)} previously failing now pass"
    elif not baseline_keys:
        verdict = "regression"
        summary = f"regression introduced: {len(new_failures)} new failures"
    elif new_failures and not preexisting_failures:
        verdict = "regression"
        summary = f"regression introduced: {len(new_failures)} new failures"
    elif new_failures and preexisting_failures:
        verdict = "regression"
        summary = f"regression introduced: {len(new_failures)} new + {len(preexisting_failures)} pre-existing failures"
    elif preexisting_failures and not new_failures:
        verdict = "no_regression"
        summary = f"no regression: {len(preexisting_failures)} pre-existing failure(s)"
    else:
        verdict = "no_regression"
        summary = f"no regression: baseline and current both have failures"

    return {
        "verdict": verdict,
        "new_failures": new_failures,
        "fixed_failures": fixed_failures,
        "preexisting_failures": preexisting_failures,
        "summary": summary,
    }
