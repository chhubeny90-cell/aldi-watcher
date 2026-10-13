import watcher


def test_aldi_login_entry_and_protected_overview_are_distinct():
    assert watcher.ALDI_LOGIN_URL == 'https://www.alditalk-kundenportal.de/portal/auth/uebersicht/'
    assert watcher.ALDI_OVERVIEW_URL == 'https://www.alditalk-kundenportal.de/logged-in-home-page/'
    assert watcher.ALDI_LOGIN_URL != watcher.ALDI_OVERVIEW_URL
