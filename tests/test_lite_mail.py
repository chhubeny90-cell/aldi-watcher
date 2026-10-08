import base64
import copy
import io
import json
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from lite.mail import GmailClient, GmailError, HistoryExpired, MailboxMismatch, MessageUnavailable, parse_gmail_message


MAILBOX = "test-aldi@gmail.com"
ACCOUNT = "aldi-main"
WARNING = "Du hast 80% des Datenvolumens in der aktuellen Optionslaufzeit genutzt."
EXHAUSTED = "Das Datenvolumen deines Tarifs oder einer Zusatz-Option ist verbraucht."
AUTH = ("mx.google.com; dkim=pass header.i=@alditalk-kundenbetreuung.de header.s=s1-rsa; "
        "spf=pass (google.com: sender permitted) smtp.mailfrom=noreply@bounce.alditalk-kundenbetreuung.de; "
        "dmarc=pass (p=NONE) header.from=alditalk-kundenbetreuung.de")


def message(body=WARNING, mime="text/plain", mail_id="1a114817dd90a3b2"):
    return {"id": mail_id, "internalDate": str(int((time.time() - 30) * 1000)),
            "labelIds": ["INBOX"], "payload": {
                "mimeType": mime,
                "headers": [
                    {"name": "Delivered-To", "value": MAILBOX},
                    {"name": "From", "value": "ALDI TALK Kundenbetreuung <noreply@alditalk-kundenbetreuung.de>"},
                    {"name": "Subject", "value": "Verbrauch deines Datenvolumens"},
                    {"name": "Authentication-Results", "value": AUTH},
                    {"name": "DKIM-Signature", "value": "v=1; a=rsa-sha256; d=alditalk-kundenbetreuung.de; s=s1-rsa; b=test"},
                ], "body": {"data": base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")}
            }}


def set_header(mail, name, value):
    for header in mail["payload"]["headers"]:
        if header["name"].lower() == name.lower():
            header["value"] = value
            return
    mail["payload"]["headers"].append({"name": name, "value": value})


@pytest.mark.parametrize("body,kind", [
    (WARNING, "warning80"),
    (WARNING.replace("80%", "80 %"), "warning80"),
    (WARNING.replace("80%", "80\u00a0%"), "warning80"),
    (EXHAUSTED, "exhausted"),
    (EXHAUSTED.replace("Zusatz-Option", "Zusatz\u2011Option"), "exhausted"),
])
def test_real_german_warning_and_exhaustion_text(body, kind):
    event = parse_gmail_message(message(body), MAILBOX, ACCOUNT)
    assert event.kind == kind
    assert event.account == ACCOUNT
    assert event.mailbox == MAILBOX
    assert event.received_at > time.time() - 60


def test_connector_representation_with_html_is_supported():
    mail = message()
    mail["internal_date"] = mail.pop("internalDate")
    mail["label_ids"] = mail.pop("labelIds")
    mail["payload"]["mime_type"] = "text/html"
    del mail["payload"]["mimeType"]
    mail["payload"]["body"] = {"content": "<style>.ignored{}</style><p>Hinweis: " + WARNING + "</p>"}
    assert parse_gmail_message(mail, MAILBOX, ACCOUNT).kind == "warning80"


def test_multipart_html_decodes_bodies_but_ignores_attachments():
    mail = message()
    mail["payload"]["mimeType"] = "multipart/mixed"
    mail["payload"]["body"] = {}
    mail["payload"]["parts"] = [
        {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(EXHAUSTED.encode()).decode()}},
            {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(
                ("<html><head><style>" + WARNING + "</style></head><body><p>" + EXHAUSTED + "</p></body></html>").encode()).decode()}},
        ]},
        {"mimeType": "text/plain", "filename": "forward.txt", "body": {"content": WARNING}},
    ]
    assert parse_gmail_message(mail, MAILBOX, ACCOUNT).kind == "exhausted"


@pytest.mark.parametrize("sender", [
    "noreply@alditalk-kundenbetreuung.de.evil.test",
    "ALDI <attacker@example.com>",
    "ALDI <noreply@alditalk-kundenbetreuung.de>, attacker@example.com",
])
def test_forged_or_multiple_sender_is_rejected(sender):
    mail = message()
    set_header(mail, "From", sender)
    assert parse_gmail_message(mail, MAILBOX, ACCOUNT) is None


@pytest.mark.parametrize("header,value", [
    ("Subject", "Re: Verbrauch deines Datenvolumens"),
    ("Delivered-To", "other-account@gmail.com"),
    ("Authentication-Results", AUTH.replace("dkim=pass", "dkim=fail")),
    ("Authentication-Results", AUTH.replace("spf=pass", "spf=fail")),
    ("Authentication-Results", AUTH.replace("dmarc=pass", "dmarc=fail")),
    ("Authentication-Results", AUTH.replace("mx.google.com", "attacker.example")),
    ("Authentication-Results", AUTH.replace("@alditalk-kundenbetreuung.de", "@attacker.example")),
    ("DKIM-Signature", "v=1; d=attacker.example; b=test"),
])
def test_wrong_subject_account_or_authentication_is_rejected(header, value):
    mail = message()
    set_header(mail, header, value)
    assert parse_gmail_message(mail, MAILBOX, ACCOUNT) is None


@pytest.mark.parametrize("name", ["Authentication-Results", "DKIM-Signature"])
def test_missing_received_authentication_or_signature_is_rejected(name):
    mail = message()
    mail["payload"]["headers"] = [header for header in mail["payload"]["headers"] if header["name"] != name]
    assert parse_gmail_message(mail, MAILBOX, ACCOUNT) is None


def test_quoted_fake_authentication_header_is_not_trusted():
    mail = message("Authentication-Results: " + AUTH + "\n" + EXHAUSTED)
    mail["payload"]["headers"] = [header for header in mail["payload"]["headers"]
                                    if header["name"] not in {"Authentication-Results", "DKIM-Signature"}]
    mail["payload"]["headers"].append({"name": "ARC-Authentication-Results", "value": "i=1; " + AUTH})
    assert parse_gmail_message(mail, MAILBOX, ACCOUNT) is None


def test_later_forged_authentication_pass_does_not_override_first_failure():
    mail = message()
    set_header(mail, "Authentication-Results", AUTH.replace("dmarc=pass", "dmarc=fail"))
    mail["payload"]["headers"].append({"name": "Authentication-Results", "value": AUTH})
    assert parse_gmail_message(mail, MAILBOX, ACCOUNT) is None


@pytest.mark.parametrize("body", ["Eine Rechnung ist eingetroffen.", WARNING + " " + EXHAUSTED])
def test_unrelated_or_conflicting_body_does_not_trigger(body):
    assert parse_gmail_message(message(body), MAILBOX, ACCOUNT) is None


def test_forwarded_attached_mail_is_not_a_trigger():
    mail = message()
    mail["payload"]["mimeType"] = "multipart/mixed"
    mail["payload"]["body"] = {}
    mail["payload"]["parts"] = [{"mimeType": "message/rfc822", "parts": [message(EXHAUSTED)["payload"]]}]
    assert parse_gmail_message(mail, MAILBOX, ACCOUNT) is None


def test_event_key_is_mailbox_plus_immutable_gmail_id_and_greeting_does_not_map_account():
    first = parse_gmail_message(message("Guten Tag andere Person, " + WARNING), MAILBOX, ACCOUNT)
    repeated = parse_gmail_message(message(WARNING), MAILBOX.upper(), ACCOUNT)
    assert first.event_id == repeated.event_id
    assert first.account == ACCOUNT
    other = message(WARNING, mail_id="f123")
    assert parse_gmail_message(other, MAILBOX, ACCOUNT).event_id != first.event_id
    with pytest.raises(ValueError, match="explicit_account_alias_required"):
        parse_gmail_message(message(), MAILBOX, "")


@pytest.mark.parametrize("field,value", [("internalDate", "bad"), ("internalDate", "0"), ("id", "invalid/path")])
def test_malformed_identity_or_date_is_rejected(field, value):
    mail = message()
    mail[field] = value
    assert parse_gmail_message(mail, MAILBOX, ACCOUNT) is None


class FakeClient(GmailClient):
    def __init__(self, pages, messages=None, profile_mailbox=MAILBOX):
        self.mailbox = MAILBOX
        self._verified = False
        self.pages = list(pages)
        self.messages = messages or {}
        self.profile_mailbox = profile_mailbox
        self.calls = []

    def _request(self, path, params=None, body=None):
        self.calls.append((path, params, body))
        if path == "/profile":
            return {"emailAddress": self.profile_mailbox, "historyId": "100"}
        if path.startswith("/messages/"):
            result = self.messages[path.rsplit("/", 1)[1]]
            if isinstance(result, Exception):
                raise result
            return copy.deepcopy(result)
        result = self.pages.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def added(mail_id):
    return {"message": {"id": mail_id}}


def test_history_pagination_only_message_added_deduplicates_and_returns_durable_cursor():
    warning, exhaustion = message(), message(EXHAUSTED, mail_id="abc123")
    exhaustion["internalDate"] = str(int(warning["internalDate"]) + 1000)
    pages = [
        {"historyId": "120", "nextPageToken": "next", "history": [
            {"id": "110", "messagesAdded": [added(warning["id"])],
             "labelsAdded": [added("ffff")]},
        ]},
        {"historyId": "125", "history": [
            {"id": "111", "messagesAdded": [added(warning["id"]), added(exhaustion["id"])]},
        ]},
    ]
    client = FakeClient(pages, {warning["id"]: warning, exhaustion["id"]: exhaustion})
    events, cursor = client.events_since("100", ACCOUNT)
    assert [event.kind for event in events] == ["warning80", "exhausted"]
    assert cursor == "125"
    assert len([call for call in client.calls if call[0].startswith("/messages/")]) == 2
    assert client.calls[-2][1]["pageToken"] == "next"
    assert client.calls[1][1]["historyTypes"] == "messageAdded"


def test_stale_history_is_explicit_and_does_not_replay():
    client = FakeClient([HistoryExpired("gmail_history_expired")])
    with pytest.raises(HistoryExpired):
        client.events_since("100", ACCOUNT)
    assert all(call[0] != "/messages" for call in client.calls)


def test_message_deleted_between_history_and_read_does_not_block_remaining_events():
    live = message(EXHAUSTED)
    client = FakeClient([{"historyId": "120", "history": [
        {"id": "110", "messagesAdded": [added("abc123"), added(live["id"])]}]}],
        {"abc123": MessageUnavailable("gmail_message_unavailable"), live["id"]: live})
    events, cursor = client.events_since("100", ACCOUNT)
    assert [event.kind for event in events] == ["exhausted"]
    assert cursor == "120"


def test_oauth_mailbox_mismatch_prevents_reads_or_watch():
    client = FakeClient([], profile_mailbox="another@gmail.com")
    with pytest.raises(MailboxMismatch):
        client.read_message("abc123")
    assert [call[0] for call in client.calls] == ["/profile"]


def test_repeated_pagination_token_is_rejected_without_infinite_loop():
    client = FakeClient([{"historyId": "101", "nextPageToken": "repeat"},
                         {"historyId": "102", "nextPageToken": "repeat"}])
    with pytest.raises(GmailError, match="pagination_invalid"):
        client.events_since("100", ACCOUNT)


def test_scan_recent_is_bounded_and_rejects_older_messages():
    recent, old = message(), message(EXHAUSTED, mail_id="abc123")
    old["internalDate"] = str(int((time.time() - 2 * 86400) * 1000))
    client = FakeClient([{"messages": [added(recent["id"])["message"], {"id": old["id"]},
                                      {"id": recent["id"]}]}], {recent["id"]: recent, old["id"]: old})
    assert len(client.scan_recent(ACCOUNT, max_results=3)) == 1
    assert client.calls[1][1]["maxResults"] == 3
    assert "from:noreply@alditalk-kundenbetreuung.de" in client.calls[1][1]["q"]


class JsonResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode())


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return JsonResponse(response)


def client_with_opener(opener):
    return GmailClient(MAILBOX, "test-client", "test-secret", "test-refresh", opener=opener)


def test_refresh_credentials_are_form_encoded_and_profile_is_verified():
    opener = Opener([{"access_token": "test-access", "expires_in": 3600},
                     {"emailAddress": MAILBOX, "historyId": "100"}])
    client_with_opener(opener).get_profile()
    assert opener.requests[0].full_url == "https://oauth2.googleapis.com/token"
    assert parse_qs(opener.requests[0].data.decode())["grant_type"] == ["refresh_token"]
    assert opener.requests[1].get_header("Authorization") == "Bearer test-access"
    assert urlsplit(opener.requests[1].full_url).path.endswith("/users/me/profile")


def test_http_error_payload_does_not_disclose_credentials():
    error = HTTPError("https://oauth2.googleapis.com/token", 400, "secret-payload", {},
                      io.BytesIO(b'{"error":"test-secret test-refresh"}'))
    client = client_with_opener(Opener([error]))
    with pytest.raises(GmailError) as captured:
        client.get_profile()
    assert str(captured.value) == "gmail_oauth_http_400"


def test_real_history_http_404_is_classified_without_replay():
    error = HTTPError("https://gmail.googleapis.com/gmail/v1/users/me/history", 404, "gone", {}, io.BytesIO(b"private"))
    client = client_with_opener(Opener([{"access_token": "test-access", "expires_in": 3600},
                                       {"emailAddress": MAILBOX, "historyId": "100"}, error]))
    with pytest.raises(HistoryExpired, match="gmail_history_expired"):
        client.events_since("99", ACCOUNT)


def test_explicit_watch_uses_verified_official_endpoint_and_topic_only():
    client = FakeClient([{"historyId": "120", "expiration": "1791449000000"}])
    assert client.watch("projects/test-project/topics/aldi-mail")["historyId"] == "120"
    assert client.calls[-1] == ("/watch", None, {"topicName": "projects/test-project/topics/aldi-mail"})
