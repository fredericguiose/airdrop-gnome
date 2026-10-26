"""Faux owlyd sur le bus de session : Acquire/Release comptés, pas de radio."""

from gi.repository import Gio, GLib

XML = """
<node><interface name="io.github.t4t5.Owly.Radio1">
  <method name="Acquire"><arg type="u" direction="in"/><arg type="t" direction="out"/><arg type="a{sv}" direction="out"/></method>
  <method name="Release"><arg type="t" direction="in"/></method>
  <method name="TestCounts"><arg type="u" direction="out"/><arg type="u" direction="out"/><arg type="b" direction="out"/></method>
  <property name="Peers" type="aa{sv}" access="read"/>
  <signal name="StateChanged"><arg type="t"/><arg type="s"/><arg type="s"/></signal>
</interface></node>
"""
state = {"acquires": 0, "releases": 0, "lease": None, "next": 1}


def call(conn, _sender, path, iface, method, params, inv):
    if method == "Acquire":
        if state["lease"] is not None:
            inv.return_dbus_error("io.github.t4t5.Owly.Error.Busy", "Another lease holds the radio.")
            return
        state["acquires"] += 1
        state["lease"] = state["next"]
        state["next"] += 1
        link = {"interface": GLib.Variant("s", "awdl0"), "index": GLib.Variant("u", 99),
                "mac": GLib.Variant("s", "02:00:00:00:00:01"), "address": GLib.Variant("s", "fe80::1")}
        inv.return_value(GLib.Variant("(ta{sv})", (state["lease"], link)))
        conn.emit_signal(None, path, iface, "StateChanged", GLib.Variant("(tss)", (state["lease"], "up", "")))
    elif method == "Release":
        (lease,) = params.unpack()
        if lease == state["lease"]:
            state["releases"] += 1
            state["lease"] = None
            conn.emit_signal(None, path, iface, "StateChanged", GLib.Variant("(tss)", (lease, "idle", "released")))
        inv.return_value(None)
    elif method == "TestCounts":
        inv.return_value(GLib.Variant("(uub)", (state["acquires"], state["releases"], state["lease"] is not None)))


def prop(*_):
    return GLib.Variant("aa{sv}", [])


def acquired(conn, _name):
    conn.register_object_with_closures2("/io/github/t4t5/Owly", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, prop, None)


Gio.bus_own_name(Gio.BusType.SESSION, "io.github.t4t5.Owly", Gio.BusNameOwnerFlags.NONE, acquired, None, None)
GLib.MainLoop().run()
