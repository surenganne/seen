"""API-equivalent cost from the versioned price table (plan 9.3). Never hardcode prices."""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

_DEFAULT = Path(__file__).resolve().parents[4] / "pricing" / "prices.json"


@cache
def table(path: str | None = None) -> dict[str, Any]:
    p = Path(path or os.environ.get("SEEN_PRICES") or _DEFAULT)
    if not p.exists():  # installed package: the table ships next to the module
        p = Path(__file__).parent / "prices.json"
    data: dict[str, Any] = json.loads(p.read_text())
    return data


def cost(usage: dict[str, dict[str, int]]) -> tuple[float | None, str]:
    """Sum over models of tokens/1e6 x price. None if any model is not priced."""
    t = table()
    total = 0.0
    for model, u in usage.items():
        pr = t["models"].get(model)
        if pr is None:
            return None, t["version"]
        cw_5m, cw_1h = u.get("cw_5m", 0), u.get("cw_1h", 0)
        cw_other = max(0, u.get("tok_cache_write", 0) - cw_5m - cw_1h)  # unsplit writes priced as 5m
        total += (u.get("tok_in", 0) * pr["input"] + u.get("tok_out", 0) * pr["output"]
                  + u.get("tok_cache_read", 0) * pr["cache_read"]
                  + (cw_5m + cw_other) * pr["cache_write_5m"] + cw_1h * pr["cache_write_1h"]) / 1e6
    return round(total, 6), t["version"]
