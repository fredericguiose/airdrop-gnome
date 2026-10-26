"""« Envoyer via AirDrop » dans le clic droit de Fichiers (nautilus-python)."""

import shutil
import subprocess

import gi

gi.require_version("Nautilus", "4.1")
from gi.repository import GObject, Nautilus  # noqa: E402


class AirDropMenu(GObject.GObject, Nautilus.MenuProvider):
    def get_file_items(self, files):
        # Seulement des fichiers locaux : owly envoie des fichiers, pas des
        # dossiers ni des emplacements réseau.
        paths = [f.get_location().get_path() for f in files
                 if f.get_uri_scheme() == "file" and not f.is_directory()]
        if not paths or len(paths) != len(files) or not shutil.which("airdrop-send"):
            return []
        item = Nautilus.MenuItem(name="AirDrop::send", label="Envoyer via AirDrop")
        item.connect("activate", lambda _item: subprocess.Popen(["airdrop-send", *paths]))
        return [item]
