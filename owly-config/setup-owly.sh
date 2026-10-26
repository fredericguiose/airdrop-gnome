#!/bin/bash
# Installe et configure Owly (https://github.com/t4t5/owly) sur Fedora,
# à lancer en root :  pkexec bash owly-config/setup-owly.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VERSION="${OWLY_VERSION:-0.4.1}"
RPM="owly-$VERSION-1.x86_64.rpm"

echo "==> Owly $VERSION"
if ! rpm -q owly >/dev/null; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fL -o "$TMP/$RPM" "https://github.com/t4t5/owly/releases/download/v$VERSION/$RPM"
  dnf install -y "$TMP/$RPM"
fi

echo "==> SELinux : owlyd doit tourner en unconfined_service_t"
# Installé dans /usr/lib/owly (lib_t), owlyd reste en init_t et SELinux lui
# refuse les sockets netlink : « can't read what <iface> can do from nl80211 ».
if command -v semanage >/dev/null && selinuxenabled 2>/dev/null; then
  semanage fcontext -a -t bin_t /usr/lib/owly/owlyd 2>/dev/null \
    || semanage fcontext -m -t bin_t /usr/lib/owly/owlyd
  restorecon -v /usr/lib/owly/owlyd
fi

echo "==> Configuration /etc/owly"
install -d /etc/owly
for f in radio.toml drivers.toml; do
  [ -e "/etc/owly/$f" ] && cp "/etc/owly/$f" "/etc/owly/$f.bak"
  install -m644 "$HERE/$f" "/etc/owly/$f"
done
echo "   (vérifier « station » dans /etc/owly/radio.toml : $(ls /sys/class/ieee80211/*/device/net 2>/dev/null | head -1))"

echo "==> Pare-feu : zone « airdrop » pour awdl0 (TCP 8771 + mDNS)"
if systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --get-zones | tr ' ' '\n' | grep -qx airdrop \
    || firewall-cmd --permanent --new-zone=airdrop
  firewall-cmd --permanent --zone=airdrop --add-port=8771/tcp
  firewall-cmd --permanent --zone=airdrop --add-service=mdns
  firewall-cmd --permanent --zone=airdrop --add-interface=awdl0 || true
  firewall-cmd --reload
fi

nmcli general reload conf || true
systemctl try-restart owlyd || true
echo
echo "OK. Vérifier avec : owly doctor"
