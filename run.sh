#!/usr/bin/env bash
set -Eeuo pipefail

DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

MODE="${1:---test}"
if [[ $# -gt 0 ]]; then
    shift
fi

if [[ ! -f requirements.txt || ! -f watcher.py ]]; then
    echo "Fehler: Kein gültiges aldi-watcher-Verzeichnis." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Fehler: python3 fehlt." >&2
    exit 1
fi

if [[ ! -d .venv ]]; then
    echo "==> Erstelle Python-Umgebung..."
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Prüfe/Installiere Abhängigkeiten..."
python -m pip install -q -r requirements.txt

# Harte Sicherheitsgrenzen für diesen Starter.
export AUTO_BOOK_ENABLED=false
export DRY_RUN=true

case "$MODE" in
    --test)
        echo "==> Starte Regressionstests..."
        python -m pytest -q "$@"
        ;;

    --monitor)
        if [[ "${ALDI_MONITORING_ENABLED:-false}" != "true" ]]; then
            echo "BLOCKED: ALDI_MONITORING_ENABLED ist nicht true." >&2
            exit 3
        fi

        if [[ -z "${CHROME_BINARY:-}" ]]; then
            for candidate in google-chrome-stable google-chrome chromium chromium-browser; do
                if command -v "$candidate" >/dev/null 2>&1; then
                    export CHROME_BINARY="$(command -v "$candidate")"
                    break
                fi
            done
        fi

        if [[ -z "${CHROME_BINARY:-}" || ! -x "${CHROME_BINARY:-}" ]]; then
            echo "Fehler: Chrome/Chromium für Selenium fehlt. Setze CHROME_BINARY oder installiere einen Browser." >&2
            exit 3
        fi

        echo "==> Starte einmaliges ALDI Read-only-Monitoring..."
        python watcher.py --run-once --provider aldi_talk "$@"
        ;;

    *)
        cat >&2 <<'EOF'
Verwendung:
  ./run.sh --test [pytest-Argumente]
  ALDI_MONITORING_ENABLED=true ./run.sh --monitor [watcher-Argumente]
EOF
        exit 2
        ;;
esac
