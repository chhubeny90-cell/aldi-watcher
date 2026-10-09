"""Manual read-only ALDI selector probe.

Runs exactly one authenticated portal session, performs no booking action, and
writes only sanitized structural selector candidates to selector-probe.json.
"""

import json
import os

from core.aldi_selector_probe import probe_selectors, sanitized_probe
from monitoring import write_report
import watcher


def main():
    if os.getenv('AUTO_BOOK_ENABLED', 'false').strip().lower() != 'false':
        return 3
    if not watcher.configure_credentials('ALDI'):
        return 3

    driver = None
    try:
        driver = watcher.build_driver()
        if not watcher.aldi_login(driver):
            return 1
        if not watcher.aldi_protected_session_visible(driver):
            return 1

        probe = sanitized_probe(probe_selectors(driver, watcher.ALDI_USER))
        write_report('selector-probe.json', {'selector_probe': probe})
        summary = {role: item['count'] for role, item in probe.items()}
        print(json.dumps({'selector_probe_counts': summary}, ensure_ascii=False), flush=True)
        return 0 if probe.get('account', {}).get('count', 0) else 2
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == '__main__':
    raise SystemExit(main())
