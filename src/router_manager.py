from enum import Enum, unique

from .config import load_routers, save_routers, CONFIG_FILE
from .utils import (
    show_message_dialog,
    show_confirmation_dialog,
)
from .dialogs import AddEditRouterDialog
from .keenetic_router import KeeneticRouter
import keyring
from gi.repository import Adw, Gtk, Gio, GLib
import gi
from keyring.errors import PasswordDeleteError
import threading
import ipaddress
import netifaces

from .me import show_me
from .vpn import show_vpn_clients
from .clients import show_online_clients
from .settings import show_settings
from .wg_server import show_vpn_server

from .ui import create_client_row, create_action_row
gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')


@unique
class Pages(str, Enum):
    ME = "me"
    VPN = "vpn"
    CLIENTS = "clients"
    VPN_SERVER = "vpn_server"
    SETTINGS = "settings"


@Gtk.Template(resource_path='/ru/toxblh/KeeneticManager/window.ui')
class RouterManager(Adw.ApplicationWindow):
    __gtype_name__ = 'RouterManagerWindow'

    main_window = Gtk.Template.Child()
    sidebar = Gtk.Template.Child()
    left = Gtk.Template.Child()
    side_panel = Gtk.Template.Child()
    main_box = Gtk.Template.Child()
    right = Gtk.Template.Child()
    main_content = Gtk.Template.Child()
    router_combo = Gtk.Template.Child()
    add_router_button = Gtk.Template.Child()
    edit_router_button = Gtk.Template.Child()
    delete_router_button = Gtk.Template.Child()
    menu_button = Gtk.Template.Child()

    # Список роутеров
    routers = []
    current_router = None
    migration_done = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.keendns_checked = set()

        # Добавляем кнопки в боковую панель
        self.add_side_panel_buttons()

        # Добавляем страницы в основную область контента
        self.add_main_content_pages()

        # Загружаем роутеры из файла при запуске
        self.routers = load_routers()
        self.migrate_router_metadata()

        # Если есть загруженные роутеры, добавляем их в ComboBox
        if self.routers:
            local_networks = self.get_local_networks()
            selected_index = 0
            for router_info in self.routers:
                self.router_combo.append_text(router_info['name'])
            for i, router_info in enumerate(self.routers):
                if self.is_router_in_local_network(router_info, local_networks):
                    selected_index = i
                    break
            self.router_combo.set_active(selected_index)
            selected_router = self.routers[selected_index]
            self.select_router(selected_router)

    def get_local_networks(self):
        networks = []
        for interface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(interface)
            if netifaces.AF_INET not in addrs:
                continue
            for addr_info in addrs[netifaces.AF_INET]:
                ip = addr_info.get('addr')
                netmask = addr_info.get('netmask')
                if not ip or not netmask:
                    continue
                if ip.startswith("127."):
                    continue
                try:
                    networks.append(ipaddress.IPv4Interface(
                        f"{ip}/{netmask}"
                    ).network)
                except ValueError:
                    continue
        return networks

    def is_router_in_local_network(self, router_info, local_networks):
        ip = router_info.get('network_ip')
        if not ip:
            return False
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in local_networks)

    def resolve_router_connection(self, router_info, local_networks, password):
        in_local = self.is_router_in_local_network(
            router_info, local_networks
        )
        keendns_urls = router_info.get('keendns_urls') or []
        network_ip = router_info.get('network_ip')
        name = router_info.get('name')
        login = router_info.get('login')

        def make_router(address):
            print(_("Using address: {address}").format(address=address))
            return KeeneticRouter(
                address,
                login,
                password,
                name,
            )

        if not keendns_urls and not network_ip:
            address = router_info.get('address')
            return make_router(address)

        if in_local and network_ip:
            return make_router(network_ip)

        if network_ip:
            router = make_router(network_ip)
            if router.login():
                return router

        if keendns_urls:
            address = router_info.get('address')
            address_host = address
            if address and address.startswith("http"):
                address_host = address.split("://", 1)[1].split("/", 1)[0]
            if address_host in keendns_urls:
                url = address if address.startswith("http") else f"https://{address_host}"
                return make_router(url)

            def is_hash_domain(domain):
                return domain.endswith(".keenetic.io")

            preferred = next(
                (d for d in keendns_urls if not is_hash_domain(d)),
                keendns_urls[0],
            )
            url = preferred if preferred.startswith("http") else f"https://{preferred}"
            return make_router(url)

        if network_ip:
            return make_router(network_ip)

        address = router_info.get('address')
        return make_router(address)

    def select_router(self, router_info):
        password = keyring.get_password(
            "router_manager", router_info["name"])
        local_networks = self.get_local_networks()

        def resolve():
            router = self.resolve_router_connection(
                router_info, local_networks, password
            )

            def apply():
                if self.router_combo.get_active_text() != router_info["name"]:
                    return False
                self.current_router = router
                self.migrate_router_metadata(for_router=router_info)
                self.update_current_page()
                return False

            GLib.idle_add(apply)

        threading.Thread(target=resolve, daemon=True).start()

    def migrate_router_metadata(self, for_router=None):
        if self.migration_done:
            return

        def needs_migration(router_info):
            return (
                ('network_ip' not in router_info or router_info.get('network_ip') is None)
                or ('keendns_urls' not in router_info or router_info.get('keendns_urls') is None)
                or (router_info.get('keendns_urls') == [] and router_info.get('network_ip') is None)
            )

        def wants_dns_retry(router_info):
            return (
                router_info.get('keendns_urls') == []
                and router_info.get('network_ip') is not None
                and router_info.get('name') not in self.keendns_checked
            )

        pool = [for_router] if for_router else self.routers
        missing = [r for r in pool if needs_migration(r) or wants_dns_retry(r)]

        if not missing:
            if not for_router:
                self.migration_done = True
            return

        def migrate():
            changed = False
            for router_info in missing:
                name = router_info.get('name')
                password = keyring.get_password(
                    "router_manager", router_info['name'])
                if not password:
                    continue
                router = KeeneticRouter(
                    router_info['address'],
                    router_info['login'],
                    password,
                    router_info['name'],
                )
                prev_network_ip = router_info.get('network_ip')
                retry_dns_once = wants_dns_retry(router_info)
                if (
                    'keendns_urls' not in router_info
                    or router_info.get('keendns_urls') is None
                    or (router_info.get('keendns_urls') == [] and prev_network_ip is None)
                    or retry_dns_once
                ):
                    keendns_urls = router.get_keendns_urls()
                    if retry_dns_once and name:
                        self.keendns_checked.add(name)
                    if keendns_urls is not None:
                        router_info['keendns_urls'] = keendns_urls
                        changed = True
                if 'network_ip' not in router_info or router_info.get('network_ip') is None:
                    network_ip = router.get_network_ip()
                    if network_ip is not None:
                        router_info['network_ip'] = network_ip
                        changed = True
            if changed:
                save_routers(self.routers)

            self.migration_done = not any(
                needs_migration(r) for r in self.routers
            )

        threading.Thread(target=migrate, daemon=True).start()

    def update_current_page(self):
        """Обновляет содержимое текущей страницы согласно выбранному роутеру и активной вкладке."""
        current_page = self.main_content.get_visible_child_name()
        if current_page == Pages.ME:
            show_me(self)
        elif current_page == Pages.VPN:
            show_vpn_clients(self)
        elif current_page == Pages.CLIENTS:
            show_online_clients(self)
        elif current_page == Pages.VPN_SERVER:
            show_vpn_server(self)
        elif current_page == Pages.SETTINGS:
            show_settings(self)

    @Gtk.Template.Callback("on_page_select")
    def on_page_select(self, listbox, row):
        if row:
            page = row.get_name()

            self.main_content.set_visible_child_name(page)

            self.update_current_page()

    @Gtk.Template.Callback("on_router_changed")
    def on_router_changed(self, combo):
        # Обработка изменения выбранного роутера
        router_name = combo.get_active_text()
        if router_name:
            # Поиск роутера по имени
            router_info = next(
                (r for r in self.routers if r["name"] == router_name), None)
            if router_info:
                self.select_router(router_info)
                print(_("Selected router: {router_name}").format(
                    router_name=router_info['name']))

        # Обновление происходит после успешного выбора подключения.

    def add_side_panel_buttons(self):
        # Кнопка Я
        self.side_panel.append(create_action_row(
            Pages.ME, _("Me"), "avatar-default-symbolic"))

        # Кнопка VPN
        self.side_panel.append(create_action_row(
            Pages.VPN, _("VPN"), "network-wireless-encrypted-symbolic"))

        # Кнопка Онлайн клиенты
        self.side_panel.append(create_action_row(
            Pages.CLIENTS, _("Clients"), "preferences-system-network-symbolic"))

        # Кнопка Настройки VPN сервера
        # self.side_panel.append(create_action_row(
        #     Pages.VPN_SERVER, _("WireGurad Server")))

        # Кнопка Настройки
        # self.side_panel.append(create_action_row(
        #     Pages.SETTINGS, _("Quick Settings")))

    def add_main_content_pages(self):
        # Страница я
        self.me_page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL)
        self.main_content.add_titled(self.me_page, Pages.ME, _("Me"))

        # Страница VPN
        self.vpn_page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL)
        self.main_content.add_titled(self.vpn_page, Pages.VPN, _("VPN"))

        # Страница клиентов
        self.clients_page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL)
        self.main_content.add_titled(
            self.clients_page, Pages.CLIENTS, _("Online Clients"))

        # Страница настроек VPN сервера
        self.vpn_server_page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL)
        self.main_content.add_titled(
            self.vpn_server_page, Pages.VPN_SERVER, _("Wireguard Server")
        )

        # Страница быстрых настроек
        self.settings_page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL)
        self.main_content.add_titled(
            self.settings_page, Pages.SETTINGS, _("Quick Settings"))

    @Gtk.Template.Callback("on_add_router_clicked")
    def on_add_router_clicked(self, button):
        # Диалог для добавления роутера
        dialog = AddEditRouterDialog(self, _("Add Router"))
        dialog.present()

    @Gtk.Template.Callback("on_edit_router_clicked")
    def on_edit_router_clicked(self, button):
        # Диалог для редактирования роутера
        router_name = self.router_combo.get_active_text()
        if router_name:
            router_info = next(
                (r for r in self.routers if r["name"] == router_name), None)
            if router_info:
                dialog = AddEditRouterDialog(
                    self, _("Edit Router"), router_info)
                dialog.present()
        else:
            show_message_dialog(self, _("Please select a router to edit."))

    @Gtk.Template.Callback("on_delete_router_clicked")
    def on_delete_router_clicked(self, button):
        # Удаление выбранного роутера
        router_name = self.router_combo.get_active_text()
        if router_name:

            def on_dialog_response(response):
                if response == Gtk.ResponseType.OK:
                    self.routers = [
                        r for r in self.routers if r["name"] != router_name]
                    try:
                        keyring.delete_password("router_manager", router_name)
                    except PasswordDeleteError:
                        pass
                    self.router_combo.remove_all()
                    for router in self.routers:
                        self.router_combo.append_text(router["name"])
                    if self.routers:
                        self.router_combo.set_active(0)
                    else:
                        self.current_router = None
                    save_routers(self.routers)

            show_confirmation_dialog(
                self,
                _("Are you sure you want to delete the router '{router_name}'?").format(
                    router_name=router_name),
                on_dialog_response,
            )
        else:
            show_message_dialog(self, _("Please select a router to delete."))

    def on_default_policy_clicked(self, button, client_mac):
        self.apply_default_policy_to_client(client_mac)

    def apply_default_policy_to_client(self, client_mac):
        """Применяет политику по умолчанию к клиенту."""
        if self.current_router.apply_default_policy_to_client(client_mac):
            print(_("Default policy applied to client {client_mac}").format(
                client_mac=client_mac))
            # Обновляем список клиентов после применения политики
            show_vpn_clients(self)
        else:
            print(_("Failed to apply the default policy to client {client_mac}").format(
                client_mac=client_mac))

    def on_policy_button_clicked(self, button, client_mac, policy_name):
        self.apply_policy_to_client(client_mac, policy_name)

    def apply_policy_to_client(self, client_mac, policy_name):
        """Применяет политику к клиенту."""
        if self.current_router.apply_policy_to_client(client_mac, policy_name):
            print(_("Policy {policy_name} applied to client {client_mac}").format(
                policy_name=policy_name, client_mac=client_mac))
            # Обновляем список клиентов после применения политики
            show_vpn_clients(self)
        else:
            print(_("Failed to apply policy {policy_name} to client {client_mac}").format(
                policy_name=policy_name, client_mac=client_mac))

    def on_download_config_clicked(self, button, interface_name, peer_name):
        # Реализуйте функцию для загрузки конфигурации пира
        pass

    def on_show_qr_clicked(self, button, interface_name, peer_name):
        # Реализуйте функцию для отображения QR-кода пира
        pass

    def on_add_peer_clicked(self, button):
        # Реализуйте функцию для добавления нового пира
        pass

    def refresh_router_combo(self, selected_router_name=None):
        """Обновляет список роутеров в ComboBox по self.routers. Если передано selected_router_name, выбирает его."""
        self.router_combo.remove_all()
        for router in self.routers:
            self.router_combo.append_text(router["name"])
        if self.routers:
            if selected_router_name:
                for i, router in enumerate(self.routers):
                    if router["name"] == selected_router_name:
                        self.router_combo.set_active(i)
                        break
                else:
                    self.router_combo.set_active(0)
            else:
                self.router_combo.set_active(0)
        else:
            self.current_router = None
