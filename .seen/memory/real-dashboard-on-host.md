---
id: real-dashboard-on-host
type: decision
file_ref:
source_change:
verified_at:
---
The dashboard on real ~/.seen data runs on the host (SEEN_WEB_DIST=$PWD/web/dist seen serve --port 47825), never in Docker: WAL locks are not coherent across the Docker Desktop file share (ADR 0008).
