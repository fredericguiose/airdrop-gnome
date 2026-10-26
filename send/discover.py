#!/usr/bin/env python3
"""Demande leur nom aux appareils AirDrop à portée de la radio Owly.

`owly browse` ne liste que ce qui s'annonce en mDNS, et un iPhone ne le fait
pas toujours. On fait donc ce que fait `owly send` avant d'envoyer, sans
envoyer : un `POST /Discover` vers chaque pair AWDL que la radio entend
(Sender::discover d'owly-airdrop). Un appareil en « Tout le monde » répond
avec son nom ; les autres ne répondent pas.
"""

import json
import plistlib
import socket
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

PORT = 8770
IFACE = "awdl0"
TIMEOUT = 6


def link_local(mac):
    """L'adresse EUI-64 modifiée d'un MAC, celle des pairs AWDL (NET-1)."""
    m = [int(b, 16) for b in mac.split(":")]
    m[0] ^= 0x02
    groups = [m[0] << 8 | m[1], m[2] << 8 | 0xFF, 0xFE << 8 | m[3], m[4] << 8 | m[5]]
    return "fe80::" + ":".join(f"{g:x}" for g in groups)


def peers():
    """Les pairs AWDL qu'entend la radio, d'après owlyd."""
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
    reply = bus.call_sync(
        "io.github.t4t5.Owly", "/io/github/t4t5/Owly",
        "org.freedesktop.DBus.Properties", "Get",
        GLib.Variant("(ss)", ("io.github.t4t5.Owly.Radio1", "Peers")),
        GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, -1)
    return [{"mac": p["mac"], "rssi": p.get("rssi")} for p in reply.unpack()[0]]


def _tls():
    # Le certificat d'un appareil AirDrop est auto-signé : comme owly-airdrop,
    # on ne le vérifie pas, et on n'en présente pas (mode « Tout le monde »).
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _read_response(conn):
    """Statut, en-têtes et corps ; le corps en Content-Length ou en chunked."""
    data = b""

    def more():
        nonlocal data
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError("réponse incomplète")
        data += chunk

    while b"\r\n\r\n" not in data:
        more()
    head, data = data.split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()

    if "chunked" in headers.get("transfer-encoding", "").lower():
        body = b""
        while True:
            while b"\r\n" not in data:
                more()
            size_line, data = data.split(b"\r\n", 1)
            size = int(size_line.split(b";")[0], 16)
            if size == 0:
                return status, headers, body
            while len(data) < size + 2:
                more()
            body += data[:size]
            data = data[size + 2:]

    length = int(headers.get("content-length", "0"))
    while len(data) < length:
        more()
    return status, headers, data[:length]


def discover(mac):
    """Le nom et le modèle de l'appareil, ou None s'il ne nous liste pas."""
    body = plistlib.dumps({}, fmt=plistlib.FMT_BINARY)
    request = (
        "POST /Discover HTTP/1.1\r\n"
        "User-Agent: AirDrop/1.0\r\n"
        "Content-Type: application/octet-stream\r\n"
        "Connection: keep-alive\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode() + body
    # create_connection ne prend que (hôte, port) : une adresse link-local a
    # besoin de son interface, d'où le tuple IPv6 complet et un socket à nous.
    addr = (link_local(mac), PORT, 0, socket.if_nametoindex(IFACE))
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as raw:
        raw.settimeout(TIMEOUT)
        raw.connect(addr)
        with _tls().wrap_socket(raw, server_hostname="airdrop.local") as conn:
            conn.sendall(request)
            status, headers, payload = _read_response(conn)
    if status != 200:
        return None
    try:
        answer = plistlib.loads(payload)
    except plistlib.InvalidFileException as e:
        raise ValueError(f"corps illisible ({len(payload)} o, en-têtes {headers}, début {payload[:16]!r})") from e
    name = answer.get("ReceiverComputerName")
    if not name:  # DISC-1 : sans nom, il n'est pas listé
        return None
    return {"name": name, "model": answer.get("ReceiverModelName")}


def main():
    targets = [{"mac": m, "rssi": None} for m in sys.argv[1:]] or peers()
    if not targets:
        print(json.dumps({"info": "aucun pair AWDL entendu"}), flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for peer, result in zip(targets, pool.map(_try, targets)):
            print(json.dumps({**peer, **result}, ensure_ascii=False), flush=True)


def _try(peer):
    try:
        found = discover(peer["mac"])
        return found or {"name": None, "error": "ne nous liste pas"}
    except Exception as e:  # noqa: BLE001
        return {"name": None, "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    main()
