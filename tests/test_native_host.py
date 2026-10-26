"""Le relais native messaging de l'extension Chrome, avec un faux airdrop-send."""

import json
import os
import struct
import subprocess
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
HOST = os.path.join(ROOT, "chrome", "native-host", "airdrop-native-host")


class NativeHost(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = os.path.join(self.dir, "calls.log")
        fake = os.path.join(self.dir, "airdrop-send")
        with open(fake, "w") as f:
            f.write(f'#!/bin/bash\nprintf "%s\\n" "$@" >> {self.log}\n')
        os.chmod(fake, 0o755)
        self.env = dict(os.environ, PATH=f"{self.dir}:{os.environ['PATH']}")

    def ask(self, message):
        data = json.dumps(message).encode()
        out = subprocess.run([HOST], input=struct.pack("=I", len(data)) + data,
                             capture_output=True, env=self.env, timeout=10).stdout
        (n,) = struct.unpack("=I", out[:4])
        return json.loads(out[4:4 + n])

    def calls(self):
        time.sleep(0.3)  # airdrop-send est détaché
        try:
            return open(self.log).read().splitlines()
        except FileNotFoundError:
            return []

    def test_web_url(self):
        url = "https://exemple.fr/page?a=1&b=2#x"
        self.assertEqual(self.ask({"url": url}), {"ok": True})
        self.assertEqual(self.calls(), ["--url", url])

    def test_refused(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "https://x.fr/\nrm -rf ~",
                    "--help", "https://", None, 42, "https://x.fr/" + "a" * 9000):
            with self.subTest(url=url):
                reply = self.ask({"url": url})
                self.assertFalse(reply["ok"])
                self.assertTrue(reply["error"])
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
