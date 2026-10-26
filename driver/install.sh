#!/bin/bash
# Installe le pilote mt7921e patché pour AirDrop (DKMS), à lancer en root :
#   pkexec bash driver/install.sh
#
# Avec Secure Boot, DKMS signe le module avec sa propre clé
# (/var/lib/dkms/mok.pub) : l'enregistrer une fois avec `mokutil --import`,
# puis confirmer dans MokManager au redémarrage. Sans ça, le noyau refuse le
# module et le Wi-Fi ne marche plus ; `dkms remove mt7921e-airdrop/<version>
# --all` rend le pilote d'origine.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "==> Outils de compilation"
dnf install -y dkms kernel-devel-matched gcc make git-core

echo "==> Fichiers"
install -d /usr/share/mt7921e-airdrop/patches
install -m644 "$HERE"/patches/*.patch /usr/share/mt7921e-airdrop/patches/
install -m644 "$HERE"/Kbuild "$HERE"/files.txt /usr/share/mt7921e-airdrop/
install -m755 "$HERE"/mt7921e-airdrop-build /usr/local/sbin/
install -Dm755 "$HERE"/91-mt7921e-airdrop.install /etc/kernel/install.d/91-mt7921e-airdrop.install
install -m644 "$HERE"/mt7921e-airdrop.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable mt7921e-airdrop.service

echo "==> Compilation pour $(uname -r)"
/usr/local/sbin/mt7921e-airdrop-build

echo
modinfo -n mt7921e
modinfo mt7921e | grep -E '^(signer|sig_key)' || true
if command -v mokutil >/dev/null && mokutil --sb-state 2>/dev/null | grep -q enabled \
   && ! mokutil --test-key /var/lib/dkms/mok.pub 2>/dev/null | grep -q 'already enrolled'; then
  echo
  echo "Secure Boot : enregistrer la clé AVANT de redémarrer :"
  echo "  sudo mokutil --import /var/lib/dkms/mok.pub"
fi
