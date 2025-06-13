from .utils import clear_container
from gi.repository import Gtk, Adw
import gi
gi.require_version('Gtk', '4.0')


def show_settings(self):
    # Очистка предыдущего контента
    clear_container(self.settings_page)

    title = Gtk.Label(label=_("Settings"), css_classes=["title"])
    self.settings_page.append(title)
