# 4. Docker runs the dashboard and team stack; hooks and CLI stay on the host

Claude Code, the repos and `~/.claude` live on the host, so hooks and the CLI run there. Docker runs
the dashboard (mock data by default, real `~/.seen` under the `local` profile on 47825), the test
suites (pytest, Playwright against a tmpfs test database) and the Phase 5 team stack.
