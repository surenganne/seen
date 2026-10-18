"""State-changing routes. Every one writes an audit event in the same unit of work (11A rule 3)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def register(app: FastAPI, state: dict[str, Any]) -> None:
    pass
