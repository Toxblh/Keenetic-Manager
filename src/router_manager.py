from enum import Enum, unique

from .config import load_routers, save_routers, CONFIG_FILE
from .utils import (
    show_message_dialog,
    show_confirmation_dialog,
    clear_container
)
from .dialogs import AddEditRouterDialog
from .keenetic_router import KeeneticRouter
import keyring
from gi.repository import Adw, Gtk, Gio
import gi

from .me import show_me
from .vpn import show_vpn_clients
from .clients import show_online_clients
from .zero_tier import ZeroTierPage
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
    ZERO_TIER = "zero_tier"


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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Добавляем кнопки в боковую панель
        self.add_side_panel_buttons()

        # Добавляем страницы в основную область контента
        self.add_main_content_pages()

        # Загружаем роутеры из файла при запуске
        self.routers = load_routers()

        # Если есть загруженные роутеры, добавляем их в ComboBox
        if self.routers:
            for router_info in self.routers:
                self.router_combo.append_text(router_info['name'])
            self.router_combo.set_active(0)
            first_router_info = self.routers[0]
            password = keyring.get_password(
                "router_manager", first_router_info['name'])
            self.current_router = KeeneticRouter(
                first_router_info['address'],
                first_router_info['login'],
                password,
                first_router_info['name'],
            )

    @Gtk.Template.Callback("on_page_select")
    def on_page_select(self, listbox, row):
        if row:
            page = row.get_name()

            self.main_content.set_visible_child_name(page)

            if page == Pages.ME:
                show_me(self)
            elif page == Pages.VPN:
                show_vpn_clients(self)
            elif page == Pages.CLIENTS:
                show_online_clients(self)
            elif page == Pages.VPN_SERVER:
                show_vpn_server(self)
            elif page == Pages.ZERO_TIER:
                # Очищаем контейнер страницы (GTK4)
                clear_container(self.zero_tier_page)
                # Добавляем виджет страницы ZeroTier
                self.zero_tier_page.append(ZeroTierPage(self))

    def add_side_panel_buttons(self):
        # Кнопка Я
        self.side_panel.append(create_action_row(
            Pages.ME, _("Me"), "avatar-default-symbolic"))

        # Кнопка VPN
        self.side_panel.append(create_action_row(
            Pages.VPN, _("VPN"), "network-wireless-encrypted-symbolic"))

        # Кнопка Онлайн клиенты
        self.side_panel.append(create_action_row(
            Pages.CLIENTS, _("Online Clients"), "preferences-system-network-symbolic"))

        # Кнопка Настройки VPN сервера
        # self.side_panel.append(create_action_row(
        #     Pages.VPN_SERVER, _("WireGurad Server")))

        # Кнопка Настройки
        self.side_panel.append(create_action_row(
            Pages.ZERO_TIER, _("ZeroTier"), "zerotier"))

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
        self.zero_tier_page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL)
        self.main_content.add_titled(
            self.zero_tier_page, Pages.ZERO_TIER, _("ZeroTier"))

    @Gtk.Template.Callback("on_router_changed")
    def on_router_changed(self, combo):
        # Обработка изменения выбранного роутера
        router_name = combo.get_active_text()
        if router_name:
            # Поиск роутера по имени
            router_info = next(
                (r for r in self.routers if r["name"] == router_name), None)
            if router_info:
                password = keyring.get_password(
                    "router_manager", router_info["name"])
                self.current_router = KeeneticRouter(
                    router_info["address"],
                    router_info["login"],
                    password,
                    router_info["name"],
                )
                print(_("Selected router: {router_name}").format(
                    router_name=router_info['name']))

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
                    keyring.delete_password("router_manager", router_name)
                    self.router_combo.remove_all()
                    for router in self.routers:
                        self.router_combo.append_text(router["name"])
                    if self.routers:
                        self.router_combo.set_active(0)
                    else:
                        self.current_router = None
                    save_routers(CONFIG_FILE, self.routers)

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

    def on_about_action(self, *args):
        """Callback for the app.about action."""
        about = Adw.AboutDialog(
            application_name=_('Keenetic Manager'),
            application_icon='ru.toxblh.KeeneticManager',
            developer_name=_('Anton Palgunov (Toxblh)'),
            version='0.3.0',
            developers=[_('Anton Palgunov (Toxblh)')],
            copyright=_('© 2024-2025 Anton Palgunov (Toxblh)')
        )
        about.add_link("GitHub", "https://github.com/Toxblh/Keenetic-Manager")
        about.add_link("Donate", "https://toxblh.ru/support")
        # Translators: Replace "translator-credits" with your name/username, and optionally an email or URL.
        about.set_translator_credits(_('translator-credits'))
        about.present(self.get_application().get_active_window())
