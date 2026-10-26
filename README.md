# AirDrop pour GNOME

Recevoir et envoyer des fichiers entre un PC Linux (GNOME) et un iPhone ou un
Mac, par le vrai AirDrop d'Apple, sans application sur l'iPhone.

Ce projet est une couche d'intégration GNOME par-dessus
[**Owly**](https://github.com/t4t5/owly), qui réimplémente AWDL (le Wi-Fi
direct d'Apple) et le protocole AirDrop sous Linux.

- **Bouton AirDrop** dans les réglages rapides de GNOME Shell : rend le PC
  visible pendant quelques minutes, notification « Accepter / Refuser » à
  chaque envoi, Wi-Fi rétabli dès le transfert terminé.
- **Clic droit → « Envoyer via AirDrop »** dans Fichiers : fenêtre GTK 4 /
  libadwaita qui liste les appareils à proximité par leur nom et envoie.
- **Pilote `mt7921e` patché** (DKMS) pour les cartes MediaTek MT7920/7921/7922.

> ⚠️ Expérimental. AirDrop sous Linux repose sur de la rétro-ingénierie et
> sur des fonctions Wi-Fi que tous les pilotes n'ont pas.

## Ce qu'il faut savoir avant

- **Côté iPhone**, AirDrop doit être sur **« Tout le monde pendant
  10 minutes »** : « Contacts uniquement » demande une identité signée par
  Apple, impossible hors de son matériel.
- **Le Wi-Fi coupe pendant AirDrop** sur la plupart des cartes : la radio ne
  peut être que sur un canal à la fois, et AirDrop vit sur les canaux 6, 44 ou
  149. Il est rendu dès le transfert fini. Avec une carte qui sait faire le
  mode « partagé » d'Owly, et un réseau sur l'un de ces canaux, il reste
  connecté. Voir la [table des cartes d'Owly](https://github.com/t4t5/owly#hardware).
- Testé sur Fedora 44, GNOME 50, MediaTek MT7921 (`14c3:7961`), iPhone sous iOS 18.

## Installation

### 1. Owly

```sh
pkexec bash owly-config/setup-owly.sh
owly doctor
```

Installe le RPM d'Owly, corrige le contexte SELinux de `owlyd` (sans ça :
« can't read what wlp3s0 can do from nl80211 »), écrit `/etc/owly/*.toml` et
ouvre TCP 8771 + mDNS sur `awdl0` seulement (zone firewalld `airdrop`).
Adapter `station` dans `owly-config/radio.toml` à votre interface Wi-Fi.

### 2. Pilote patché (MediaTek MT7920/7921/7922 seulement)

Sans lui, ces cartes injectent à 1 Mbit/s et jamais en 5 GHz : AirDrop est
lent et peu fiable. Le patch est celui de
[shaecodes-wilde/mt76](https://github.com/shaecodes-wilde/mt76/commit/2a2f085dc1f920cabf8b8bc18686b9f974b27dac)
([discussion](https://github.com/t4t5/owly/issues/14)), pas encore dans le
noyau.

```sh
pkexec bash driver/install.sh
```

Le module est construit contre les sources `mt76` du noyau exact qui tourne,
et reconstruit à chaque nouveau noyau (hook `kernel-install` + service de
rattrapage). Si le patch ne s'applique plus ou qu'il est arrivé dans le noyau,
le pilote d'origine reste en place.

**Secure Boot** : enregistrer la clé DKMS *avant* de redémarrer
(`sudo mokutil --import /var/lib/dkms/mok.pub`, puis « Enroll MOK » dans
l'écran bleu). Sinon le noyau refuse le module et le Wi-Fi ne marche plus ;
`pkexec dkms remove mt7921e-airdrop/<version> --all` rend le pilote d'origine.

### 3. Intégration GNOME

```sh
sudo dnf install nautilus-python
./install.sh
```

Puis se déconnecter et se reconnecter (sous Wayland, GNOME ne charge une
nouvelle extension qu'à l'ouverture de session).

### 4. Extension Chrome (facultatif)

Clic droit sur une page ou un lien → **« Envoyer via AirDrop »**, ou le bouton
de la barre d'outils : la page s'ouvre sur l'iPhone.

```sh
chrome/install.sh
```

puis dans `chrome://extensions` : **Mode développeur** → **Charger l'extension
non empaquetée** → dossier `chrome/extension`. Le script déclare le relais
local (*native messaging*) à Chrome, Chromium, Brave, Edge et Vivaldi s'ils
sont installés ; il n'accepte que cette extension (identifiant fixé par la clé
du manifeste) et ne transmet à `airdrop-send --url` que des adresses http(s).
Le Chrome en Flatpak ne permet pas ce relais.

## Comment ça marche

```
 bouton GNOME Shell ──┐                                ┌─ owly receive / browse / send
 fenêtre d'envoi ─────┼── D-Bus (session) ── airdropd ─┤
 extension Chrome ────┘   fr.portalstudio.AirDrop      └─ owlyd (D-Bus système) : la radio
```

Tout passe par **`airdropd`**, un petit service de session lancé par D-Bus au
premier appel et qui s'arrête seul, inoccupé. Il tient le bail radio d'owlyd
**pour tous** : owlyd n'en prête qu'un à la fois, et la réception comme
l'envoi savent partager celui qui est levé. La radio monte pour le premier
utilisateur et redescend avec le dernier ; owlyd la reprend si le service meurt.

| Composant | Rôle |
|---|---|
| `airdrop/daemon.py` (`bin/airdropd`) | Le service : radio partagée, réception (demande → `Answer`), recherche des appareils, envoi avec progression |
| `airdrop/owly.py` | Toute la lecture de la sortie de la CLI d'Owly, en un seul endroit |
| `airdrop/discover.py` | Demande leur nom aux pairs AWDL (`POST /Discover`), ce que la CLI d'Owly ne fait pas sans envoyer ; `owly browse` réveille les iPhone en Bluetooth |
| `extension/` | Extension GNOME Shell 50 : le bouton et les notifications, simple client D-Bus (aucun processus dans le Shell) |
| `send/airdrop-send` | Fenêtre d'envoi (Python, GTK 4, libadwaita), cliente du service |
| `nautilus/` | Entrée « Envoyer via AirDrop » du clic droit (nautilus-python) |
| `chrome/` | Extension Chrome (menu et bouton) et son relais local, qui lance `airdrop-send --url` |
| `driver/` | Le patch mt76 et son installation DKMS |
| `owly-config/` | Installation et configuration d'Owly |

L'interface D-Bus est décrite en tête de `airdrop/daemon.py` : `StartReceiving`,
`Answer`, `StartBrowsing`, `GetDevices`, `Send`… et les signaux `Request`,
`Received`, `DeviceSeen`, `SendProgress`…

**Version d'Owly** : testé avec **0.4.1**. Le service lit la sortie texte de
la CLI d'Owly (`wants to send:`, `accept? [y/N]`, `delivered`…) : une autre
version peut la changer, et `airdrop/owly.py` est le seul fichier à adapter.

## Tests

```sh
sudo dnf install dbus-daemon   # pour dbus-run-session
tests/run.sh
```

Aucun test ne touche au Wi-Fi : `tests/fake-owly/owly` imite la CLI,
`tests/fake-owlyd.py` imite owlyd sur un bus D-Bus privé. On y vérifie
notamment que réception et envoi simultanés ne demandent **qu'une** radio, et
qu'elle est rendue. Le dernier test ouvre la fenêtre d'envoi et la pilote
jusqu'à « Envoyé ».

## Limites connues et suite

- Pas encore de choix automatique du mode partagé (Wi-Fi gardé) quand le
  réseau est sur 6, 44 ou 149.
- Envoi lent (~100 Ko/s) quand l'iPhone est sur un Wi-Fi 2,4 GHz : voir
  l'[issue #1](https://github.com/fredericguiose/airdrop-gnome/issues/1).
- `airdrop/discover.py` refait le `POST /Discover` d'owly-airdrop ; à retirer
  si `owly browse` interroge un jour les pairs AWDL.

## Crédits

- [Owly](https://github.com/t4t5/owly) (t4t5 et contributeurs), qui fait tout
  le vrai travail.
- Le patch `mt76` de Shae Wilde, et les tests MT7921 de l'issue
  [owly#14](https://github.com/t4t5/owly/issues/14).
- [OpenDrop](https://github.com/seemoo-lab/opendrop) et
  [OWL](https://github.com/seemoo-lab/owl) (SEEMOO, TU Darmstadt), à l'origine
  de tout ça.

## Licence

GPL-3.0-or-later. Les patchs de `driver/patches/` gardent la licence du code
`mt76` qu'ils modifient.
