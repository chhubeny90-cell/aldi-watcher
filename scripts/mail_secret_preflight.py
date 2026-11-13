"""Presence-only diagnostics for the passive ALDI usage-mail workflow.

Never log credential values, lengths, hashes or substrings. This check performs
no network access and must not replace the monitor's fail-closed report.
"""
import os

_FIELDS = ("MAILBOX_2_HOST", "MAILBOX_2_USER", "MAILBOX_2_PASS")


def check_presence(environ):
    """Return only booleans; never return secret contents."""
    return {
        field: bool(environ.get(field, "").strip())
        for field in _FIELDS
    }


def main(environ=None):
    fields = check_presence(os.environ if environ is None else environ)
    for field, present in fields.items():
        print(f"[mail-preflight] {field}: {'set' if present else 'missing'}")

    if not all(fields.values()):
        print(
            "::warning title=ALDI mailbox configuration::"
            "Mailbox 2 configuration is incomplete for this workflow run. "
            "Check repository Settings > Secrets and variables > Actions for "
            "MAILBOX_2_USER and MAILBOX_2_PASS. Do not paste credentials into "
            "logs, issues or chat. Cause cannot be determined from absence alone."
        )
    else:
        print(
            "[mail-preflight] Mailbox 2 mapping is present. "
            "Presence does not prove successful IMAP authentication."
        )

    # Do not stop the monitor: it must still write its sanitized report, which
    # deliberately marks absent mailbox configuration as a failing result.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
