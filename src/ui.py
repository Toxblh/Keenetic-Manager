# ui.py
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Adw

def create_action_row(name, title):
        row = Adw.ActionRow()
        row.set_title(title)
        row.set_name(name)
        return row

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

def get_client_data(client):
    data = client.get("data", {})
    mws = data.get("mws", {})
    def pick(*keys, default=None):
        for k in keys:
            v = data.get(k)
            if v is not None:
                return v
            v = mws.get(k)
            if v is not None:
                return v
        return default
    ap = pick("ap")
    rssi = pick("rssi", default="N/A")
    txrate = pick("txrate")
    encryption = pick("security", default="N/A")
    support = pick("_11", default="")
    txss = pick("txss", default="N/A")
    ht = pick("ht", default="N/A")
    speed = data.get("speed")
    port = data.get("port")
    mode = pick("mode", default="N/A")
    priority = data.get("priority", "N/A")
    return ap, rssi, txrate, encryption, support, txss, ht, speed, port, mode, priority

def get_wifi_ghz(ap):
    if ap == "WifiMaster0/AccessPoint0":
        return "2.4 GHz"
    elif ap == "WifiMaster1/AccessPoint0":
        return "5 GHz"
    return ""

def create_client_row(client):
    name = client.get("name")
    ip = client.get("ip")
    mac = client.get("mac", "N/A")
    ap, rssi, txrate, encryption, support, txss, ht, speed, port, mode, priority = get_client_data(client)
    connection = "Wi-Fi" if ap else "Ethernet"
    wifi_Ghz = get_wifi_ghz(ap)
    COL_WIDTH, ICON_WIDTH, BTN_WIDTH = 160, 36, 48

    def make_label(label, xalign, halign, hexpand=False, dim=False):
        l = Gtk.Label(label=label, xalign=xalign)
        l.set_halign(halign)
        if hexpand:
            l.set_hexpand(True)
        if dim:
            l.get_style_context().add_class("dim-label")
        return l

    row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row_box.set_margin_top(4)
    row_box.set_margin_bottom(4)
    row_box.set_margin_start(4)
    row_box.set_margin_end(4)

    name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    name_label = make_label(name, 0, Gtk.Align.START, hexpand=True)
    name_box.set_hexpand(True)
    name_box.set_halign(Gtk.Align.FILL)
    name_box.append(name_label)
    row_box.append(name_box)

    net_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    ip_label = make_label(ip, 1, Gtk.Align.END)
    mac_label = make_label(mac, 1, Gtk.Align.END, dim=True)
    net_box.append(ip_label)
    net_box.append(mac_label)
    net_box.set_size_request(COL_WIDTH, -1)
    net_box.set_halign(Gtk.Align.END)
    row_box.append(net_box)

    net_box2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    net_label = make_label("Домашняя сеть", 1, Gtk.Align.END)
    wifi_label = make_label(f"Wi-Fi {wifi_Ghz}" if ap else "По проводу", 1, Gtk.Align.END, dim=True)
    net_box2.append(net_label)
    net_box2.append(wifi_label)
    net_box2.set_size_request(COL_WIDTH, -1)
    net_box2.set_halign(Gtk.Align.END)
    row_box.append(net_box2)

    icon_name = get_signal_icon_name(rssi)
    signal_icon = Gtk.Image.new_from_icon_name(icon_name)
    signal_icon.set_halign(Gtk.Align.END)
    icon_box = Gtk.Box()
    icon_box.set_size_request(ICON_WIDTH, -1)
    icon_box.set_halign(Gtk.Align.END)
    icon_box.append(signal_icon)
    row_box.append(icon_box)

    speed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    speed_label = make_label(f"{txrate} Мбит/с {encryption}" if ap else f"{speed} Мбит/с", 1, Gtk.Align.END)
    if isinstance(support, list):
        support_str = "/" + "/".join(str(x) for x in support)
    else:
        support_str = str(support)
    info_label = make_label(
        f"{mode}{support_str} {txss}х{txss} {ht} МГц" if ap else f"Порт {port}",
        1, Gtk.Align.END, dim=True)
    speed_box.append(speed_label)
    speed_box.append(info_label)
    speed_box.set_size_request(COL_WIDTH, -1)
    speed_box.set_halign(Gtk.Align.END)
    row_box.append(speed_box)

    circle_button = Gtk.Button(label=str(priority))
    circle_button.set_sensitive(False)
    circle_button.set_size_request(BTN_WIDTH, 32)
    circle_button.get_style_context().add_class("suggested-action")
    btn_box = Gtk.Box()
    btn_box.set_size_request(BTN_WIDTH, -1)
    btn_box.set_halign(Gtk.Align.END)
    btn_box.append(circle_button)
    row_box.append(btn_box)

    widgets = {
        'name_label': name_label,
        'ip_label': ip_label,
        'mac_label': mac_label,
        'net_label': net_label,
        'wifi_label': wifi_label,
        'signal_icon': signal_icon,
        'speed_label': speed_label,
        'info_label': info_label,
        'circle_button': circle_button,
    }

    def update_data(new_client):
        name = new_client.get("name")
        ip = new_client.get("ip")
        mac = new_client.get("mac", "N/A")
        ap, rssi, txrate, encryption, support, txss, ht, speed, port, mode, priority = get_client_data(new_client)
        wifi_Ghz = get_wifi_ghz(ap)
        widgets['name_label'].set_text(name)
        widgets['ip_label'].set_text(ip)
        widgets['mac_label'].set_text(mac)
        widgets['net_label'].set_text("Домашняя сеть")
        widgets['wifi_label'].set_text(f"Wi-Fi {wifi_Ghz}" if ap else "По проводу")
        icon_name = get_signal_icon_name(rssi)
        widgets['signal_icon'].set_from_icon_name(icon_name)
        widgets['speed_label'].set_text(f"{txrate} Мбит/с {encryption}" if ap else f"{speed} Мбит/с")
        if isinstance(support, list):
            support_str = "/" + "/".join(str(x) for x in support)
        else:
            support_str = str(support)
        widgets['info_label'].set_text(
            f"{mode}{support_str} {txss}х{txss} {ht} МГц" if ap else f"Порт {port}")
        widgets['circle_button'].set_label(str(priority))

    listbox_row = Gtk.ListBoxRow()
    listbox_row.set_child(row_box)
    listbox_row.update_data = update_data
    return listbox_row
