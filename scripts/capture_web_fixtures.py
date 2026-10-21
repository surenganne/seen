"""Capture real API responses from a seeded scratch home, for the dashboard's page-level unit tests.

    uv run python scripts/capture_web_fixtures.py        (rewrites web/src/test/fixtures.json)

Synthetic data only: it seeds a throwaway SEEN_HOME with `devseed`, never touches ~/.seen. Lists are trimmed so the file stays small.
"""

import json
import os
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web/src/test/fixtures.json"
TRIM = 8


def trim(v):  # type: ignore[no-untyped-def]
    if isinstance(v, list):
        return [trim(x) for x in v[:TRIM]]
    if isinstance(v, dict):
        return {k: trim(x) for k, x in v.items()}
    return v


def main() -> None:
    with tempfile.TemporaryDirectory() as home:
        os.environ["SEEN_HOME"] = home
        from fastapi.testclient import TestClient

        from seen_core import devseed
        from seen_local.app import create_app

        devseed.seed(Path(home))
        c = TestClient(create_app(web_dist=None), base_url="http://localhost")
        got: dict[str, object] = {}

        def grab(path: str) -> object:
            r = c.get(path, headers={"Host": "localhost"})
            assert r.status_code == 200, (path, r.status_code, r.text[:200])
            got[path.split("?")[0]] = trim(r.json())
            return r.json()

        projects = grab("/api/projects")
        p = next(x for x in projects if x["id"] and x["name"] == "payments-api")  # type: ignore[index,union-attr]
        pid = p["id"]
        grab("/api/settings")
        grab("/api/audit/verify")
        grab("/api/skills")
        for tail in ("overview?range=7", "changes", "sessions", "timeline", "audit", "policies"):
            grab(f"/api/projects/{pid}/{tail}")
        cid = got[f"/api/projects/{pid}/changes"]["items"][0]["id"]  # type: ignore[index]
        grab(f"/api/changes/{cid}")
        grab(f"/api/projects/{pid}/provenance/files")
        grab(f"/api/projects/{pid}/provenance/file?path=src/payments/charge.py")  # the first file of demo-payments
        got["_ids"] = {"pid": pid, "cid": cid}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
        print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
