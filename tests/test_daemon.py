"""airdropd : réception et envoi en même temps, une seule radio.

    dbus-run-session -- python3 tests/test_daemon.py
"""

import os
import sys
import time

from gi.repository import Gio, GLib

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from harness import Harness, report  # noqa: E402


def main():
    h = Harness()
    events = []
    loop = GLib.MainLoop()

    def on_signal(_c, _s, _p, _i, name, params):
        args = params.unpack()
        events.append((name, *args))
        if name == "Request":
            h.call("Answer", "sb", args[0], True)
        elif name == "DeviceSeen" and args[1] == "iPhone de Camille" and not any(e[0] == "SendProgress" for e in events):
            path = os.path.join(h.tmp, "a-envoyer.txt")
            open(path, "w").write("x")
            h.call("Send", "sasas", args[0], [path], [])
        elif name == "SendProgress" and args[1] in ("delivered", "declined", "failed"):
            h.call("StopBrowsing")

    h.bus.signal_subscribe("fr.portalstudio.AirDrop", "fr.portalstudio.AirDrop1", None, "/fr/portalstudio/AirDrop",
                           None, Gio.DBusSignalFlags.NONE, on_signal)
    h.call("StartReceiving", "u", 60)
    h.call("StartBrowsing")

    deadline = time.monotonic() + 30

    def check():
        names = {e[0] for e in events}
        if ({"Received", "SendProgress"} <= names and h.owlyd_counts()[2] is False) or time.monotonic() > deadline:
            loop.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE
    GLib.timeout_add(200, check)
    loop.run()

    acquires, releases, held = h.owlyd_counts()
    h.close()
    received = [e for e in events if e[0] == "Received"]
    sends = [e[2] for e in events if e[0] == "SendProgress"]
    report({
        "demande reçue": any(e[0] == "Request" and e[2] == "iPhone de Camille" for e in events),
        "fichier reçu": bool(received) and open(received[0][1]).read().strip() == "photo reçue",
        "fichier dans Téléchargements": bool(received) and received[0][1].startswith(h.downloads),
        "envoi livré": sends[-1:] == ["delivered"],
        "progression": "progress" in sends,
        "une seule radio pour tout": acquires == 1,
        "radio rendue": releases == 1 and not held,
    }, events)


if __name__ == "__main__":
    main()
