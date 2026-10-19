# 5. Team server is a skeleton

Phase 5 is an outline in the plan. Built: strict ingest (content fields rejected), idempotent
batches, hashed project-scoped keys with roles, aggregates in the local API's shapes, append-only
audit-head anchors bound to the install's first key, auth throttle, production key guard. Not built:
SSO, retention controls, Alembic migrations for the team schema (uses create_all), managed rollout.
Per-IP lockout also refuses valid keys while locked (ExampleOrg standard 5.1: no free oracle); behind a
proxy, configure trusted X-Forwarded-For before relying on it.
