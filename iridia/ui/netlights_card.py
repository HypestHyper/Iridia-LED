"""The Devices tab's Network lights card: look for WiZ and Govee lights on the network."""

from gi.repository import Gtk

from iridia.i18n import _
from iridia.ui import widgets
from iridia.ui.widgets import button, card, hbox, label, switch_row, vbox, wrap_row


class NetLightsCard:
    def __init__(self, app):
        self.app = app
        self._found_now = None
        self.widget = card()
        c = self.widget
        c.append(label(_("Network lights"), ("heading",)))
        c.append(label(_("Philips WiZ and Govee lights on your Wi-Fi, found and driven over the network: nothing "
                         "to pair, and they keep working in their own apps and in Google Home. Each one shows one "
                         "colour. Govee lights need LAN Control switched on (Govee app, the light's settings)."),
                       ("small", "dim"), wrap=True))
        row, self._on = switch_row(_("Look for WiZ and Govee lights"), False, lambda v: self._send(enabled=v))
        c.append(row)
        self._list = vbox(4)
        c.append(self._list)
        self._note = label("", ("small", "faint"), wrap=True)
        c.append(self._note)
        self._again = button(_("Look again"), "refresh", "tonal small", lambda: self._send(scan=True))
        c.append(hbox(8, self._again))
        c.append(label(_("Other networks"), ("body",)))
        c.append(label(_("Lights on another VLAN or subnet (an IoT network, say) don't hear the search. Give their "
                         "address, or the whole network, and they're asked directly. The router has to let this "
                         "PC reach them (UDP 38899 for WiZ, 4001 and 4003 for Govee) and Govee's answers back to "
                         "it (UDP 4002)."), ("small", "dim"), wrap=True))
        self._host = Gtk.Entry(placeholder_text=_("Address or network, like 192.168.20.0/24"), hexpand=True)
        self._host.connect("activate", lambda *_a: self._add_host())
        c.append(hbox(8, self._host, button(_("Add"), "add", "tonal small", self._add_host)))
        self._hosts = wrap_row(6)
        self._hosts_now = None
        c.append(self._hosts)

    def _add_host(self):
        h = self._host.get_text().strip()
        if h:
            self._host.set_text("")
            self._send(add_host=h)

    def _send(self, **kw):
        def done(r):
            if not r.get("ok"):
                self.app.toast(r.get("error") or _("Couldn't save"))
            self.update(r)
        self.app.bg(lambda: self.app.client.netlights(**kw), done)

    def update(self, n):
        if not n:
            return
        on = bool(n.get("enabled"))
        hosts = n.get("hosts") or []
        if hosts != self._hosts_now:
            self._hosts_now = hosts
            widgets.clear(self._hosts)
            for h in hosts:
                self._hosts.append(button(h, "close", "tonal small", lambda h=h: self._send(remove_host=h),
                                          tooltip=_("Remove")))
            self._hosts.set_visible(bool(hosts))
        self._on.set_value(on)
        self._again.set_visible(on)
        found = n.get("found") or []
        key = [(f["name"], f.get("net", {}).get("ip")) for f in found]
        if key != self._found_now:
            self._found_now = key
            widgets.clear(self._list)
            for f in found:
                ip = f.get("net", {}).get("ip", "")
                self._list.append(label(f"{f['name']}  ·  {ip}", ("body",)))
        if not on:
            self._note.set_label(_("Off: nothing is sent to the network."))
        elif n.get("error"):
            self._note.set_label(n["error"])
        elif not found:
            self._note.set_label(_("Looking… Lights answer within a few seconds. A Govee light that doesn't show up "
                                   "needs LAN Control switched on in the Govee app."))
        else:
            self._note.set_label(_("Each light has its own card above, like a strip: pattern, brightness, scenes and the rest work the same."))
