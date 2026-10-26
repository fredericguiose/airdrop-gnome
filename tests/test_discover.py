"""Adresses AWDL et lecture des réponses HTTP de /Discover."""

import importlib.machinery
import importlib.util
import os
import plistlib
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "send"))

import discover  # noqa: E402

loader = importlib.machinery.SourceFileLoader("airdrop_send", os.path.join(ROOT, "send", "airdrop-send"))
spec = importlib.util.spec_from_loader("airdrop_send", loader)
send = importlib.util.module_from_spec(spec)
loader.exec_module(send)


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
        self.assertEqual(discover.link_local("02:11:22:33:44:55"), "fe80::11:22ff:fe33:4455")
        self.assertEqual(discover.link_local("0a:bb:cc:dd:ee:ff"), "fe80::8bb:ccff:fedd:eeff")

    def test_round_trip(self):
        for mac in ("02:11:22:33:44:55", "0a:bb:cc:dd:ee:ff", "62:ce:18:00:01:02"):
            self.assertEqual(send.mac_from_link_local(discover.link_local(mac)), mac)

    def test_not_eui64(self):
        self.assertIsNone(send.mac_from_link_local("fe80::1"))


class Responses(unittest.TestCase):
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


class Owly(unittest.TestCase):
    def test_unquote(self):
        self.assertEqual(send.unquote('"iPhone de Frédéric"'), "iPhone de Frédéric")
        self.assertEqual(send.unquote(r'"emoji \u{1f600} \"cité\""'), 'emoji 😀 "cité"')


if __name__ == "__main__":
    unittest.main()
