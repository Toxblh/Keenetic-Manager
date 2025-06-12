import gi
import threading

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Adw, GLib

from .utils import clear_container
from .ui import create_client_row

# Храним виджеты клиентов по MAC
CLIENT_WIDGETS_KEY = '_client_widgets'
CLIENTS_LISTBOX_KEY = '_clients_listbox'
CLIENTS_SCROLLED_KEY = '_clients_scrolled'
CLIENTS_REFRESH_TIMER_KEY = '_clients_refresh_timer'


def show_online_clients(self):
    # Очистка и инициализация UI только один раз
    clear_container(self.clients_page)
    self._client_widgets = {}  # mac -> row widget

    # Создаём ScrolledWindow и ListBox один раз
    scrolled_window = Gtk.ScrolledWindow()
    scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled_window.set_min_content_height(400)
    scrolled_window.set_margin_start(10)
    scrolled_window.set_margin_end(10)
    scrolled_window.set_vexpand(True)
    self.clients_page.append(scrolled_window)

    listbox = Gtk.ListBox()
    scrolled_window.set_child(listbox)
    self._clients_listbox = listbox
    self._clients_scrolled = scrolled_window

    # Сообщение если не выбран роутер
    if not self.current_router:
        label = Gtk.Label(label=_('Please select a router.'))
        self.clients_page.append(label)
        return

    # Первый раз — сразу загружаем данные
    def initial_update():
        update_clients_data(self)
        return False
    GLib.idle_add(initial_update)

    # Запускаем автообновление
    start_clients_auto_refresh(self)


def start_clients_auto_refresh(self):
    # Останавливаем предыдущий таймер если был
    if hasattr(self, CLIENTS_REFRESH_TIMER_KEY):
        return  # Уже запущен
    def refresh():
        threading.Thread(target=update_clients_data, args=(self,), daemon=True).start()
        return True
    timer_id = GLib.timeout_add_seconds(2, refresh)
    setattr(self, CLIENTS_REFRESH_TIMER_KEY, timer_id)


def update_clients_data(self):
    # Получаем данные в потоке
    online_clients = self.current_router.get_online_clients() if self.current_router else []
    # Фильтруем только клиентов с валидным IP и link=="up"
    def is_valid_ip(ip):
        parts = ip.split('.')
        return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
    def is_online(client):
        data = client.get("data", {})
        state = data.get("link") == "up" or data.get("mws", {}).get("link") == "up"
        return bool(state)
    filtered_clients = [c for c in online_clients if is_valid_ip(c.get("ip", "")) and is_online(c)]
    def ip_key(client):
        ip = client.get("ip", "")
        try:
            return tuple(int(part) for part in ip.split("."))
        except Exception:
            return (0, 0, 0, 0)
    clients_sorted = sorted(filtered_clients, key=ip_key)
    def update_ui():
        # Если нет listbox — UI не инициализирован
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
                # Обновить существующий row
                row = client_widgets[mac]
                if hasattr(row, 'update_data'):
                    row.update_data(client)
            else:
                # Создать новый row
                row = create_client_row(client)
                client_widgets[mac] = row
                listbox.append(row)
        # Удалить строки для клиентов, которых больше нет
        for mac in list(client_widgets.keys()):
            if mac not in macs_seen:
                row = client_widgets[mac]
                listbox.remove(row)
                del client_widgets[mac]
        return False
    GLib.idle_add(update_ui)
