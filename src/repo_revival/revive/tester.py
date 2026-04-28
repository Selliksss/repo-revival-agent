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

    if result.returncode == 0:
        return {"status": "passed", "tests": tests, "stdout_tail": stdout_tail}
    else:
        return {
            "status": "failed",
            "tests": tests,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }
