"""Lire ce que la CLI d'Owly (0.4.1) écrit : pas de sortie machine, donc on
s'en tient à ses phrases, toutes ici pour n'avoir qu'un endroit à adapter.
"""

import ipaddress
import json
import os
import re

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

def owlyd_bus():
    """Le bus d'owlyd : le système, ou celui des tests (AIRDROP_OWLY_BUS=session)."""
    if os.environ.get("AIRDROP_OWLY_BUS") == "session":
        return Gio.bus_get_sync(Gio.BusType.SESSION)
    return Gio.bus_get_sync(Gio.BusType.SYSTEM)


# `owly receive`, sur stderr.
ASK = re.compile(r'^(".*") \((".*")\) wants to send:$')
OFFER_FILE = re.compile(r'^ {2}(".*") (\S+) (?:(\d+) bytes)?$')
PROMPT = "accept? [y/N] "
# `owly browse`, sur stdout.
LISTED = re.compile(r'^\S+\s+(".*") \(\[([0-9a-fA-F:]+)%\d+\]:\d+\)$')
# `owly send`, sur stderr ; la progression se réécrit avec \r.
PROGRESS = re.compile(r"^(\d+) / (\d+) bytes$")


def unquote(s):
    """Une chaîne {:?} de Rust : guillemets, \\" \\\\ \\n, et \\u{1f600}."""
    s = s.strip()
    if not (s.startswith('"') and s.endswith('"')):
        return s
    s = re.sub(r"\\u\{([0-9a-fA-F]+)\}", lambda m: chr(int(m.group(1), 16)), s)
    try:
        return json.loads(s)
    except ValueError:
        return s[1:-1]


def link_local(mac):
    """L'adresse EUI-64 modifiée d'un MAC, celle des pairs AWDL (NET-1)."""
    m = [int(b, 16) for b in mac.split(":")]
    m[0] ^= 0x02
    groups = [m[0] << 8 | m[1], m[2] << 8 | 0xFF, 0xFE << 8 | m[3], m[4] << 8 | m[5]]
    return "fe80::" + ":".join(f"{g:x}" for g in groups)


def mac_from_link_local(addr):
    """Le MAC d'une adresse EUI-64 modifiée, ou None."""
    b = ipaddress.IPv6Address(addr).packed[8:]
    if b[3:5] != b"\xff\xfe":
        return None
    return ":".join(f"{x:02x}" for x in (b[0] ^ 0x02, b[1], b[2], b[5], b[6], b[7]))


def parse_listed(line):
    """Une ligne d'`owly browse` → (mac, nom), ou None."""
    m = LISTED.match(line.strip())
    mac = m and mac_from_link_local(m.group(2))
    return (mac, unquote(m.group(1))) if mac else None


class ReceiveParser:
    """Le stderr d'`owly receive`, ligne à ligne ; rend des événements :

    ("listening",)  ("request", {sender, files, urls})  ("expired",)
    ("withdrawn",)  ("failed", raison)
    """

    def __init__(self):
        self._request = None

    def line(self, line):
        if m := ASK.match(line):
            self._request = {"sender": unquote(m[1]), "files": [], "urls": []}
        elif self._request is not None and line.startswith("  "):
            if m := OFFER_FILE.match(line):
                self._request["files"].append(
                    {"name": unquote(m[1]), "type": m[2], "size": int(m[3]) if m[3] else 0})
            else:
                self._request["urls"].append(unquote(line))
        elif line.startswith("receiving as"):
            return ("listening",)
        elif line.strip() == "timed out":
            return ("expired",)
        elif line.startswith("the request was withdrawn"):
            return ("withdrawn",)
        elif line.startswith("transfer failed: "):
            return ("failed", line[len("transfer failed: "):])
        return None

    def partial(self, text):
        """Le reste sans retour à la ligne : la question d'Owly en est un."""
        if text.endswith(PROMPT) and self._request is not None:
            request, self._request = self._request, None
            return ("request", request)
        return None


def parse_received(line):
    """Le stdout d'`owly receive` : ("file", chemin) ou ("url", lien)."""
    if line.startswith('"'):
        return ("url", unquote(line))
    if line.startswith("/"):
        return ("file", line)
    return None


def parse_send_stderr(part):
    """Un morceau du stderr d'`owly send` (coupé sur \\r et \\n)."""
    if part == "accepted":
        return ("accepted",)
    if m := PROGRESS.match(part):
        return ("progress", int(m[1]), int(m[2]))
    if part.startswith("owly: "):
        return ("failed", part[len("owly: "):])
    return None


def parse_send_result(out, returncode):
    out = out.strip()
    if out == "delivered":
        return ("delivered",)
    if out == "declined":
        return ("declined",)
    if out.startswith("failed: "):
        return ("failed", out[len("failed: "):])
    if returncode != 0:
        return ("failed", out or f"owly send a quitté ({returncode})")
    return ("delivered",)
