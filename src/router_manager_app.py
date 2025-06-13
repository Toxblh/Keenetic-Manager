# router_manager_app.py
from .router_manager import RouterManager
from gi.repository import Adw, Gio
import gi
gi.require_version('Adw', '1')

Adw.init()


class RouterManagerApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id='ru.toxblh.KeeneticManager',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.create_action('quit', lambda *_: self.quit(), ['<primary>q'])

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = RouterManager(application=self)
        win.present()

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)
