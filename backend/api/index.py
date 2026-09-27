"""Vercel serverless entrypoint for the existing CloudOps AI FastAPI app.

This adapter does not define or duplicate any routes. It only makes the
existing ``backend/main.py`` application importable by Vercel's Python
runtime and re-exports its ``app`` object.
"""

import os
import sys

# Ensure the backend package root is importable (module-level imports in
# main.py use top-level names such as ``aws_client`` and ``services``).
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from main import app  # noqa: E402,F401
