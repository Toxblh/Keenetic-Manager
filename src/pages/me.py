from .utils import clear_container
from gi.repository import Gtk, Adw
import gi
import threading
import time
import netifaces
from .utils import clear_container, get_local_mac_addresses

gi.require_version('Gtk', '4.0')


def get_interface_stats(interface):
    try:
        with open(f"/sys/class/net/{interface}/statistics/rx_bytes") as f:
            rx_bytes = int(f.read())
        with open(f"/sys/class/net/{interface}/statistics/tx_bytes") as f:
            tx_bytes = int(f.read())
        with open(f"/sys/class/net/{interface}/operstate") as f:
            state = f.read().strip()
        return rx_bytes, tx_bytes, state
    except Exception:
        return 0, 0, 'down'


def show_me(self):
    # Очистка предыдущего контента
    clear_container(self.me_page)
    try:
        _ = __builtins__._
    except AttributeError:
        def _(s): return s

    # Получаем локальные MAC-адреса и интерфейсы
    macs = []
    for interface in netifaces.interfaces():
        if interface == 'lo':
            continue  # Исключаем loopback
        addrs = netifaces.ifaddresses(interface)
        mac = None
        iface_type = "Ethernet"
        # Определяем тип интерфейса
        if interface.startswith('wl') or interface.startswith('wlan') or interface.startswith('wifi'):
            iface_type = "Wi-Fi"
        elif interface.startswith('en') or interface.startswith('eth'):
            iface_type = "Ethernet"
        else:
            if netifaces.AF_INET in addrs:
                for addr in addrs[netifaces.AF_INET]:
                    if 'broadcast' in addr:
                        iface_type = "Ethernet"
                        break
        if netifaces.AF_LINK in addrs:
            for link in addrs[netifaces.AF_LINK]:
                mac = link.get('addr')
                if mac:
                    break
        if mac:
            macs.append((interface, mac.lower(), iface_type))

    # Получаем политики
    policies = self.current_router.get_policies() if getattr(self, 'current_router', None) else {}
    policy_names = [(policy_name, policy_info.get("description", policy_name)) for policy_name, policy_info in policies.items()]

    # Сетка для интерфейсов -> теперь FlowBox для карточек
    flowbox = Gtk.FlowBox()
    flowbox.set_max_children_per_line(3)
    flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
    self.me_page.append(flowbox)

    def get_ip(interface):
        addrs = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addrs:
            return addrs[netifaces.AF_INET][0].get('addr', 'N/A')
        return 'N/A'

    card_widgets = []
    usage_stats = {}
    usage_window = 5  # секунд для анализа активности
    for idx, (interface, mac, iface_type) in enumerate(macs):
        client_name = None
        client_found = False
        online = False
        if hasattr(self, 'current_router') and self.current_router:
            clients = self.current_router.get_online_clients()
            for c in clients:
                if c.get('mac', '').lower() == mac:
                    client_name = c.get('name', interface)
                    client_policy = c.get('policy', None)
                    state = c.get("data", {}).get("link") == "up" or c.get("data", {}).get("mws", {}).get("link") == "up"
                    online =  True if state else False
                    client_found = True
                    break
            if not client_found:
                continue
        else:
            client_name = interface
            client_policy = None
        # Карточка
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.set_css_classes(["card", "boxed"])
        card.set_margin_top(6)
        card.set_margin_bottom(6)
        card.set_margin_start(6)
        card.set_margin_end(6)
        card.set_vexpand(False)
        card.set_hexpand(False)
        card.set_spacing(10)

        active_grid = Gtk.Grid(column_spacing=6, row_spacing=4)
        active_grid.set_column_homogeneous(False)
        active_grid.set_margin_top(15)
        active_grid.set_margin_start(20)
        active_grid.set_margin_end(20)
        active_grid.set_hexpand(True)
        card.append(active_grid)

        # Заголовок — имя клиента
        header_label = Gtk.Label()
        header_label.set_markup(f'<b>{client_name}</b>')
        header_label.set_halign(Gtk.Align.START)

        active_grid.attach(header_label, 0, 0, 1, 1)
        # card.append(header_label)

        # Таблица для свойств
        info_grid = Gtk.Grid(column_spacing=6, row_spacing=4)
        info_grid.set_column_homogeneous(False)
        info_grid.set_margin_top(5)
        info_grid.set_margin_start(20)
        card.append(info_grid)
        def add_info_row(row, label_text, value_text, markup=False):
            label = Gtk.Label(label=label_text, xalign=0)
            label.get_style_context().add_class("dim-label")
            label.set_halign(Gtk.Align.START)
            label.set_size_request(100, -1)
            if markup:
                value = Gtk.Label()
                value.set_markup(value_text)
            else:
                value = Gtk.Label(label=value_text, xalign=0)
            value.set_halign(Gtk.Align.START)
            info_grid.attach(label, 0, row, 1, 1)
            info_grid.attach(value, 1, row, 1, 1)
            return value
        row = 0
        add_info_row(row, "Name:", interface); row += 1
        add_info_row(row, "Type:", iface_type); row += 1
        # State: online/offline по данным роутера
        state_markup = '<span foreground="green">●</span> Online' if online else '<span foreground="gray">●</span> Offline'
        state_label = add_info_row(row, "State:", state_markup, markup=True); row += 1
        ip = get_ip(interface)
        add_info_row(row, "IP:", ip); row += 1
        add_info_row(row, "MAC:", mac); row += 1
        # Определяем человекочитаемое название политики
        policy_human = None
        for pname, pdesc in policy_names:
            if client_policy == pname:
                policy_human = pdesc
                break
        if policy_human is None:
            if client_policy is None:
                policy_human = "Default"
            else:
                policy_human = str(client_policy)
        policy_label = add_info_row(row, "Policy:", policy_human); row += 1


        # Трафик
        traffic_label = Gtk.Label(label="↓ 0 KB/s  ↑ 0 KB/s")
        traffic_label.set_halign(Gtk.Align.END)
        traffic_label.set_hexpand(True)
        active_grid.attach(traffic_label, 1, 0, 1, 1)

        # Активность
        active_label = Gtk.Label(label="")
        active_label.set_halign(Gtk.Align.END)
        active_label.set_hexpand(True)
        active_grid.attach(active_label, 2, 0, 1, 1)

        # Кнопки VPN политик
        toggleGroup = Adw.ToggleGroup()
        toggleGroup.set_margin_top(5)
        toggleGroup.set_margin_start(20)
        toggleGroup.set_margin_end(20)
        toggleGroup.set_margin_bottom(20)
        toggleGroup.set_css_classes(["round"])
        toggleOption = Adw.Toggle(label="Default", name="Default")
        toggleGroup.add(toggleOption)
        for pidx, (policy_name, policy_desc) in enumerate(policy_names):
            toggleOption = Adw.Toggle(label=policy_desc, name=policy_name, tooltip=f"Apply {policy_name} policy")
            toggleGroup.add(toggleOption)
            if client_policy == policy_name:
                toggleGroup.set_active(pidx + 1)
        card.append(toggleGroup)
        def on_policy_change(toggle_group, __, mac=mac, policy_label=policy_label, self=self):
            index = toggle_group.get_active()
            name = toggle_group.get_active_name()
            if index == 0:
                self.apply_policy_to_client(mac, None)
                policy_label.set_text("Default")
            else:
                self.apply_policy_to_client(mac, name)
                for pname, pdesc in policy_names:
                    if name == pname:
                        policy_label.set_text(pdesc)
                        break
                else:
                    policy_label.set_text(name)
        toggleGroup.connect("notify::active", on_policy_change)

        if not online:
            # Если клиент оффлайн, отключаем кнопки политик
            toggleGroup.set_sensitive(False)

        # Для обновления
        card_widgets.append({
            'interface': interface,
            'state_label': state_label,
            'traffic_label': traffic_label,
            'active_label': active_label,
            'usage_history': []
        })
        flowbox.append(card)

    # Если ни одной карточки не показано, выводим плейсхолдер
    if not card_widgets:
        placeholder = Gtk.Label(label="В данный момент вы не в сети роутера, к которому подключились.")
        placeholder.set_margin_top(40)
        placeholder.set_margin_bottom(40)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_valign(Gtk.Align.CENTER)
        self.me_page.append(placeholder)

    def update_traffic():
        prev_stats = {}
        while True:
            for w in card_widgets:
                interface = w['interface']
                rx, tx, state = get_interface_stats(interface)
                prev = prev_stats.get(interface, (rx, tx))
                rx_speed = max(rx - prev[0], 0)
                tx_speed = max(tx - prev[1], 0)
                prev_stats[interface] = (rx, tx)
                w['traffic_label'].set_text(f"↓ {rx_speed/1024:.1f} KB/s  ↑ {tx_speed/1024:.1f} KB/s")
                # --- накопление статистики активности ---
                w['usage_history'].append(rx_speed + tx_speed)
                if len(w['usage_history']) > usage_window:
                    w['usage_history'].pop(0)
                avg_speed = sum(w['usage_history']) / max(len(w['usage_history']), 1)
                if avg_speed > 1024 * 5:  # >5KB/s среднее за usage_window
                    w['active_label'].set_markup('<span foreground="limegreen">Active now</span>')
                elif state == "up":
                    w['active_label'].set_markup('<span foreground="gray">Idle</span>')
                else:
                    w['active_label'].set_markup('')
            time.sleep(1)
    thread = threading.Thread(target=update_traffic, daemon=True)
    thread.start()
