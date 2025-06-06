# ui.py
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

def get_signal_icon_name(rssi):
    """Возвращает имя иконки по уровню сигнала RSSI."""
    try:
        rssi = int(rssi)
    except (TypeError, ValueError):
        # ethernet
        return "network-wired-symbolic"

    if rssi >= -50:
        return "network-cellular-signal-excellent-symbolic"  # сильный сигнал
    elif rssi >= -60:
        return "network-cellular-signal-good-symbolic"
    elif rssi >= -70:
        return "network-cellular-signal-ok-symbolic"
    else:
        return "network-cellular-signal-weak-symbolic"

def create_client_row(client, grid, idx):
    name = client.get("name")
    ip = client.get("ip")
    mac = client.get("mac", "N/A")
    ap = client.get("data", {}).get("ap") or client.get("data", {}).get("mws", {}).get("ap")
    rssi = client.get("data", {}).get("rssi") or client.get("data", {}).get("mws", {}).get("rssi", "N/A")
    connection = "Wi-Fi" if ap else "Ethernet"

    # Определяем диапазон Wi-Fi по имени точки доступа
    if ap == "WifiMaster0/AccessPoint0":
        wifi_Ghz = "2.4 GHz"
    elif ap == "WifiMaster1/AccessPoint0":
        wifi_Ghz = "5 GHz"
    else:
        wifi_Ghz = ""

    txrate = client.get("data", {}).get("txrate") or client.get("data", {}).get("mws", {}).get("txrate")
    encryption = client.get("data", {}).get("security") or client.get("data", {}).get("mws", {}).get("security", "N/A")
    support = client.get("data", {}).get("_11") or client.get("data", {}).get("mws", {}).get("_11", "")
    txss = client.get("data", {}).get("txss") or client.get("data", {}).get("mws", {}).get("txss", "N/A")
    ht = client.get("data", {}).get("ht") or client.get("data", {}).get("mws", {}).get("ht", "N/A")
    speed = client.get("data", {}).get("speed")
    port = client.get("data", {}).get("port")
    mode = client.get("data", {}).get("mode") or client.get("data", {}).get("mws", {}).get("mode", "N/A")
    priority = client.get("data", {}).get("priority", "N/A")


    # 1. Имя и через кого (вертикально)
    name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    name_label = Gtk.Label(label=name, xalign=0)
    name_label.set_halign(Gtk.Align.START)
    name_box.append(name_label)

    # router_label = Gtk.Label(label=f"Роутер: {client.get('router', 'Unknown')}", xalign=0)
    # name_box.append(router_label)

    grid.attach(name_box, 0, idx, 1, 1)

    # 2. IP и MAC (вертикально)
    net_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    ip_label = Gtk.Label(label=ip, xalign=0)
    ip_label.set_halign(Gtk.Align.START)
    net_box.append(ip_label)

    mac_label = Gtk.Label(label=mac, xalign=0)
    mac_label.set_halign(Gtk.Align.START)
    mac_label.get_style_context().add_class("dim-label")
    net_box.append(mac_label)

    grid.attach(net_box, 1, idx, 1, 1)

    # 3. Сеть и диапазон (вертикально)
    net_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    net_label = Gtk.Label(label="Домашняя сеть", xalign=0) # ToDo: Здесь нужно указать имя сети реальное
    net_label.set_halign(Gtk.Align.START)
    net_box.append(net_label)
    if ap:
        wifi_label = Gtk.Label(label=f"Wi-Fi {wifi_Ghz}", xalign=0)
    else:
        wifi_label = Gtk.Label(label="По проводу", xalign=0)
    wifi_label.set_halign(Gtk.Align.START)
    wifi_label.get_style_context().add_class("dim-label")
    net_box.append(wifi_label)
    grid.attach(net_box, 2, idx, 1, 1)

    # 4. Иконка сигнала
    icon_name = get_signal_icon_name(rssi)
    signal_icon = Gtk.Image.new_from_icon_name(icon_name)
    grid.attach(signal_icon, 3, idx, 1, 1)

    # 5. Скорость и доп.инфо (вертикально)
    speed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    if ap:
        speed_label = Gtk.Label(label=f"{txrate} Мбит/с {encryption}", xalign=0)
    else:
        speed_label = Gtk.Label(label=f"{speed} Мбит/с", xalign=0)
    speed_label.set_halign(Gtk.Align.START)
    speed_box.append(speed_label)

    if isinstance(support, list):
        support_str = "/" + "/".join(str(x) for x in support)
    else:
        support_str = str(support)
    if ap:
        info_label = Gtk.Label(label=f"{mode}{support_str} {txss}х{txss} {ht} МГц", xalign=0)
    else:
        info_label = Gtk.Label(label=f"Порт {port}", xalign=0)
    info_label.set_halign(Gtk.Align.START)
    info_label.get_style_context().add_class("dim-label")
    speed_box.append(info_label)
    grid.attach(speed_box, 4, idx, 1, 1)

    # 6. Кнопка с числом (например, 6)
    circle_button = Gtk.Button(label=str(priority))
    circle_button.set_sensitive(False)
    circle_button.set_size_request(40, 32)
    circle_button.get_style_context().add_class("suggested-action")
    grid.attach(circle_button, 5, idx, 1, 1)
