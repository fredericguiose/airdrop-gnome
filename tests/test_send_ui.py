"""Parcours complet de la fenêtre d'envoi avec le faux owly (ouvre une fenêtre).

    PATH=tests/fake-owly:$PATH python3 tests/test_send_ui.py
"""

import importlib.machinery
import importlib.util
import os
import sys
import tempfile

from gi.repository import GLib

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader("airdrop_send", os.path.join(ROOT, "send", "airdrop-send"))
spec = importlib.util.spec_from_loader("airdrop_send", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

# Pas d'owlyd : la découverte répond comme un iPhone en « Tout le monde ».
m.discover.peers = lambda: [{"mac": "02:11:22:33:44:55", "rssi": -35}]
m.discover.discover = lambda mac: {"name": "iPhone de Camille", "model": None}
m.CLOSE_AFTER_SENT = 30

result = {}


def watch(win, ticks=[0]):
    ticks[0] += 1
    page = win.stack.get_visible_child_name()
    if page == "list" and len(win.rows) >= 2 and not win.sending:
        win._on_pick(next(r for r in win.rows.values() if r.name.startswith("iPhone")))
    if page == "sending" and win.progress.get_visible():
        result["progress"] = True
    if page == "result" or ticks[0] > 40:
        result["title"] = win.result_page.get_title()
        result["banner"] = win.banner.get_title()
        result["devices"] = sorted(r.name for r in win.rows.values())
        win.close()
        return False
    return True


class Test(m.App):
    def do_activate(self):
        f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        w = m.SendWindow(self, [f.name], [])
        w.present()
        GLib.timeout_add(250, watch, w)


Test().run([sys.argv[0]])
print(result)
expected = {"title": "Envoyé", "banner": "Wi-Fi rétabli.", "progress": True,
            "devices": ["MacBook Pro de Test", "iPhone de Camille"]}
sys.exit(0 if result == expected else 1)
