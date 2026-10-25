"""Render a German Actions summary using only fixed text and validated times."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


MESSAGES = {
    "expected_account_required": (
        "Die Ziel-SIM ist nicht eingerichtet.",
        "Das Repository-Secret `ALDI_PROFILE_1_USER` für die gewünschte SIM hinterlegen.",
    ),
    "phone_identifier_required": (
        "Die konfigurierte Rufnummer hat kein unterstütztes Format.",
        "Das Repository-Secret `ALDI_PROFILE_1_USER` prüfen.",
    ),
    "configured_account_mismatch": (
        "Die konfigurierten Rufnummern passen nicht zusammen.",
        "Die Zuordnung zur Ziel-SIM über `ALDI_PROFILE_1_USER` prüfen.",
    ),
    "password_missing": (
        "Das Passwort fehlt.",
        "Das Repository-Secret `ALDI_PASS` oder die verschlüsselte Alternative "
        "`ALDI_PASS_ENC` mit `CREDENTIAL_ENCRYPTION_KEY` hinterlegen.",
    ),
    "controlled_dispatch_required": (
        "Dieser Start erfüllt die Bedingungen für den manuellen Login nicht.",
        "Den Workflow im vorgesehenen Repository auf `main` neu starten; "
        "keinen vorhandenen Lauf wiederholen.",
    ),
    "read_only_required": (
        "Der reine Lesemodus ist nicht korrekt konfiguriert.",
        "Die Workflow-Konfiguration prüfen: `AUTO_BOOK_ENABLED` muss `false` sein.",
    ),
    "auth_guard_missing": (
        "Der gespeicherte Authentifizierungszustand fehlt.",
        "Den vorhandenen Journalzustand prüfen und wiederherstellen; "
        "keine leere Ersatzhistorie anlegen.",
    ),
    "unresolved_provider_state": (
        "Im Journal oder in der Mailqueue gibt es einen ungeklärten Vorgang.",
        "Den Vorgang anhand des gespeicherten Zustands klären, bevor ein neuer Login startet.",
    ),
    "auth_reservation_unverified": (
        "Die Reservierung des Loginversuchs konnte nicht bestätigt werden.",
        "Den gespeicherten Authentifizierungszustand prüfen; nicht sofort erneut starten.",
    ),
    "auth_backoff_active": (
        "Der 24-Stunden-Abstand ist noch aktiv. Es wurde kein Anbieterzugriff gestartet.",
        "Bis zum angegebenen Zeitpunkt warten; die Sperre nicht zurücksetzen.",
    ),
    "account_locked": (
        "Der Anbieter meldet eine Kontosperre.",
        "Die Sperre über den offiziellen ALDI-Weg klären; keine weiteren Loginversuche starten.",
    ),
    "authentication_not_completed": (
        "Der Anbieter hat die Anmeldung nicht erfolgreich abgeschlossen.",
        "Die hinterlegten Zugangsdaten und den Kontostatus über den offiziellen ALDI-Weg prüfen.",
    ),
    "additional_authentication_required": (
        "Der Anbieter verlangt einen zusätzlichen Authentifizierungsschritt.",
        "Den Zugang über den offiziellen ALDI-Weg prüfen.",
    ),
    "account_mismatch": (
        "Das angemeldete Konto passt nicht zur Ziel-SIM.",
        "Die SIM-Zuordnung prüfen; das Ergebnis nicht als erfolgreichen Login verwenden.",
    ),
}


def _utc_time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, OverflowError):
        return None


def render_summary(report):
    """Never echo arbitrary report fields, even if the report is malformed."""
    heading = "## ALDI-Login\n\n"
    if not isinstance(report, dict):
        return heading + (
            "**Login nicht bestätigt.** Es liegt kein lesbarer Ergebnisbericht vor.\n\n"
            "Nach Abbruch oder Timeout kann der Versuch bereits reserviert worden sein. "
            "Den Lauf und den gespeicherten Authentifizierungszustand prüfen; "
            "nicht sofort erneut starten.\n"
        )

    outcome = report.get("outcome")
    outcome = outcome if isinstance(outcome, str) else None
    success = (outcome == "login_verified" and report.get("login_ok") is True
               and report.get("account_match") is True)
    if success:
        paragraphs = [
            "**Login bestätigt.** Das Konto passt zur Ziel-SIM und eine geschützte "
            "Subscription-Antwort wurde geladen.",
            "Tarif und Restvolumen wurden dabei nicht geprüft. Es wurde keine Buchung ausgelöst.",
        ]
    else:
        reason, next_step = MESSAGES.get(outcome, (
            "Die Anmeldung konnte nicht bestätigt werden.",
            "Den bereinigten Ergebnisbericht und den gespeicherten Authentifizierungszustand "
            "prüfen, bevor ein neuer Versuch gestartet wird.",
        ))
        paragraphs = ["**Login nicht bestätigt.** " + reason, "Nächster Schritt: " + next_step]

    retry_after = _utc_time(report.get("retry_after"))
    reservation = report.get("reservation_status")
    if reservation == "unconfirmed":
        paragraphs.append(
            "Die Reservierung könnte bereits gespeichert sein. Den gespeicherten Zustand "
            "prüfen; nicht sofort erneut starten und die Sperre nicht zurücksetzen."
        )
        if retry_after:
            paragraphs.append("Vorgesehener Abstand bis: **" + retry_after + "**. "
                              "Dieser Zeitpunkt ist erst nach Prüfung des gespeicherten Zustands bestätigt.")
    elif reservation == "confirmed" or outcome == "auth_backoff_active":
        paragraphs.append("Der 24-Stunden-Abstand bleibt auch nach Erfolg oder Fehler bestehen.")
        if retry_after:
            paragraphs.append("Frühester nächster Versuch: **" + retry_after + "**.")
        else:
            paragraphs.append("Den frühesten nächsten Versuch im gespeicherten "
                              "Authentifizierungszustand prüfen.")
    return heading + "\n\n".join(paragraphs) + "\n"


def main():
    try:
        report = json.loads(Path(os.getenv("ALDI_HTTP_REPORT", "aldi-http-login.json"))
                            .read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        report = None
    summary = render_summary(report)
    destination = os.getenv("GITHUB_STEP_SUMMARY")
    if destination:
        try:
            with Path(destination).open("a", encoding="utf-8") as stream:
                stream.write(summary)
        except OSError:
            print("Die ALDI-Login-Zusammenfassung konnte nicht gespeichert werden.")
            return 2
    else:
        print(summary, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
