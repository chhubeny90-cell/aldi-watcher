"""Read completed LITE events and report observed timings, without provider access.

Warning-to-exhausted values measure arrival times of successive mails in the
same account/mailbox. They are not booking duration, predicted depletion time,
or evidence that the mails belong to one unchanged allowance.
"""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics


_ACCOUNT = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_CLASS = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")


def _category(value):
    return value if isinstance(value, str) and _CLASS.fullmatch(value) else "UNCLASSIFIED"


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _timings(values):
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    return {"count": len(values), "min": round(min(values), 3), "max": round(max(values), 3),
            "mean": round(statistics.mean(values), 3), "median": round(statistics.median(values), 3)}


class Report:
    def __init__(self, database_path, account=None):
        if account is not None and (not isinstance(account, str) or not _ACCOUNT.fullmatch(account)):
            raise ValueError("A logical account alias is required")
        self.path = Path(database_path).resolve()
        self.account = account

    def summarize(self, limit=10000):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("limit must be an integer from 1 to 10000")
        query = """
            SELECT account, mailbox, kind, received_at, started_at, updated_at,
                   status, error_class
            FROM lite_events WHERE state='COMPLETED'
        """
        parameters = []
        if self.account is not None:
            query += " AND account=?"
            parameters.append(self.account)
        query += " ORDER BY updated_at DESC LIMIT ?"
        parameters.append(limit)
        # No EventStore initialization: mode=ro prevents report-time schema/data writes.
        with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(row) for row in conn.execute(query, parameters)]
        statuses = Counter(_category(row["status"]) for row in rows)
        errors = Counter(_category(row["error_class"]) for row in rows if row["error_class"])
        latency = [row["updated_at"] - row["started_at"] for row in rows
                   if _finite(row["updated_at"]) and _finite(row["started_at"])
                   and row["updated_at"] >= row["started_at"]]
        intervals = []
        warnings = {}
        received = sorted((row for row in rows if _finite(row["received_at"])),
                          key=lambda row: (row["received_at"], row["kind"] != "warning80"))
        for row in received:
            key = row["account"], row["mailbox"]
            if row["kind"] == "warning80":
                warnings[key] = row["received_at"]
            elif row["kind"] == "exhausted":
                warning = warnings.pop(key, None)
                if warning is not None:
                    intervals.append(row["received_at"] - warning)
        return {
            "component": "PRO", "completed_count": len(rows), "sample_limit": limit,
            "statuses": dict(sorted(statuses.items())), "error_classes": dict(sorted(errors.items())),
            "event_latency_seconds": _timings(latency),
            "warning_to_exhausted_mail_seconds": _timings(intervals),
            "interval_basis": "latest_unpaired_warning_received_to_next_exhausted_received",
        }


def summarize(database_path, account=None, limit=10000):
    return Report(database_path, account).summarize(limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--account")
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args(argv)
    try:
        result = summarize(args.db, args.account, args.limit)
    except (OSError, sqlite3.Error, ValueError):
        print(json.dumps({"component": "PRO", "status": "CONFIG_ERROR"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
