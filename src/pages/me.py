from .utils import clear_container
from gi.repository import Gtk, Adw
import gi
gi.require_version('Gtk', '4.0')


def show_me(self):
    # Очистка предыдущего контента
    clear_container(self.me_page)

    title = Gtk.Label(label=_("Me"), css_classes=["title"])
    self.me_page.append(title)
