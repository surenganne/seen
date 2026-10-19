---
id: regen-openapi
type: gotcha
file_ref: scripts/gen_openapi.py
source_change:
verified_at:
---
After changing an API route or schema, run uv run python scripts/gen_openapi.py && (cd web && npm run gen:api); CI fails on a stale openapi.json or web client.
