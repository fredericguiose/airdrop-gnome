"""airdropd : le service de session par lequel passent tous les clients
(bouton GNOME Shell, fenêtre d'envoi, extension Chrome).

Il tient la radio d'owlyd pour tous : owlyd n'en prête qu'une à la fois, et
`owly receive` comme `owly send` savent partager celle qui est levée. La
radio monte pour le premier utilisateur et redescend avec le dernier ;
owlyd la reprend de lui-même si ce processus meurt.
"""

import itertools
import os
import re
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import discover, owly  # noqa: E402

BUS_NAME = "fr.portalstudio.AirDrop"
PATH = "/fr/portalstudio/AirDrop"
IFACE = "fr.portalstudio.AirDrop1"

OWLY_NAME, OWLY_PATH, OWLY_IFACE = "io.github.t4t5.Owly", "/io/github/t4t5/Owly", "io.github.t4t5.Owly.Radio1"

DISCOVER_EVERY = 3
FORGET_SECONDS = 15
# Après un transfert reçu, on rend le Wi-Fi : le temps qu'un éventuel second
# fichier du même envoi arrive.
LINGER_SECONDS = 3
IDLE_EXIT_SECONDS = 120

XML = f"""
<node>
  <interface name="{IFACE}">
    <!-- idle | starting | up -->
    <property name="Radio" type="s" access="read"/>
    <!-- Fin de la réception (µs, GLib.get_real_time), 0 si elle est coupée. -->
    <property name="ReceivingUntil" type="x" access="read"/>
    <method name="StartReceiving"><arg name="seconds" type="u" direction="in"/></method>
    <method name="StopReceiving"/>
    <method name="Answer">
      <arg name="request" type="s" direction="in"/>
      <arg name="accept" type="b" direction="in"/>
    </method>
    <!-- Tant qu'un client cherche, la radio reste levée et les appareils
         sont annoncés ; le client qui disparaît arrête de chercher. -->
    <method name="StartBrowsing"/>
    <method name="StopBrowsing"/>
    <method name="GetDevices"><arg name="devices" type="aa{{sv}}" direction="out"/></method>
    <method name="Send">
      <arg name="mac" type="s" direction="in"/>
      <arg name="files" type="as" direction="in"/>
      <arg name="urls" type="as" direction="in"/>
      <arg name="transfer" type="s" direction="out"/>
    </method>
    <signal name="RadioFailed"><arg name="reason" type="s"/></signal>
    <signal name="Request">
      <arg name="request" type="s"/><arg name="sender" type="s"/>
      <arg name="files" type="aa{{sv}}"/><arg name="urls" type="as"/>
    </signal>
    <!-- answered | expired | withdrawn | stopped -->
    <signal name="RequestClosed"><arg name="request" type="s"/><arg name="reason" type="s"/></signal>
    <signal name="Received"><arg name="path" type="s"/></signal>
    <signal name="UrlReceived"><arg name="url" type="s"/></signal>
    <signal name="ReceiveFailed"><arg name="reason" type="s"/></signal>
    <signal name="DeviceSeen">
      <arg name="mac" type="s"/><arg name="name" type="s"/>
      <arg name="model" type="s"/><arg name="rssi" type="i"/>
    </signal>
    <signal name="DeviceLost"><arg name="mac" type="s"/></signal>
    <!-- waiting | accepted | progress | delivered | declined | failed -->
    <signal name="SendProgress">
      <arg name="transfer" type="s"/><arg name="state" type="s"/>
      <arg name="sent" type="t"/><arg name="total" type="t"/><arg name="detail" type="s"/>
    </signal>
  </interface>
</node>
"""


def spawn(args, **kw):
    # Le processus fils suit airdropd dans la tombe : sans lui, plus personne
    # ne lirait ses tuyaux.
    def die_with_parent():
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGINT)  # PR_SET_PDEATHSIG
    return subprocess.Popen(args, preexec_fn=die_with_parent, **kw)


def interrupt(proc):
    """Ctrl-C (owly rend ce qu'il tient), puis SIGKILL s'il traîne."""
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGINT)

        def reap():
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        threading.Thread(target=reap, daemon=True).start()


def read_lines(stream, on_line, on_partial=None, split=rb"\n"):
    """Lit un tuyau d'octets dans un thread ; rappelle dans la boucle GLib."""
    def run():
        buf = b""
        while chunk := stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096):
            buf += chunk
            *lines, buf = re.split(split, buf)
            for line in lines:
                GLib.idle_add(on_line, line.decode(errors="replace"))
            if buf and on_partial:
                text = buf.decode(errors="replace")
                done = threading.Event()
                taken = []

                def offer():
                    taken.append(on_partial(text))
                    done.set()
                GLib.idle_add(offer)
                done.wait()
                if taken[0]:
                    buf = b""
    threading.Thread(target=run, daemon=True).start()


class Radio:
    """Le bail d'owlyd, partagé : acquire(utilisateur) / release(utilisateur)."""

    def __init__(self, on_state, on_lost):
        self.bus = owly.owlyd_bus()
        self.state = "idle"
        self.users = set()
        self.lease = None
        self._waiting = []
        self._on_state, self._on_lost = on_state, on_lost
        self.bus.signal_subscribe(OWLY_NAME, OWLY_IFACE, "StateChanged", OWLY_PATH, None,
                                  Gio.DBusSignalFlags.NONE, self._owly_state)

    def acquire(self, user, callback):
        """callback(erreur ou None), une fois la radio levée."""
        self.users.add(user)
        if self.state == "up":
            GLib.idle_add(callback, None)
            return
        self._waiting.append(callback)
        if self.state == "idle":
            self._set("starting")
            self.bus.call(OWLY_NAME, OWLY_PATH, OWLY_IFACE, "Acquire", GLib.Variant("(u)", (0,)),
                          GLib.VariantType("(ta{sv})"), Gio.DBusCallFlags.NONE, 120_000, None,
                          self._acquired)

    def _acquired(self, bus, result):
        waiting, self._waiting = self._waiting, []
        try:
            self.lease, _link = bus.call_finish(result).unpack()
        except GLib.Error as e:
            self.users.clear()
            self._set("idle")
            reason = Gio.DBusError.strip_remote_error(e) or e.message
            for callback in waiting:
                callback(reason)
            return
        if not self.users:
            self._give_back()
            return
        self._set("up")
        for callback in waiting:
            callback(None)

    def release(self, user):
        self.users.discard(user)
        if not self.users and self.state == "up":
            self._give_back()

    def _give_back(self):
        lease, self.lease = self.lease, None
        if lease is not None:
            self.bus.call(OWLY_NAME, OWLY_PATH, OWLY_IFACE, "Release", GLib.Variant("(t)", (lease,)),
                          None, Gio.DBusCallFlags.NONE, -1, None, None)
        self._set("idle")

    # owlyd peut finir notre bail sans nous (redémarrage, Wi-Fi rendu).
    def _owly_state(self, _conn, _sender, _path, _iface, _signal, params):
        lease, state, _reason = params.unpack()
        if lease == self.lease and state != "up":
            self.lease = None
            self.users.clear()
            self._set("idle")
            self._on_lost()

    def _set(self, state):
        if state != self.state:
            self.state = state
            self._on_state(state)


class Service:
    def __init__(self, loop):
        self.loop = loop
        self.conn = None
        self.download_dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or GLib.get_home_dir()
        self.radio = Radio(self._radio_state, self._radio_lost)
        self.ids = itertools.count(1)
        # Réception
        self.receiving_until = 0
        self.receiver = None
        self.pending = None  # (id, owly.ReceiveParser)
        self._deadline_id = self._linger_id = 0
        # Recherche
        self.browsers = {}  # nom de bus du client → id de surveillance
        self.devices = {}   # mac → {name, model, rssi, seen}
        self.browse_proc = None
        self._browse_stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=6)
        # Envois
        self.sends = {}
        self._idle_since = time.monotonic()
        GLib.timeout_add_seconds(DISCOVER_EVERY, self._prune)
        GLib.timeout_add_seconds(30, self._maybe_exit)

    # --- D-Bus -------------------------------------------------------------

    def register(self, conn):
        self.conn = conn
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        conn.register_object_with_closures2(PATH, info, self._call, self._get_property, None)

    def _emit(self, name, signature=None, *args):
        if self.conn:
            params = GLib.Variant(f"({signature})", args) if signature else None
            self.conn.emit_signal(None, PATH, IFACE, name, params)

    def _changed(self, **props):
        values = {"Radio": lambda v: GLib.Variant("s", v), "ReceivingUntil": lambda v: GLib.Variant("x", v)}
        self.conn and self.conn.emit_signal(
            None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
            GLib.Variant("(sa{sv}as)", (IFACE, {k: values[k](v) for k, v in props.items()}, [])))

    def _get_property(self, _conn, _sender, _path, _iface, name):
        if name == "Radio":
            return GLib.Variant("s", self.radio.state)
        if name == "ReceivingUntil":
            return GLib.Variant("x", self.receiving_until)
        return None

    def _call(self, _conn, sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        try:
            result = getattr(self, f"_m_{method}")(sender, *args)
        except Exception as e:  # noqa: BLE001
            invocation.return_dbus_error(f"{IFACE}.Error.Failed", str(e))
            return
        invocation.return_value(result)

    # --- Radio -------------------------------------------------------------

    def _radio_state(self, state):
        self._changed(Radio=state)

    def _radio_lost(self):
        self._stop_receiving("stopped")
        self._stop_browsing_all()

    # --- Réception ---------------------------------------------------------

    def _m_StartReceiving(self, _sender, seconds):
        self._set_deadline(seconds)
        if self.receiver is None and "receive" not in self.radio.users:
            self.radio.acquire("receive", self._receive_ready)
        return None

    def _m_StopReceiving(self, _sender):
        self._stop_receiving("stopped")
        return None

    def _m_Answer(self, _sender, request, accept):
        if self.pending and self.pending == request and self.receiver:
            self.pending = None
            self._write_receiver(b"y\n" if accept else b"n\n")
            self._emit("RequestClosed", "ss", request, "answered")
        return None

    def _set_deadline(self, seconds):
        if self._deadline_id:
            GLib.source_remove(self._deadline_id)
        self._deadline_id = GLib.timeout_add_seconds(max(1, seconds), self._deadline)
        self.receiving_until = GLib.get_real_time() + seconds * 1_000_000
        self._changed(ReceivingUntil=self.receiving_until)

    def _deadline(self):
        self._deadline_id = 0
        self._stop_receiving("stopped")
        return GLib.SOURCE_REMOVE

    def _receive_ready(self, error):
        if error:
            self._emit("RadioFailed", "s", error)
            self._stop_receiving("stopped")
            return
        if not self.receiving_until:  # arrêtée entre-temps
            self.radio.release("receive")
            return
        self.receiver = spawn(["owly", "receive", "--dir", self.download_dir],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        parser = owly.ReceiveParser()
        proc = self.receiver

        def on_err(line):
            if proc is self.receiver:
                self._receive_event(parser.line(line))

        def on_partial(text):
            if proc is not self.receiver:
                return False
            event = parser.partial(text)
            self._receive_event(event)
            return event is not None

        def on_out(line):
            if proc is self.receiver:
                self._receive_event(owly.parse_received(line))

        read_lines(proc.stderr, on_err, on_partial)
        read_lines(proc.stdout, on_out)
        threading.Thread(target=lambda: (proc.wait(), GLib.idle_add(self._receiver_exited, proc)),
                         daemon=True).start()

    def _receive_event(self, event):
        if not event:
            return
        kind, *rest = event
        if kind == "request":
            r = rest[0]
            self.pending = f"r{next(self.ids)}"
            files = [{"name": GLib.Variant("s", f["name"]), "type": GLib.Variant("s", f["type"]),
                      "size": GLib.Variant("t", f["size"])} for f in r["files"]]
            self._emit("Request", "ssaa{sv}as", self.pending, r["sender"], files, r["urls"])
        elif kind in ("expired", "withdrawn"):
            if self.pending:
                self._emit("RequestClosed", "ss", self.pending, kind)
                self.pending = None
        elif kind == "failed":
            self._emit("ReceiveFailed", "s", rest[0])
        elif kind == "file":
            self._emit("Received", "s", rest[0])
            self._linger()
        elif kind == "url":
            self._emit("UrlReceived", "s", rest[0])
            self._linger()

    def _linger(self):
        if self._linger_id:
            GLib.source_remove(self._linger_id)

        def done():
            self._linger_id = 0
            self._stop_receiving("stopped")
            return GLib.SOURCE_REMOVE
        self._linger_id = GLib.timeout_add_seconds(LINGER_SECONDS, done)

    def _write_receiver(self, data):
        try:
            self.receiver.stdin.write(data)
            self.receiver.stdin.flush()
        except (OSError, ValueError):
            pass

    def _receiver_exited(self, proc):
        if proc is self.receiver:
            self._stop_receiving("stopped")

    def _stop_receiving(self, reason):
        for attr in ("_deadline_id", "_linger_id"):
            if getattr(self, attr):
                GLib.source_remove(getattr(self, attr))
                setattr(self, attr, 0)
        if self.pending:
            self._emit("RequestClosed", "ss", self.pending, reason)
            self.pending = None
        proc, self.receiver = self.receiver, None
        interrupt(proc)
        was = self.receiving_until
        self.receiving_until = 0
        if was:
            self._changed(ReceivingUntil=0)
        self.radio.release("receive")

    # --- Recherche ---------------------------------------------------------

    def _m_StartBrowsing(self, sender):
        if sender not in self.browsers:
            self.browsers[sender] = Gio.bus_watch_name_on_connection(
                self.conn, sender, Gio.BusNameWatcherFlags.NONE, None,
                lambda _c, name: self._m_StopBrowsing(name))
            if len(self.browsers) == 1:
                self.radio.acquire("browse", self._browse_ready)
        return None

    def _m_StopBrowsing(self, sender):
        watch = self.browsers.pop(sender, None)
        if watch is not None:
            Gio.bus_unwatch_name(watch)
        if not self.browsers:
            self._stop_browsing()
        return None

    def _m_GetDevices(self, _sender):
        devices = [{"mac": GLib.Variant("s", mac), "name": GLib.Variant("s", d["name"]),
                    "model": GLib.Variant("s", d.get("model") or ""),
                    "rssi": GLib.Variant("i", d.get("rssi") or 0)}
                   for mac, d in self.devices.items()]
        return GLib.Variant("(aa{sv})", (devices,))

    def _browse_ready(self, error):
        if error:
            self._emit("RadioFailed", "s", error)
            self._stop_browsing_all()
            return
        if not self.browsers:
            self.radio.release("browse")
            return
        # `owly browse` réveille les iPhone en Bluetooth (BLE-1) et liste ceux
        # qui s'annoncent ; discover demande leur nom aux autres pairs AWDL.
        self._browse_stop = stop = threading.Event()
        self.browse_proc = spawn(["owly", "browse", "--seconds", "86400"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        def on_listed(line):
            if found := owly.parse_listed(line):
                self._device(found[0], {"name": found[1]})
        read_lines(self.browse_proc.stdout, on_listed)
        threading.Thread(target=self._discover_loop, args=(stop,), daemon=True).start()

    def _discover_loop(self, stop):
        while not stop.wait(DISCOVER_EVERY):
            try:
                peers = discover.peers()
            except GLib.Error:
                continue
            for peer, found in zip(peers, self._pool.map(self._ask, peers)):
                GLib.idle_add(self._device, peer["mac"], {"rssi": peer.get("rssi"), **found})

    @staticmethod
    def _ask(peer):
        try:
            return discover.discover(peer["mac"]) or {}
        except Exception:  # noqa: BLE001 : un pair qui ne répond pas, c'est normal
            return {}

    def _device(self, mac, info):
        d = self.devices.get(mac)
        if d is None:
            if not info.get("name"):
                return  # n'apparaît que celui qui accepte et a donné son nom
            d = self.devices[mac] = {"name": info["name"]}
        d.update({k: v for k, v in info.items() if v is not None})
        d["seen"] = time.monotonic()
        self._emit("DeviceSeen", "sssi", mac, d["name"], d.get("model") or "", d.get("rssi") or 0)

    def _prune(self):
        now = time.monotonic()
        for mac, d in list(self.devices.items()):
            if now - d["seen"] > FORGET_SECONDS:
                del self.devices[mac]
                self._emit("DeviceLost", "s", mac)
        return GLib.SOURCE_CONTINUE

    def _stop_browsing(self):
        self._browse_stop.set()
        proc, self.browse_proc = self.browse_proc, None
        interrupt(proc)
        for mac in list(self.devices):
            self._emit("DeviceLost", "s", mac)
        self.devices.clear()
        self.radio.release("browse")

    def _stop_browsing_all(self):
        for sender in list(self.browsers):
            self._m_StopBrowsing(sender)
        self._stop_browsing()

    # --- Envoi -------------------------------------------------------------

    def _m_Send(self, _sender, mac, files, urls):
        if not files and not urls:
            raise ValueError("rien à envoyer")
        transfer = f"s{next(self.ids)}"
        user = f"send:{transfer}"
        args = ["owly", "send", "--mac", mac] + ([a for u in urls for a in ("--url", u)] or list(files))

        def ready(error):
            if error:
                self._progress(transfer, "failed", detail=error)
                self.radio.release(user)
                return
            self._progress(transfer, "waiting")
            self.sends[transfer] = spawn(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._watch_send(transfer, user, self.sends[transfer])
        self.radio.acquire(user, ready)
        return GLib.Variant("(s)", (transfer,))

    def _watch_send(self, transfer, user, proc):
        def on_err(part):
            event = owly.parse_send_stderr(part)
            if event and event[0] == "progress":
                self._progress(transfer, "progress", event[1], event[2])
            elif event and event[0] == "accepted":
                self._progress(transfer, "accepted")

        read_lines(proc.stderr, on_err, split=rb"[\r\n]")

        def wait():
            out = proc.stdout.read().decode(errors="replace")
            proc.wait()
            GLib.idle_add(finish, owly.parse_send_result(out, proc.returncode))

        def finish(result):
            self.sends.pop(transfer, None)
            self._progress(transfer, result[0], detail=result[1] if len(result) > 1 else "")
            self.radio.release(user)
        threading.Thread(target=wait, daemon=True).start()

    def _progress(self, transfer, state, sent=0, total=0, detail=""):
        self._emit("SendProgress", "sstts", transfer, state, sent, total, detail)

    # --- Fin ---------------------------------------------------------------

    def _maybe_exit(self):
        busy = self.radio.users or self.browsers or self.sends or self.receiving_until
        if busy:
            self._idle_since = time.monotonic()
        elif time.monotonic() - self._idle_since > IDLE_EXIT_SECONDS:
            self.loop.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def shutdown(self):
        self._stop_receiving("stopped")
        self._stop_browsing_all()
        for proc in self.sends.values():
            interrupt(proc)
        if self.radio.lease is not None:
            self.radio._give_back()
            self.radio.bus.flush_sync(None)


def main():
    loop = GLib.MainLoop()
    service = Service(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), GLib.SOURCE_REMOVE)[1])
    Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
                     lambda conn, _name: service.register(conn), None,
                     lambda _conn, _name: loop.quit())
    loop.run()
    service.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
