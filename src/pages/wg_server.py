from .utils import clear_container
from gi.repository import Gtk, Adw
import gi
gi.require_version('Gtk', '4.0')


def show_vpn_server(self):
    # Очистка предыдущего контента
    clear_container(self.vpn_server_page)

    if not self.current_router:
        label = Gtk.Label(label=_("Please select a router."))
        self.vpn_server_page.append(label)
        return

    # Получение настроек WireGuard сервера
    wg_data = self.current_router.get_wireguard_peers()

    if not wg_data:
        label = Gtk.Label(
            label=_("Failed to retrieve VPN server settings."))
        self.vpn_server_page.append(label)
        return

    # Отображение списка пиров
    for interface_name, interface_info in wg_data.items():
        if "peer" in interface_info:
            for peer_name, peer_info in interface_info["peer"].items():
                hbox = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                self.vpn_server_page.append(hbox)

                peer_label = Gtk.Label(label=_("Peer: {peer_name}").format(
                    peer_name=peer_name), xalign=0)
                hbox.append(peer_label)

                # Кнопка для загрузки конфигурации
                config_button = Gtk.Button(
                    label=_("Download Configuration"))
                config_button.connect(
                    "clicked", self.on_download_config_clicked, interface_name, peer_name
                )
                hbox.append(config_button)

                # Кнопка для отображения QR-кода
                qr_button = Gtk.Button(label=_("Show QR Code"))
                qr_button.connect(
                    "clicked", self.on_show_qr_clicked, interface_name, peer_name
                )
                hbox.append(qr_button)

    # Кнопка для добавления нового пира
    add_peer_button = Gtk.Button(label=_("Add Peer"))
    add_peer_button.connect("clicked", self.on_add_peer_clicked)
    self.vpn_server_page.append(add_peer_button)
