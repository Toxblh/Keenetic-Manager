# router_manager_app.py
from .router_manager import RouterManager
from gi.repository import Adw, Gio
import gi
gi.require_version('Adw', '1')

Adw.init()


class RouterManagerApplication(Adw.Application):
    def __init__(self, version):
        super().__init__(application_id='ru.toxblh.KeeneticManager',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.version = version
        self.create_action('quit', lambda *_: self.quit(), ['<primary>q'])
        self.create_action('about', lambda *_: self.on_about_action(), [])

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

    def on_about_action(self, *args):
        """Callback for the app.about action."""
        about = Adw.AboutDialog(
            application_name=_('Keenetic Manager'),
            application_icon='ru.toxblh.KeeneticManager',
            developer_name=_('Anton Palgunov (Toxblh)'),
            version=self.version,
            developers=[_('Anton Palgunov (Toxblh)')],
            copyright=_('© 2024-2026 Anton Palgunov (Toxblh)')
        )
        about.add_link("GitHub", "https://github.com/Toxblh/Keenetic-Manager")
        about.add_link(_("Donate"), "https://toxblh.ru/support")
        about.set_translator_credits(_('translator-credits'))
        about.present()
