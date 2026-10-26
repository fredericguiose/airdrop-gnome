#!/bin/bash
# Déclare le relais native messaging aux navigateurs Chromium installés, pour
# l'utilisateur courant. L'extension elle-même se charge à la main :
# chrome://extensions → Mode développeur → Charger l'extension non empaquetée
# → chrome/extension.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOST="$HERE/native-host/airdrop-native-host"
NAME=fr.portalstudio.airdrop

# L'identifiant d'une extension non empaquetée vient de sa clé (« key ») :
# sha256 de la clé publique, 32 premiers chiffres hexadécimaux en a–p.
ID="$(python3 - "$HERE/extension/manifest.json" <<'EOF'
import base64, hashlib, json, sys
key = base64.b64decode(json.load(open(sys.argv[1]))["key"])
print(hashlib.sha256(key).hexdigest()[:32].translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop")))
EOF
)"

chmod +x "$HOST"
installed=0
for dir in ~/.config/google-chrome ~/.config/chromium ~/.config/BraveSoftware/Brave-Browser \
           ~/.config/microsoft-edge ~/.config/vivaldi; do
  [ -d "$dir" ] || continue
  mkdir -p "$dir/NativeMessagingHosts"
  cat > "$dir/NativeMessagingHosts/$NAME.json" <<EOF
{
  "name": "$NAME",
  "description": "AirDrop : ouvre la fenêtre d'envoi d'airdrop-gnome",
  "path": "$HOST",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$ID/"]
}
EOF
  echo "Relais déclaré pour $(basename "$dir")"
  installed=1
done
[ "$installed" = 1 ] || echo "Aucun navigateur Chromium trouvé dans ~/.config."
echo "Identifiant de l'extension : $ID"
echo "Charger chrome/extension dans chrome://extensions (mode développeur)."
