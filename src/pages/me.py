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
    title = Gtk.Label(label=_('Me'), css_classes=["title"])
    self.me_page.append(title)

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
            # Попробуем по netifaces
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

    # Получаем политики, если есть роутер
    policies = self.current_router.get_policies() if getattr(self, 'current_router', None) else {}
    policy_names = [(policy_name, policy_info.get("description", policy_name)) for policy_name, policy_info in policies.items()]

    # Сетка для интерфейсов
    grid = Gtk.Grid(column_spacing=10, row_spacing=10)
    grid.set_column_homogeneous(False)
    self.me_page.append(grid)

    # Для обновления трафика
    traffic_labels = {}
    state_labels = {}

    def update_traffic():
        prev_stats = {}
        while True:
            for idx, (interface, mac, iface_type) in enumerate(macs):
                rx, tx, state = get_interface_stats(interface)
                prev = prev_stats.get(interface, (rx, tx))
                rx_speed = max(rx - prev[0], 0)
                tx_speed = max(tx - prev[1], 0)
                prev_stats[interface] = (rx, tx)
                # Обновляем лейблы
                if interface in traffic_labels:
                    traffic_labels[interface].set_text(f"↓ {rx_speed/1024:.1f} KB/s  ↑ {tx_speed/1024:.1f} KB/s")
                if interface in state_labels:
                    color = "green" if state == "up" else "red"
                    state_labels[interface].set_markup(f'<span foreground="{color}">•</span> {state}')
            time.sleep(1)

    for idx, (interface, mac, iface_type) in enumerate(macs):
        # Имя интерфейса, MAC и тип
        name_label = Gtk.Label(label=f"{interface} ({mac}) [{iface_type}]")
        name_label.set_xalign(0)
        grid.attach(name_label, 0, idx, 1, 1)

        # Статус
        state_label = Gtk.Label()
        state_labels[interface] = state_label
        grid.attach(state_label, 1, idx, 1, 1)

        # Трафик
        traffic_label = Gtk.Label(label="↓ 0 KB/s  ↑ 0 KB/s")
        traffic_labels[interface] = traffic_label
        grid.attach(traffic_label, 2, idx, 1, 1)

        # Кнопки VPN политик
        toggleGroup = Adw.ToggleGroup()
        toggleGroup.set_css_classes(["round"])
        toggleOption = Adw.Toggle(label="Default", name="Default")
        toggleGroup.add(toggleOption)
        for pidx, (policy_name, policy_desc) in enumerate(policy_names):
            toggleOption = Adw.Toggle(label=policy_desc, name=policy_name, icon_name="network-vpn-symbolic", tooltip=f"Apply {policy_name} policy")
            toggleGroup.add(toggleOption)
        grid.attach(toggleGroup, 3, idx, 1, 1)
        def on_policy_change(toggle_group, __, mac=mac, self=self):
            index = toggle_group.get_active()
            name = toggle_group.get_active_name()
            if index == 0:
                self.apply_policy_to_client(mac, None)
            else:
                self.apply_policy_to_client(mac, name)
        toggleGroup.connect("notify::active", on_policy_change)

    # Запускаем поток обновления трафика
    thread = threading.Thread(target=update_traffic, daemon=True)
    thread.start()
