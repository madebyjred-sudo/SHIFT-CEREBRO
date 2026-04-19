"""Cerebro SDK — Programmatic access to the CEREBRO multi-agent system.

Usage:
    from cerebro import Cerebro
    c = Cerebro(tenant="shift")
    response = c.run("¿Cuánto vendimos este mes?")
"""
from cerebro.sdk import Cerebro, CerebroResponse

__all__ = ["Cerebro", "CerebroResponse"]
__version__ = "0.1.0"
