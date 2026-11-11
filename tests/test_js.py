"""Runs the JavaScript unit tests (tests/js) with Node's built-in runner, so `pytest` covers them too."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_unit_tests():
    files = sorted(str(f.relative_to(ROOT)) for f in (ROOT / "tests" / "js").glob("*.test.js"))
    assert files, "no JavaScript tests found"
    # the files by name: older Node versions take a folder here as a module to run
    result = subprocess.run(["node", "--test", *files], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
