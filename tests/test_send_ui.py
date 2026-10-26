"""La fenêtre d'envoi de bout en bout, via airdropd (ouvre une fenêtre).

    dbus-run-session -- python3 tests/test_send_ui.py
"""

import importlib.machinery
import importlib.util
import os
import sys
import tempfile

from gi.repository import GLib

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from harness import ROOT, Harness, report  # noqa: E402

loader = importlib.machinery.SourceFileLoader("airdrop_send", os.path.join(ROOT, "send", "airdrop-send"))
spec = importlib.util.spec_from_loader("airdrop_send", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
m.CLOSE_AFTER_SENT = 30

h = Harness()
result = {}


def watch(win, ticks=[0]):
    ticks[0] += 1
    page = win.stack.get_visible_child_name()
    result.setdefault("pages", [])
    if not result["pages"] or result["pages"][-1] != page:
        result["pages"].append(page)
    if page == "list" and len(win.rows) >= 2 and not win.sending:
        result["devices"] = sorted(r.name for r in win.rows.values())
        win._on_pick(next(r for r in win.rows.values() if r.name.startswith("iPhone")))
    if page == "sending" and win.progress.get_visible():
        result["progress"] = True
    if (page == "result" and win.banner.get_title() == "Wi-Fi rétabli.") or ticks[0] > 120:
        result["title"] = win.result_page.get_title()
        result["banner"] = win.banner.get_title()
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
acquires, releases, held = h.owlyd_counts()
h.close()
report({
    "deux appareils listés": result.get("devices") == ["MacBook Pro de Test", "iPhone de Camille"],
    "progression affichée": result.get("progress", False),
    "envoyé": result.get("title") == "Envoyé",
    "Wi-Fi rétabli affiché": result.get("banner") == "Wi-Fi rétabli.",
    "radio rendue": releases == acquires == 1 and not held,
}, result)
