"""Hiring signals: find a company's public job board and read its open roles."""

from __future__ import annotations

from signalscout.jobs.ats import ATS_ORDER, Ats, Board, Job, board_url, fetch_board
from signalscout.jobs.discover import BoardMatch, find_board

__all__ = [
    "ATS_ORDER",
    "Ats",
    "Board",
    "BoardMatch",
    "Job",
    "board_url",
    "fetch_board",
    "find_board",
]
