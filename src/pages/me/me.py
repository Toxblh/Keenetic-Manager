from .utils import clear_container
from .policy_toggle import PolicyToggleWidget
from gi.repository import Gtk, Adw, GLib
import gi
import threading
import time
import netifaces

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
        __ = __builtins__._
    except AttributeError:
        def __(s): return s

    # Загружаем UI из GtkBuilder
    builder = Gtk.Builder()
    builder.add_from_resource("/ru/toxblh/KeeneticManager/pages/me/me_page.ui")
    toast_overlay = builder.get_object("toast_overlay")
    flowbox = builder.get_object("flowbox_interfaces")
    placeholder_label = builder.get_object("placeholder_label")
    self.me_page.append(toast_overlay)

    toast = Adw.Toast(title=_('Loading...'))
    toast_overlay.add_toast(toast)

    # flowbox.set_visible(False)
    placeholder_label.set_visible(False)

    def render(clients):
        toast_overlay.dismiss_all()
        flowbox.set_visible(True)

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
        policies = self.current_router.get_policies() if getattr(
            self, 'current_router', None) else {}
        policy_names = [(policy_name, policy_info.get("description", policy_name))
                        for policy_name, policy_info in policies.items()]

        def get_ip(interface):
            addrs = netifaces.ifaddresses(interface)
            if netifaces.AF_INET in addrs:
                return addrs[netifaces.AF_INET][0].get('addr', 'N/A')
            return 'N/A'

        card_widgets = []
        usage_window = 5  # секунд для анализа активности
        for idx, (interface, mac, iface_type) in enumerate(macs):
            client_name = None
            client_found = False
            client_deny = False
            online = False
            client_policy = None
            if clients:
                for c in clients:
                    if c.get('mac', '').lower() == mac:
                        client_name = c.get('name', interface)
                        client_policy = c.get('policy', None)
                        client_deny = c.get('deny', False)
                        state = c.get("data", {}).get("link") == "up" or c.get(
                            "data", {}).get("mws", {}).get("link") == "up"
                        online = True if state else False
                        client_found = True
                        break
                if not client_found:
                    continue
            else:
                client_name = interface
                client_policy = None

            # Карточка через шаблон из UI
            card_builder = Gtk.Builder()
            card_builder.add_from_resource(
                "/ru/toxblh/KeeneticManager/pages/me/me_card.ui")
            card = card_builder.get_object("card")

            header_label = card_builder.get_object("header_label")
            info_grid = card_builder.get_object("info_grid")
            traffic_label = card_builder.get_object("traffic_label")
            active_label = card_builder.get_object("active_label")
            toggle_vpn = card_builder.get_object("toggle_vpn")

            header_label.set_markup(f'<b>{client_name}</b>')

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
            add_info_row(row, "Name:", interface)
            row += 1
            add_info_row(row, "Type:", iface_type)
            row += 1
            state_markup = '<span foreground="green">●</span> Online' if online else '<span foreground="gray">●</span> Offline'
            state_label = add_info_row(
                row, "State:", state_markup, markup=True)
            row += 1
            ip = get_ip(interface)
            add_info_row(row, "IP:", ip)
            row += 1
            add_info_row(row, "MAC:", mac)
            row += 1
            policy_human = None
            for pname, pdesc in policy_names:
                if client_policy == pname:
                    policy_human = pdesc
                    break
            if policy_human is None:
                if client_policy is None:
                    policy_human = "Default"
                elif client_deny:
                    policy_human = "Blocked"
                else:
                    policy_human = str(client_policy)
            policy_label = add_info_row(row, "Policy:", policy_human);
            row += 1

            traffic_label.set_text("↓ 0 KB/s  ↑ 0 KB/s")
            active_label.set_text("")

            policy_widget = PolicyToggleWidget(
                policies=policy_names,
                current_policy=client_policy,
                deny=client_deny,
                router=getattr(self, 'current_router', None),
                mac=mac,
                policy_names=policy_names,
                policy_label=policy_label
            )
            toggle_vpn.append(policy_widget)

            card_widgets.append({
                'interface': interface,
                'state_label': state_label,
                'traffic_label': traffic_label,
                'active_label': active_label,
                'usage_history': []
            })
            flowbox.append(card)

        if not card_widgets:
            placeholder_label.set_visible(True)
        else:
            placeholder_label.set_visible(False)

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

                    def update_labels(w=w, rx_speed=rx_speed, tx_speed=tx_speed, state=state):
                        w['traffic_label'].set_text(
                            f"↓ {rx_speed/1024:.1f} KB/s  ↑ {tx_speed/1024:.1f} KB/s")
                        w['usage_history'].append(rx_speed + tx_speed)
                        if len(w['usage_history']) > usage_window:
                            w['usage_history'].pop(0)
                        avg_speed = sum(w['usage_history']) / \
                            max(len(w['usage_history']), 1)
                        if avg_speed > 1024 * 5:
                            w['active_label'].set_markup(
                                '<span foreground="limegreen">Active now</span>')
                        elif state == "up":
                            w['active_label'].set_markup(
                                '<span foreground="gray">Idle</span>')
                        else:
                            w['active_label'].set_markup('')
                    GLib.idle_add(update_labels)
                time.sleep(1)
        if card_widgets:
            thread = threading.Thread(target=update_traffic, daemon=True)
            thread.start()

    def fetch_clients():
        clients = []
        try:
            clients = self.current_router.get_online_clients()
        except Exception:
            clients = []
        GLib.idle_add(render, clients)

    threading.Thread(target=fetch_clients, daemon=True).start()
