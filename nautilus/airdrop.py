"""« Envoyer via AirDrop » dans le clic droit de Fichiers (nautilus-python).

AIRDROP_DEBUG=1 nautilus  → explique sur stderr pourquoi l'entrée apparaît ou non.
"""

import os
import shutil
import subprocess
import sys
import traceback

import gi

gi.require_version("Nautilus", "4.1")
from gi.repository import GObject, Nautilus  # noqa: E402

DEBUG = bool(os.environ.get("AIRDROP_DEBUG"))


def debug(*args):
    if DEBUG:
        print("airdrop-nautilus:", *args, file=sys.stderr, flush=True)


class AirDropMenu(GObject.GObject, Nautilus.MenuProvider):
    def get_file_items(self, *args):
        # nautilus-python passe (files) ou, selon les versions, (window, files).
        files = args[-1]
        try:
            return self._items(files)
        except Exception:  # noqa: BLE001 : jamais casser le menu de Fichiers
            traceback.print_exc()
            return []

    def _items(self, files):
        debug("sélection :", [(f.get_uri_scheme(), f.get_uri(), f.is_directory()) for f in files])
        # Seulement des fichiers locaux : owly envoie des fichiers, pas des
        # dossiers ni des emplacements réseau.
        paths = [f.get_location().get_path() for f in files
                 if f.get_uri_scheme() == "file" and not f.is_directory()]
        if not paths or len(paths) != len(files):
            debug("ignoré : pas uniquement des fichiers locaux")
            return []
        if not shutil.which("airdrop-send"):
            debug("ignoré : airdrop-send introuvable dans PATH =", os.environ.get("PATH"))
            return []
        item = Nautilus.MenuItem(name="AirDrop::send", label="Envoyer via AirDrop")
        item.connect("activate", lambda _item: subprocess.Popen(["airdrop-send", *paths]))
        debug("entrée ajoutée pour", paths)
        return [item]
