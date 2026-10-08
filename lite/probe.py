"""Read-only authenticated diagnosis; retains no account fields or response bodies."""
import json
from pathlib import Path
from urllib.parse import urlencode

from lite.portal import AldiPortal
from monitoring import write_report, utcnow


NAVIGATION_URL = 'https://www.alditalk-kundenportal.de/scs/bff/scs-207-customer-master-data-bff/customer-master-data/v1/navigation-list'
OFFERS_URL = 'https://www.alditalk-kundenportal.de/scs/bff/scs-209-selfcare-dashboard-bff/selfcare-dashboard/v1/offers'


def fetch_json(driver, url):
    # URLs are grounded in inspected public integrations, not yet a live API contract.
    # Cookies stay inside the normal same-origin browser session.
    return driver.execute_async_script("""
        const done = arguments[arguments.length - 1];
        fetch(arguments[0], {credentials: 'same-origin', redirect: 'error'})
          .then(async response => {
            const type = response.headers.get('content-type') || '';
            done({status: response.status, json: type.includes('application/json') ? await response.json() : null});
          }).catch(() => done({status: null, json: null}));
    """, url)


def main():
    report = {'scope': 'authenticated_read_only', 'started_at': utcnow(),
              'login_confirmed': False, 'booking_executed': False}
    portal = AldiPortal()
    try:
        portal.login()
        report['login_confirmed'] = bool(portal._session())
        if report['login_confirmed']:
            navigation = fetch_json(portal.driver, NAVIGATION_URL)
            report['navigation_http_status'] = navigation['status']
            data = navigation.get('json')
            details = data.get('userDetails', {}) if isinstance(data, dict) else {}
            subscriptions = details.get('subscriptions', []) if isinstance(details, dict) else []
            report['subscription_count'] = len(subscriptions) if isinstance(subscriptions, list) else None
            # Never choose a first contract among multiple accounts.
            if isinstance(subscriptions, list) and len(subscriptions) == 1:
                contract = subscriptions[0].get('contractId')
                if isinstance(contract, str) and contract:
                    result = fetch_json(portal.driver, OFFERS_URL + '?' + urlencode({'contractId': contract, 'productType': ''}))
                    report['offers_http_status'] = result['status']
                    offers = result.get('json')
                    # Schema presence only; never raw offers, balances, phone or contract IDs.
                    report['offers_json_object'] = isinstance(offers, dict)
                    report['subscribed_offers_present'] = isinstance(offers, dict) and 'subscribedOffers' in offers
                    report['free_refill_verified'] = False
    except Exception as exc:
        allowed = {'credentials_missing', 'user_action_required', 'login_not_confirmed',
                   'protected_element_unverified', 'account_flow_unconfigured'}
        report['error_class'] = str(exc) if str(exc) in allowed else type(exc).__name__
    finally:
        try:
            portal.close()
        except Exception:
            report['cleanup_failed'] = True
        report['finished_at'] = utcnow()
        write_report('v5-login-report.json', report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report['login_confirmed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
