#!/bin/bash
# Tous les tests ; aucun ne touche au Wi-Fi (faux owly, faux owlyd, bus D-Bus
# privé). Le dernier ouvre la fenêtre d'envoi. Demande dbus-run-session
# (paquet dbus-daemon).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest -v tests/test_owly.py tests/test_native_host.py
dbus-run-session -- python3 tests/test_daemon.py
# GTK et les portails sont bavards sur un bus vide : on ne garde que le verdict.
out="$(dbus-run-session -- python3 tests/test_send_ui.py 2>&1)" && status=0 || status=$?
grep -E '^(ok|FAIL|détails)' <<<"$out"
exit "$status"
