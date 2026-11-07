"""The Devices tab's Network lights card: look for WiZ and Govee lights on the network."""

from iridia.i18n import _
from iridia.ui import widgets
from iridia.ui.widgets import button, card, hbox, label, switch_row, vbox


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
