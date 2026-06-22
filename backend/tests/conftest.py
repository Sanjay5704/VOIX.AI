"""Pytest configuration: ensures `app` package is importable from tests/."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force CPU + non-interactive Coqui license acceptance for any test path
# that might touch device detection, without requiring a real GPU or
# interactive prompt in CI.
os.environ.setdefault("DEVICE_PREFERENCE", "cpu")
os.environ.setdefault("COQUI_TOS_AGREED", "1")
os.environ.setdefault("ENVIRONMENT", "test")
