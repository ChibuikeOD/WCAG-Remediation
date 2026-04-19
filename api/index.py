import os
import sys

# Ensure repo root is on sys.path so `backend` package imports work on Vercel.
REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.main import app  # noqa: E402

