"""Faux owlyd + vrai airdropd (avec le faux owly), sur le bus de session du
test : à lancer sous `dbus-run-session`. Rien ne touche au Wi-Fi.
"""

import os
import subprocess
import sys
import tempfile
import time

from gi.repository import Gio, GLib

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TESTS = os.path.join(ROOT, "tests")


class Harness:
    def __init__(self):
        self.tmp = tempfile.mkdtemp()
        self.downloads = os.path.join(self.tmp, "Téléchargements")
        os.makedirs(self.downloads)
        os.makedirs(os.path.join(self.tmp, "config"))
        with open(os.path.join(self.tmp, "config", "user-dirs.dirs"), "w") as f:
            f.write(f'XDG_DOWNLOAD_DIR="{self.downloads}"\n')
        self.env = dict(os.environ, AIRDROP_OWLY_BUS="session",
                        XDG_CONFIG_HOME=os.path.join(self.tmp, "config"),
                        PATH=f"{TESTS}/fake-owly:{os.environ['PATH']}")
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.procs = [subprocess.Popen([sys.executable, os.path.join(TESTS, "fake-owlyd.py")], env=self.env)]
        self.wait_name("io.github.t4t5.Owly")
        self.procs.append(subprocess.Popen([os.path.join(ROOT, "bin", "airdropd")], env=self.env))
        self.wait_name("fr.portalstudio.AirDrop")

    def wait_name(self, name, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                  "NameHasOwner", GLib.Variant("(s)", (name,)), None,
                                  Gio.DBusCallFlags.NONE, -1, None).unpack()[0]:
                return
            time.sleep(0.1)
        raise TimeoutError(name)

    def call(self, method, sig=None, *args):
        return self.bus.call_sync("fr.portalstudio.AirDrop", "/fr/portalstudio/AirDrop",
                                  "fr.portalstudio.AirDrop1", method,
                                  GLib.Variant(f"({sig})", args) if sig else None, None,
                                  Gio.DBusCallFlags.NONE, 5000, None).unpack()

    def owlyd_counts(self):
        """(Acquire, Release, bail en cours) côté faux owlyd."""
        return self.bus.call_sync("io.github.t4t5.Owly", "/io/github/t4t5/Owly", "io.github.t4t5.Owly.Radio1",
                                  "TestCounts", None, None, Gio.DBusCallFlags.NONE, -1, None).unpack()

    def close(self):
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            p.wait(timeout=5)


def report(checks, details=None):
    for name, ok in checks.items():
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if not all(checks.values()):
        if details is not None:
            print("détails :", details)
        sys.exit(1)
