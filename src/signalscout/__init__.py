"""SignalScout: account-level prospecting from public signals.

``seeds`` decides which companies to look at, ``jobs``, ``funding`` and ``crm`` collect public
signals about each one through a polite, cached ``fetch`` layer, ``score`` turns signals into a
tier with reasons, and ``export`` writes a Clay import, PipelineOS load files and a run report.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
