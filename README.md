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

## Comment ça marche

| Composant | Rôle |
|---|---|
| `extension/` | Extension GNOME Shell 50 : bouton, notifications. Lance `owly radio up` et `owly receive`, répond à leur « accept? » |
| `send/airdrop-send` | Fenêtre d'envoi (Python, GTK 4, libadwaita). `owly browse` réveille les iPhone en Bluetooth ; `send/discover.py` demande leur nom aux pairs AWDL (`POST /Discover`), ce que la CLI d'Owly ne fait pas sans envoyer |
| `nautilus/` | Entrée « Envoyer via AirDrop » du clic droit (nautilus-python) |
| `driver/` | Le patch mt76 et son installation DKMS |
| `owly-config/` | Installation et configuration d'Owly |

**Version d'Owly** : testé avec **0.4.1**. L'extension et la fenêtre d'envoi
lisent la sortie texte de la CLI d'Owly (`wants to send:`, `accept? [y/N]`,
`delivered`…) : une autre version peut la changer.

## Tests

```sh
tests/run.sh
```

Aucun test ne touche au Wi-Fi : `tests/fake-owly/owly` imite la CLI. Le
dernier ouvre la fenêtre d'envoi et la pilote jusqu'à « Envoyé ».

## Limites connues et suite

- La réception (dans GNOME Shell) et l'envoi (dans la fenêtre) tiennent chacun
  leur radio : owlyd n'en prête qu'une à la fois, donc pas d'envoi pendant une
  réception. Prévu : un service de session `airdropd` qui partage la radio, et
  dont le bouton, la fenêtre et une extension Chrome seraient les clients.
- Pas encore de choix automatique du mode partagé (Wi-Fi gardé) quand le
  réseau est sur 6, 44 ou 149.
- `send/discover.py` refait le `POST /Discover` d'owly-airdrop, que la CLI
  n'expose pas seul ; à retirer si `owly browse` interroge un jour les pairs AWDL.

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
