#!/bin/bash
# Installe la partie bureau, pour l'utilisateur courant (sans root) :
# le bouton AirDrop de GNOME Shell, la fenêtre d'envoi et le clic droit de
# Fichiers. Par liens symboliques : modifier le dépôt suffit.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UUID=airdrop@portalstudio.fr

mkdir -p ~/.local/bin ~/.local/share/applications \
  ~/.local/share/gnome-shell/extensions ~/.local/share/nautilus-python/extensions

ln -sfn "$HERE/send/airdrop-send" ~/.local/bin/airdrop-send
ln -sfn "$HERE/send/fr.portalstudio.AirDropSend.desktop" ~/.local/share/applications/fr.portalstudio.AirDropSend.desktop
ln -sfn "$HERE/nautilus/airdrop.py" ~/.local/share/nautilus-python/extensions/airdrop.py
ln -sfn "$HERE/extension" ~/.local/share/gnome-shell/extensions/$UUID
update-desktop-database ~/.local/share/applications 2>/dev/null || true

# Activée d'avance : sous Wayland, GNOME ne la découvre qu'à la reconnexion.
python3 - "$UUID" <<'EOF'
import ast, subprocess, sys
uuid = sys.argv[1]
cur = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
                     capture_output=True, text=True).stdout.replace("@as ", "").strip()
exts = ast.literal_eval(cur) if cur and cur != "[]" else []
if uuid not in exts:
    exts.append(uuid)
    subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions", str(exts)], check=True)
EOF

rpm -q nautilus-python >/dev/null 2>&1 || echo "Pour le clic droit : sudo dnf install nautilus-python"
nautilus -q 2>/dev/null || true
echo "OK. Déconnectez-vous puis reconnectez-vous pour voir le bouton AirDrop."
