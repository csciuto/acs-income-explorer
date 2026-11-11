"""Runs the JavaScript unit tests (tests/js) with Node's built-in runner, so `pytest` covers them too."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_unit_tests():
    result = subprocess.run(["node", "--test", "tests/js/"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
