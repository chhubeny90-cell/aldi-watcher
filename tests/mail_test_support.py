"""Keep notification/dedup unit tests independent of cursor storage.

Real cursor restart, backlog and CAS behavior are covered by test_mailbox_cursor.
This fixture deliberately rescans so those tests can exercise retained-history
migration and dedup even when the transport presents the same UID again.
"""


class RescanningCursor:
    backlog = 0
    validity_changed = False

    def __init__(self, host, user, client):
        self.client = client

    def batch(self):
        status, values = self.client.uid('search', None, 'SINCE', '01-Jan-2026',
                                         'FROM', 'alditalk-kundenbetreuung.de')
        if status != 'OK':
            raise RuntimeError('mailbox_uid_search_failed')
        return values[0].split()

    def commit(self):
        pass
