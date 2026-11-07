"""The Devices tab's Network lights card: look for WiZ and Govee lights on the network."""

from gi.repository import GLib, Gtk

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
        c.append(hbox(8, self._host, button(_("Add"), "add", "tonal small", self._add_host),
                      button(_("Test"), "troubleshoot", "text small", self._test)))
        self._hosts = wrap_row(6)
        self._hosts_now = None
        c.append(self._hosts)
        self._probe = label("", ("small",), wrap=True)
        self._probe.set_visible(False)
        c.append(self._probe)
        self._anyway_ip = ""
        self._anyway = hbox(8, button(_("Add as a Govee light"), "add", "tonal small", lambda: self._add_light("govee")),
                            button(_("Add as a WiZ light"), "add", "text small", lambda: self._add_light("wiz")))
        self._anyway.set_visible(False)
        c.append(self._anyway)

    def _test(self):
        ip = self._host.get_text().strip()
        if not ip:
            self.app.toast(_("Type the light's address first."))
            return
        self._probe.set_label(_("Asking {ip}…").format(ip=ip))
        self._probe.set_visible(True)
        self._anyway.set_visible(False)

        def done(r):
            if not r.get("ok"):
                self._probe.set_label(r.get("error") or _("Couldn't test it"))
                return
            p = r.get("probe") or {}
            if p.get("govee") or p.get("wiz"):
                self._probe.set_label(_("{ip} answered ({what}). It shows up with the next search; add its address "
                                        "above if it's on another network.").format(
                    ip=p.get("ip"), what=", ".join(p.get("heard") or [])))
                return
            fw = p.get("firewall")
            text = _("No answer from {ip}. Either no light with LAN Control on is there, or its answers don't get "
                     "back to this PC: the router has to let the lights reach this PC on UDP port 4002 "
                     "(a WiZ light answers from 38899).").format(ip=p.get("ip"))
            if fw:
                text += " " + _("This PC's own firewall ({fw}) is on and can drop them too.").format(fw=fw)
            text += " " + _("Or add it anyway: Iridia then just sends it colours, which usually gets through.")
            self._probe.set_label(text)
            self._anyway_ip = p.get("ip", "")
            self._anyway.set_visible(True)
        self.app.bg(lambda: self.app.client.netlights(probe=ip), done)

    def _open(self, name):
        if not self.app.show_device_card(name):
            self.app.toast(_("Its card shows up in a moment, once Iridia has added it."))

    def _add_light(self, kind):
        if self._anyway_ip:
            self._anyway.set_visible(False)
            self._probe.set_visible(False)
            self._host.set_text("")
            name = f"{'WiZ' if kind == 'wiz' else 'Govee'} {self._anyway_ip}"
            self._send(add_light={"kind": kind, "ip": self._anyway_ip})
            self._jump_to(name, 12)

    def _jump_to(self, name, tries):
        """Open the new light's card once the daemon has added it (a second or two)."""
        if self.app.show_device_card(name):
            self.app.toast(_("Added: this is its card. Settings next to it in Network lights comes back here."))
            return
        if tries > 0:
            GLib.timeout_add(500, lambda: (self._jump_to(name, tries - 1), False)[1])
        else:
            self.app.toast(_("Added. Its card is above the Network lights card: Settings next to it goes there."))

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
        key = [(f["name"], f.get("net", {}).get("ip"), f.get("net", {}).get("manual")) for f in found]
        if key != self._found_now:
            self._found_now = key
            widgets.clear(self._list)
            for f in found:
                net = f.get("net", {})
                row = label(f"{f['name']}  ·  {net.get('ip', '')}"
                            + ("  ·  " + _("added by address") if net.get("manual") else ""), ("body",))
                row.set_hexpand(True)
                name = f["name"]
                go = button(_("Settings"), "tune", "text small", lambda n=name: self._open(n),
                            tooltip=_("Its card: colours, brightness, on and off"))
                if net.get("manual"):
                    addr = net.get("ip")
                    rm = button(None, "close", "flat small",
                                lambda ip=addr: self._send(remove_light=ip), tooltip=_("Remove"))
                    self._list.append(hbox(8, row, go, rm))
                else:
                    self._list.append(hbox(8, row, go))
        if not on:
            self._note.set_label(_("Off: nothing is sent to the network."))
        elif n.get("error"):
            self._note.set_label(n["error"])
        elif not found:
            self._note.set_label(_("Looking… Lights answer within a few seconds. A Govee light that doesn't show up "
                                   "needs LAN Control switched on in the Govee app."))
        else:
            self._note.set_label(_("Each light has its own card above, like a strip: pattern, brightness, scenes and the rest work the same."))
