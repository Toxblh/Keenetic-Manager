# router_manager_app.py
import gi
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, Gtk

from router_manager import RouterManager

Adw.init()

class RouterManagerApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.toxblh.RouterManager', flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        win = RouterManager(application=self)
        win.present()
