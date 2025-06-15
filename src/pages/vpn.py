from .policy_toggle import PolicyToggleWidget
from .utils import clear_container, get_local_mac_addresses
from gi.repository import Gtk, Adw, GLib
import threading
import gi
gi.require_version('Gtk', '4.0')


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

    loading_label = Gtk.Label(label=_("Loading..."))
    self.vpn_page.append(loading_label)

    if not self.current_router:
        label = Gtk.Label(label=_("Please select a router."))
        self.vpn_page.append(label)
        return

    def render_vpn_clients(online_clients, policies):
        clear_container(self.vpn_page)

        if not online_clients:
            label = Gtk.Label(
                label=_("Failed to retrieve the list of clients."))
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

        # --- Search input + Update button ---
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        update_button = Gtk.Button(label=_("Update"))
        update_button.set_icon_name("view-refresh-symbolic")
        update_button.set_tooltip_text(_("Update the list of VPN clients"))
        update_button.set_margin_bottom(12)
        update_button.set_margin_top(6)
        update_button.set_margin_start(6)
        update_button.set_margin_end(0)
        update_button.connect("clicked", lambda _: threading.Thread(
            target=lambda: update_vpn_clients(), daemon=True).start())
        search_box.append(update_button)

        search_entry = Gtk.Entry()
        search_entry.set_placeholder_text(_("Search by name, IP or MAC"))
        search_entry.set_margin_bottom(12)
        search_entry.set_margin_top(6)
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

        self.vpn_page.append(search_box)
        search_entry.grab_focus()  # Автофокус

        # Создаем ScrolledWindow
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_min_content_height(400)
        scrolled_window.set_vexpand(True)
        self.vpn_page.append(scrolled_window)

        # Создаем Grid
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_column_homogeneous(False)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        scrolled_window.set_child(grid)

        # Добавляем заголовки для каждой политики
        policy_names = []
        for policy_name, policy_info in policies.items():
            policy_names.append(
                (policy_name, policy_info.get("description", policy_name)))

        # --- Filtering logic ---
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

        # --- Render table rows ---
        def render_table(filtered_clients):
            clear_container(grid)
            for row_idx, client in enumerate(filtered_clients, start=1):
                client_mac = client.get("mac", "").lower()
                client_name = client.get("name", "Unknown")
                client_policy = client.get("policy", None)
                is_current_pc = client_mac in local_macs
                is_deny = client.get("deny", True)
                state = client.get("data", {}).get("link") == "up" or client.get(
                    "data", {}).get("mws", {}).get("link") == "up"
                online = True if state else False
                color = "green" if online else "red"
                status_label = Gtk.Label()
                status_label.set_markup(f'<span foreground="{color}">•</span>')
                grid.attach(status_label, 0, row_idx, 1, 1)
                name_text = f"{client_name}"
                if is_current_pc:
                    name_text += _(" [This is you]")
                if is_deny:
                    name_text += " (x)"
                name_label = Gtk.Label(label=name_text)
                name_label.set_xalign(0)
                grid.attach(name_label, 1, row_idx, 1, 1)
                policy_widget = PolicyToggleWidget(
                    policies=policy_names,
                    current_policy=client_policy,
                    deny=is_deny,
                    router=getattr(self, 'current_router', None),
                    mac=client_mac,
                    policy_names=policy_names
                )
                grid.attach(policy_widget, 2, row_idx, 1, 1)

        # --- Connect search ---
        def on_search_changed(entry):
            text = entry.get_text()
            filtered = filter_clients(online_clients, text)
            render_table(filtered)
        search_entry.connect("changed", on_search_changed)

        # Initial render
        render_table(online_clients)

    def update_vpn_clients():
        online_clients = self.current_router.get_online_clients()
        policies = self.current_router.get_policies()
        GLib.idle_add(render_vpn_clients, online_clients, policies)

    threading.Thread(target=update_vpn_clients, daemon=True).start()
