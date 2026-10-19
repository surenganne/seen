"""Container healthcheck: the API answers (401 without a key is healthy)."""

import urllib.error
import urllib.request

try:
    urllib.request.urlopen("http://127.0.0.1:47824/api/projects", timeout=2)
except urllib.error.HTTPError as e:
    raise SystemExit(0 if e.code == 401 else 1) from None
except OSError:
    raise SystemExit(1) from None
