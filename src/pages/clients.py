from .ui import create_client_row
from .utils import clear_container
from gi.repository import Gtk, Adw, GLib
import gi
import threading

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

CLIENTS_REFRESH_TIMER_KEY = '_clients_refresh_timer'

def start_clients_auto_refresh(self):
    if hasattr(self, CLIENTS_REFRESH_TIMER_KEY):
        return  # Уже запущен

    def refresh():
        threading.Thread(target=update_clients_data,
                         args=(self,), daemon=True).start()
        return True

    timer_id = GLib.timeout_add_seconds(2, refresh)
    setattr(self, CLIENTS_REFRESH_TIMER_KEY, timer_id)


def show_online_clients(self):
    clear_container(self.clients_page)
    self._client_widgets = {}

    # --- Search input ---
    search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    search_entry = Gtk.Entry()
    search_entry.set_placeholder_text(_('Search by name, IP or MAC'))
    search_entry.set_margin_bottom(12)
    search_entry.set_margin_top(6)
    search_entry.set_margin_start(6)
    search_entry.set_margin_end(0)
    search_entry.set_hexpand(True)
    search_box.append(search_entry)

    clear_button = Gtk.Button(label=_('Clear'))
    clear_button.set_tooltip_text(_('Clear search field'))
    clear_button.set_margin_bottom(12)
    clear_button.set_margin_top(6)
    clear_button.set_margin_end(8)

    def on_clear_clicked(_btn):
        search_entry.set_text("")
        search_entry.grab_focus()
    clear_button.connect('clicked', on_clear_clicked)
    search_box.append(clear_button)

    self.clients_page.append(search_box)\

    scrolled_window = Gtk.ScrolledWindow()
    scrolled_window.set_policy(
        Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled_window.set_min_content_height(400)
    scrolled_window.set_vexpand(True)
    self.clients_page.append(scrolled_window)

    listbox = Gtk.ListBox()
    scrolled_window.set_child(listbox)
    self._clients_listbox = listbox

    if not self.current_router:
        label = Gtk.Label(label=_('Please select a router.'))
        self.clients_page.append(label)
        return

    self._clients_search_text = ""
    self._all_online_clients = []  # локальное состояние

    def filter_clients(clients, text):
        text = text.strip().lower()
        if not text:
            return clients
        filtered = []
        for client in clients:
            name = client.get("name", "").lower()
            mac = client.get("mac", "").lower()
            ip = client.get("ip", "").lower() if client.get("ip") else ""
            if text in name or text in mac or text in ip:
                filtered.append(client)
        return filtered
    self._clients_filter_clients = filter_clients
    self._clients_search_entry = search_entry

    def on_search_changed(entry):
        self._clients_search_text = entry.get_text()
        update_clients_ui(self)
    search_entry.connect("changed", on_search_changed)

    def initial_update():
        update_clients_data(self)
        search_entry.grab_focus()
        return False
    GLib.idle_add(initial_update)

    start_clients_auto_refresh(self)

def update_clients_ui(self):
    def is_valid_ip(ip):
        parts = ip.split('.')
        return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

    def is_online(client):
        data = client.get("data", {})
        state = data.get("link") == "up" or data.get(
            "mws", {}).get("link") == "up"
        return bool(state)
    # Фильтруем только клиентов с валидным IP и online
    filtered_clients = [c for c in self._all_online_clients if is_valid_ip(
        c.get("ip", "")) and is_online(c)]
    # --- Apply search filter if present ---
    search_text = getattr(self, '_clients_search_text', '')
    filter_clients = getattr(self, '_clients_filter_clients', None)
    if filter_clients:
        filtered_clients = filter_clients(filtered_clients, search_text)

    def ip_key(client):
        ip = client.get("ip", "")
        try:
            return tuple(int(part) for part in ip.split("."))
        except Exception:
            return (0, 0, 0, 0)
    clients_sorted = sorted(filtered_clients, key=ip_key)

    def update_ui():
        if not hasattr(self, '_clients_listbox'):
            return False
        listbox = self._clients_listbox
        client_widgets = getattr(self, '_client_widgets', {})
        macs_seen = set()
        for client in clients_sorted:
            mac = client.get('mac')
            if not mac:
                continue
            macs_seen.add(mac)
            if mac in client_widgets:
                row = client_widgets[mac]
                if hasattr(row, 'update_data'):
                    row.update_data(client)
            else:
                row = create_client_row(client)
                client_widgets[mac] = row
                listbox.append(row)
        for mac in list(client_widgets.keys()):
            if mac not in macs_seen:
                row = client_widgets[mac]
                listbox.remove(row)
                del client_widgets[mac]
        return False
    GLib.idle_add(update_ui)

def update_clients_data(self):
    online_clients = self.current_router.get_online_clients() if self.current_router else []
    self._all_online_clients = online_clients
    update_clients_ui(self)
