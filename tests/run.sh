#!/bin/bash
# Tous les tests ; aucun ne touche au Wi-Fi. Le dernier ouvre une fenêtre.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest -v tests/test_discover.py
gjs -m tests/test_owly.js
PATH="$PWD/tests/fake-owly:$PATH" python3 tests/test_send_ui.py
