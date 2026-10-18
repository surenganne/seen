"""Write web/openapi.json from the FastAPI app. --check fails if the committed file is stale.
The TypeScript client (web/src/api/schema.d.ts) is generated from it by `npm run gen:api`."""

import json
import sys
from pathlib import Path

from seen_local.app import create_app

OUT = Path(__file__).resolve().parents[1] / "web" / "openapi.json"
spec = json.dumps(create_app(web_dist=None).openapi(), indent=2, sort_keys=True) + "\n"
if "--check" in sys.argv:
    if not OUT.exists() or OUT.read_text() != spec:
        sys.exit("web/openapi.json is stale: run `uv run python scripts/gen_openapi.py` and `npm run gen:api`")
    print("openapi.json up to date")
else:
    OUT.write_text(spec)
    print(f"wrote {OUT}")
