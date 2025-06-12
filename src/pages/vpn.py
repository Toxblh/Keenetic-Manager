import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Adw

from .utils import clear_container, get_local_mac_addresses

def on_value_changed(toggle_group, __, mac_address, self):
    index = toggle_group.get_active()
    name = toggle_group.get_active_name()

    if index == 0:
        # Если выбрана опция "По умолчанию", применяем политику по умолчанию
        self.apply_policy_to_client(mac_address, None)
    else:
        self.apply_policy_to_client(mac_address, name)

def show_vpn_clients(self):
    # Очистка предыдущего контента
    clear_container(self.vpn_page)

    if not self.current_router:
        label = Gtk.Label(label=_("Please select a router."))
        self.vpn_page.append(label)
        return

    # Получение данных о онлайн клиентах
    online_clients = self.current_router.get_online_clients()
    policies = self.current_router.get_policies()

    if not online_clients:
        label = Gtk.Label(label=_("Failed to retrieve the list of clients."))
        self.vpn_page.append(label)
        return

    # Получение MAC-адресов локальных интерфейсов
    local_macs = get_local_mac_addresses()

    # Сначала сортируем клиентов: локальные, онлайн, остальные
    def is_online(client):
        data = client.get("data", {})
        return data.get("link") == "up" or data.get("mws", {}).get("link") == "up"
    def client_sort_key(client):
        mac = client.get("mac", "").lower()
        if mac in local_macs:
            return (0,)
        elif is_online(client):
            return (1, 0)
        else:
            return (1, 1)
    online_clients.sort(key=client_sort_key)

    # Создаем ScrolledWindow
    scrolled_window = Gtk.ScrolledWindow()
    scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled_window.set_min_content_height(400)
    scrolled_window.set_margin_start(10)
    scrolled_window.set_margin_end(10)
    scrolled_window.set_vexpand(True)
    self.vpn_page.append(scrolled_window)

    # Создаем Grid
    grid = Gtk.Grid(column_spacing=10, row_spacing=10)
    grid.set_column_homogeneous(False)
    scrolled_window.set_child(grid)

    # Добавляем заголовки для каждой политики
    policy_names = []
    for policy_name, policy_info in policies.items():
        policy_names.append((policy_name, policy_info.get("description", policy_name)))

    # Отображение клиентов в таблице
    for row_idx, client in enumerate(online_clients, start=1):
        client_mac = client.get("mac", "").lower()
        client_name = client.get("name", "Unknown")
        client_policy = client.get("policy", None)

        # Проверяем, является ли клиент текущим компьютером
        is_current_pc = client_mac in local_macs
        is_deny = client.get("deny", True)

        # Проверяем статус online
        state = client.get("data", {}).get("link") == "up" or client.get("data", {}).get("mws", {}).get("link") == "up"
        online = True if state else False
        color = "green" if online else "red"
        status_label = Gtk.Label()
        status_label.set_markup(f'<span foreground="{color}">•</span>')
        grid.attach(status_label, 0, row_idx, 1, 1)

        # Отображаем имя клиента и его MAC-адрес
        # name_text = f"{client_name} ({client_mac})"
        name_text = f"{client_name}"
        if is_current_pc:
            name_text += _(" [This is you]")
        if is_deny:
            name_text += " (x)"
        name_label = Gtk.Label(label=name_text)
        name_label.set_xalign(0)
        grid.attach(name_label, 1, row_idx, 1, 1)

        toggleGroup = Adw.ToggleGroup()
        toggleGroup.set_css_classes(["round"])
        toggleOption = Adw.Toggle(label="Default", name="Default")
        toggleGroup.add(toggleOption)

        # Добавляем кнопки политик
        for idx, (policy_name, policy_desc) in enumerate(policy_names):
            toggleOption = Adw.Toggle(label=policy_desc, name=policy_name, icon_name="network-vpn-symbolic", tooltip="Apply {policy_name} policy".format(policy_name=policy_name))
            toggleGroup.add(toggleOption)

            if client_policy == policy_name:
                toggleGroup.set_active(idx + 1)

        grid.attach(toggleGroup, 2, row_idx, 1, 1)
        toggleGroup.connect("notify::active", on_value_changed, client_mac, self)
