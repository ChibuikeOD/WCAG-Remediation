"""The Vercel service root must load the backend as a package."""

import os
import subprocess
import sys
from pathlib import Path

from backend.build_assets import bundle_rules
from backend.rules_engine import RulesEngine


def test_vercel_build_bundles_wcag_rules(tmp_path):
    destination = tmp_path / "rules"
    bundle_rules(destination)

    assert len(RulesEngine(rules_dir=destination).get_all_rules()) > 0


def test_vercel_entrypoint_imports_from_service_root():
    backend_dir = Path(__file__).resolve().parents[1]
    script = """
import os
import subprocess
import sys

sys.path = [os.getcwd()] + [
    path for path in sys.path if path not in ('', os.path.dirname(os.getcwd()))
]
from vercel_app import app

assert any(route.path == '/health' for route in app.routes)
probe = subprocess.run(
    [sys.executable, '-c', 'import backend.pdf_probe'],
    capture_output=True,
    text=True,
)
assert probe.returncode == 0, probe.stderr
"""
    environment = os.environ.copy()
    environment["DEPLOYMENT_MODE"] = "testing"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
