"""Helper script: run pytest and write results to a file so they can be read back."""

import pathlib
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/unit/test_core.py", "--tb=short", "-q", "--no-header"],
    capture_output=True,
    text=True,
    cwd=str(pathlib.Path(__file__).parent),
)

output = result.stdout + result.stderr
out_path = pathlib.Path(__file__).parent / "pytest_results.txt"
out_path.write_text(output, encoding="utf-8")
print(f"Exit code: {result.returncode}")
print(f"Output written to: {out_path}")
sys.exit(result.returncode)
