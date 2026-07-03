"""
interface/__init__.py — Grid Master OS Phase 5
Public surface of the Interface Layer.
"""
from .common import validate, run, format_result, format_error
from .api    import create_app

__all__ = ["validate", "run", "format_result", "format_error", "create_app"]
