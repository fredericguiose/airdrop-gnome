"""Lecture de la sortie de la CLI d'Owly, adresses AWDL et réponses /Discover."""

import os
import plistlib
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from airdrop import discover, owly  # noqa: E402


class FakeConn:
    """Un socket qui rend la réponse par morceaux de `step` octets."""

    def __init__(self, data, step):
        self.data, self.step = data, step

    def recv(self, n):
        out = self.data[:min(n, self.step)]
        self.data = self.data[len(out):]
        return out


class Addresses(unittest.TestCase):
    def test_link_local(self):
        self.assertEqual(owly.link_local("02:11:22:33:44:55"), "fe80::11:22ff:fe33:4455")
        self.assertEqual(owly.link_local("0a:bb:cc:dd:ee:ff"), "fe80::8bb:ccff:fedd:eeff")

    def test_round_trip(self):
        for mac in ("02:11:22:33:44:55", "0a:bb:cc:dd:ee:ff", "62:ce:18:00:01:02"):
            self.assertEqual(owly.mac_from_link_local(owly.link_local(mac)), mac)

    def test_not_eui64(self):
        self.assertIsNone(owly.mac_from_link_local("fe80::1"))


class Discover(unittest.TestCase):
    body = plistlib.dumps({"ReceiverComputerName": "iPhone de Camille"}, fmt=plistlib.FMT_BINARY)

    def check(self, raw):
        for step in (3, 4096):
            status, _headers, body = discover._read_response(FakeConn(raw, step))
            self.assertEqual(status, 200)
            self.assertEqual(plistlib.loads(body)["ReceiverComputerName"], "iPhone de Camille")

    def test_content_length(self):
        self.check(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(self.body) + self.body)

    def test_chunked(self):
        half = len(self.body) // 2
        self.check(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                   + b"%x\r\n" % half + self.body[:half] + b"\r\n"
                   + b"%x\r\n" % (len(self.body) - half) + self.body[half:] + b"\r\n0\r\n\r\n")


class Cli(unittest.TestCase):
    def test_unquote(self):
        self.assertEqual(owly.unquote('"iPhone de Frédéric"'), "iPhone de Frédéric")
        self.assertEqual(owly.unquote(r'"emoji \u{1f600} \"cité\".txt"'), 'emoji 😀 "cité".txt')

    def test_receive_files(self):
        p = owly.ReceiveParser()
        self.assertEqual(p.line('receiving as "pc" (c0ffee) on [fe80::1]:8771, flags 0x89'), ("listening",))
        self.assertIsNone(p.line('"iPhone de Camille" ("iPhone") wants to send:'))
        self.assertIsNone(p.line('  "IMG.PNG" public.png 4694496 bytes'))
        self.assertIsNone(p.line('  "sans taille.mov" com.apple.quicktime-movie '))
        self.assertIsNone(p.partial('accept? [y/'))  # pas encore la question entière
        kind, request = p.partial("accept? [y/N] ")
        self.assertEqual(kind, "request")
        self.assertEqual(request, {"sender": "iPhone de Camille", "urls": [], "files": [
            {"name": "IMG.PNG", "type": "public.png", "size": 4694496},
            {"name": "sans taille.mov", "type": "com.apple.quicktime-movie", "size": 0}]})
        self.assertIsNone(p.partial("accept? [y/N] "))  # une seule fois par demande

    def test_receive_url_and_outcomes(self):
        p = owly.ReceiveParser()
        p.line('"iPhone" ("iPhone") wants to send:')
        p.line('  "https://exemple.fr/page"')
        self.assertEqual(p.partial("accept? [y/N] ")[1]["urls"], ["https://exemple.fr/page"])
        self.assertEqual(p.line("timed out"), ("expired",))
        self.assertEqual(p.line("the request was withdrawn"), ("withdrawn",))
        self.assertEqual(p.line("transfer failed: reset"), ("failed", "reset"))
        self.assertEqual(owly.parse_received("/home/x/Téléchargements/a.jpg"), ("file", "/home/x/Téléchargements/a.jpg"))
        self.assertEqual(owly.parse_received('"https://exemple.fr"'), ("url", "https://exemple.fr"))

    def test_browse_and_send(self):
        self.assertEqual(owly.parse_listed('8e56c45cfd7c   "iPhone de Camille" ([fe80::11:22ff:fe33:4455%31]:8770)'),
                         ("02:11:22:33:44:55", "iPhone de Camille"))
        self.assertIsNone(owly.parse_listed("looking for a receiver for 10 s..."))
        self.assertEqual(owly.parse_send_stderr("accepted"), ("accepted",))
        self.assertEqual(owly.parse_send_stderr("1000 / 5000 bytes"), ("progress", 1000, 5000))
        self.assertEqual(owly.parse_send_stderr("owly: no AWDL peer answered"), ("failed", "no AWDL peer answered"))
        self.assertEqual(owly.parse_send_result("delivered\n", 0), ("delivered",))
        self.assertEqual(owly.parse_send_result("declined", 1), ("declined",))
        self.assertEqual(owly.parse_send_result("failed: x", 2), ("failed", "x"))


if __name__ == "__main__":
    unittest.main()
