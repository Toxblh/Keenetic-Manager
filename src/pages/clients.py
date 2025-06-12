import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Adw

from .utils import clear_container
from .ui import create_client_row

def show_online_clients(self):
        # Очистка предыдущего контента
        clear_container(self.clients_page)

        if not self.current_router:
            label = Gtk.Label(label=_("Please select a router."))
            self.clients_page.append(label)
            return

        # Получение данных о онлайн клиентах
        online_clients = self.current_router.get_online_clients()

        if not online_clients:
            label = Gtk.Label(label=_("Failed to retrieve the list of clients."))
            self.clients_page.append(label)
            return

        # Создаем ScrolledWindow
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_min_content_height(400)
        scrolled_window.set_margin_start(10)
        scrolled_window.set_margin_end(10)
        scrolled_window.set_vexpand(True)
        self.clients_page.append(scrolled_window)

        # Отображение клиентов в списке
        listbox = Gtk.ListBox()
        scrolled_window.set_child(listbox)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_column_homogeneous(False)
        grid.set_hexpand(True)
        grid.set_vexpand(False)
        listbox.append(grid)

        for idx, (client) in enumerate(online_clients):
            state = client.get("data", {}).get("link") == "up" or client.get("data", {}).get("mws", {}).get("link") == "up"
            online =  True if state else False

            if online:
                create_client_row(client, grid, idx)
