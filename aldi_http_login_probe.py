"""One browser-free login with the configured phone and password, no booking."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from core.aldi_http_login import AldiHttpLogin, LoginError
from core.credentials import get_credential


def main():
    client = AldiHttpLogin()
    report = client.report
    report.update(started_at=datetime.now(timezone.utc).isoformat(), booking_clicks=0)
    try:
        phone = get_credential("ALDI_USER")
        password = get_credential("ALDI_PASS")
        client.login(phone, password)
        report["outcome"] = "login_verified"
        return 0
    except LoginError as exc:
        report["outcome"] = str(exc)
        return 2
    except Exception as exc:
        report["outcome"] = "probe_error"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        path = Path(os.getenv("ALDI_HTTP_REPORT", "aldi-http-login.json"))
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
