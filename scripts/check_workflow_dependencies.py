#!/usr/bin/env python3
"""Import scheduled entrypoints in clean environments; never run a monitor."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PROFILES = {'mail-monitor': 'usage_mail_notify', 'public-probe': 'portal_probe'}


def main():
    for profile, module in PROFILES.items():
        with tempfile.TemporaryDirectory(prefix='workflow-dependencies-') as folder:
            subprocess.run([sys.executable, '-m', 'venv', folder], check=True)
            executable = Path(folder) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            subprocess.run([
                str(executable), '-m', 'pip', 'install', '--quiet',
                '--disable-pip-version-check', '-r',
                str(ROOT / 'requirements' / (profile + '.txt')),
            ], cwd=ROOT, check=True)
            subprocess.run([str(executable), '-c', 'import ' + module], cwd=ROOT, check=True)
        print(profile + ': isolated entrypoint import passed', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
