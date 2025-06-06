import gi

from .ui import create_client_row
gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')
from gi.repository import Adw, Gtk, Gio

import keyring
from .keenetic_router import KeeneticRouter
from .dialogs import AddEditRouterDialog
from .utils import (
    get_local_mac_addresses,
    clear_container,
    show_message_dialog,
    show_confirmation_dialog,
)
from .config import load_routers, save_routers, CONFIG_FILE


class RouterManager(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title(_("Router Manager"))
        self.set_default_size(800, 600)

        # Список роутеров
        self.routers = []
        self.current_router = None

        # Основная компоновка
        self.main_window = Adw.NavigationSplitView()
        self.main_window.set_max_sidebar_width(220)
        self.main_window.set_min_sidebar_width(220)
        self.set_content(self.main_window)

        # Левая часть
        about_item = Gio.MenuItem.new(_('About'), "app.about")

        menu = Gio.Menu()
        menu.append_item(about_item)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_menu_model(menu)

        header_bar = Adw.HeaderBar()
        header_bar.pack_end(menu_button)

        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self.on_about_action)
        self.get_application().add_action(action)

        self.left = Adw.ToolbarView()
        self.left.add_top_bar(header_bar)

        # Боковая панель
        self.side_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.left.set_content(self.side_panel)

        self.sidebar = Adw.NavigationPage()
        self.sidebar.set_title(_("Router Manager"))
        self.sidebar.set_child(self.left)

        # Основная область контента
        self.main_content = Adw.ViewStack()

        # Правая часть
        self.right = Adw.ToolbarView()
        self.right.set_content(self.main_content)

        self.main_box = Adw.NavigationPage()
        self.main_box.set_child(self.right)

        # Заголовок окна
        self.create_header_bar()

        # Разделение на боковую панель и основной контент
        self.main_window.set_sidebar(self.sidebar)
        self.main_window.set_content(self.main_box)

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
            password = keyring.get_password("router_manager", first_router_info['name'])
            self.current_router = KeeneticRouter(
                first_router_info['address'],
                first_router_info['login'],
                password,
                first_router_info['name'],
            )

    def create_header_bar(self):
        header_bar = Adw.HeaderBar()
        self.right.add_top_bar(header_bar)

        # Выпадающий список роутеров
        self.router_combo = Gtk.ComboBoxText()
        self.router_combo.connect("changed", self.on_router_changed)
        header_bar.pack_start(self.router_combo)

        # Кнопка добавления роутера
        add_router_button = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_router_button.set_tooltip_text(_("Add Router"))
        add_router_button.connect("clicked", self.on_add_router_clicked)
        header_bar.pack_end(add_router_button)

        # Кнопка редактирования роутера
        edit_router_button = Gtk.Button.new_from_icon_name("document-edit-symbolic")
        edit_router_button.set_tooltip_text(_("Edit Router"))
        edit_router_button.connect("clicked", self.on_edit_router_clicked)
        header_bar.pack_end(edit_router_button)

        # Кнопка удаления роутера
        delete_router_button = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        delete_router_button.set_tooltip_text(_("Delete Router"))
        delete_router_button.connect("clicked", self.on_delete_router_clicked)
        header_bar.pack_end(delete_router_button)

    def add_side_panel_buttons(self):
        # Кнопка VPN
        vpn_button = Gtk.Button(label=_("VPN"))
        vpn_button.connect("clicked", self.on_vpn_button_clicked)
        vpn_button.set_margin_start(10)
        vpn_button.set_margin_end(10)
        self.side_panel.append(vpn_button)

        # Кнопка Онлайн клиенты
        clients_button = Gtk.Button(label=_("Online Clients"))
        clients_button.connect("clicked", self.on_clients_button_clicked)
        clients_button.set_margin_start(10)
        clients_button.set_margin_end(10)
        self.side_panel.append(clients_button)

        # Кнопка Быстрые настройки
        # settings_button = Gtk.Button(label="Быстрые настройки")
        # settings_button.connect("clicked", self.on_settings_button_clicked)
        # self.side_panel.append(settings_button)

        # # Кнопка Настройки VPN сервера
        # vpn_server_button = Gtk.Button(label="Настройки VPN сервера")
        # vpn_server_button.connect("clicked", self.on_vpn_server_button_clicked)
        # self.side_panel.append(vpn_server_button)

    def add_main_content_pages(self):
        # Страница VPN
        self.vpn_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.main_content.add_titled(self.vpn_page, "vpn", _("VPN"))

        # Страница клиентов
        self.clients_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.main_content.add_titled(self.clients_page, "clients", _("Online Clients"))

        # Страница быстрых настроек
        self.settings_page = Gtk.Label(label="Страница быстрых настроек")
        self.main_content.add_titled(self.settings_page, "settings", _("Quick Settings"))

        # Страница настроек VPN сервера
        self.vpn_server_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.main_content.add_titled(
            self.vpn_server_page, "vpn_server", _("VPN Server Settings")
        )

    def on_router_changed(self, combo):
        # Обработка изменения выбранного роутера
        router_name = combo.get_active_text()
        if router_name:
            # Поиск роутера по имени
            router_info = next((r for r in self.routers if r["name"] == router_name), None)
            if router_info:
                password = keyring.get_password("router_manager", router_info["name"])
                self.current_router = KeeneticRouter(
                    router_info["address"],
                    router_info["login"],
                    password,
                    router_info["name"],
                )
                print(_("Selected router: {router_name}").format(router_name=router_info['name']))

    def on_add_router_clicked(self, button):
        # Диалог для добавления роутера
        dialog = AddEditRouterDialog(self, _("Add Router"))
        dialog.present()

    def on_edit_router_clicked(self, button):
        # Диалог для редактирования роутера
        router_name = self.router_combo.get_active_text()
        if router_name:
            router_info = next((r for r in self.routers if r["name"] == router_name), None)
            if router_info:
                dialog = AddEditRouterDialog(self, _("Edit Router"), router_info)
                dialog.present()
        else:
            show_message_dialog(self, _("Please select a router to edit."))

    def on_delete_router_clicked(self, button):
        # Удаление выбранного роутера
        router_name = self.router_combo.get_active_text()
        if router_name:

            def on_dialog_response(response):
                if response == Gtk.ResponseType.OK:
                    self.routers = [r for r in self.routers if r["name"] != router_name]
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
                _("Are you sure you want to delete the router '{router_name}'?").format(router_name=router_name),
                on_dialog_response,
            )
        else:
            show_message_dialog(self, _("Please select a router to delete."))

    def on_vpn_button_clicked(self, button):
        self.main_content.set_visible_child_name("vpn")
        self.show_vpn_clients()

    def on_clients_button_clicked(self, button):
        self.main_content.set_visible_child_name("clients")
        self.show_online_clients()

    def on_settings_button_clicked(self, button):
        self.main_content.set_visible_child_name("settings")

    def on_vpn_server_button_clicked(self, button):
        self.main_content.set_visible_child_name("vpn_server")
        self.show_vpn_server_settings()

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

        # Сортируем клиентов, поднимая текущий компьютер наверх
        def client_sort_key(client):
            if client["mac"] in local_macs:
                return 0
            else:
                return 1

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

            # Отображаем имя клиента и его MAC-адрес
            # name_text = f"{client_name} ({client_mac})"
            name_text = f"{client_name}"
            if is_current_pc:
                name_text += _(" [This is you]")
            if is_deny:
                name_text += " (x)"
            name_label = Gtk.Label(label=name_text)
            name_label.set_xalign(0)
            grid.attach(name_label, 0, row_idx, 1, 1)


            toggleGroup = Adw.ToggleGroup()
            toggleGroup.set_css_classes(["round"])

            toggleOption = Adw.Toggle(label="Default", name="Default")
            toggleGroup.add(toggleOption)


            # Кнопка "По умолчанию"
            default_button = Gtk.Button(label=_("Default"))
            if not client_policy:
                default_button.get_style_context().add_class("suggested-action")
            default_button.connect("clicked", self.on_default_policy_clicked, client_mac)
            grid.attach(default_button, 1, row_idx, 1, 1)

            # Добавляем кнопки политик
            for idx, (policy_name, policy_desc) in enumerate(policy_names):
                policy_button = Gtk.Button(label=policy_desc)
                if client_policy == policy_name:
                    policy_button.get_style_context().add_class("suggested-action")
                policy_button.connect(
                    "clicked", self.on_policy_button_clicked, client_mac, policy_name
                )
                grid.attach(policy_button, idx + 2, row_idx, 1, 1)

                toggleOption = Adw.Toggle(label=policy_desc, name=policy_name, icon_name="network-vpn-symbolic", tooltip="Apply {policy_name} policy".format(policy_name=policy_name))
                toggleGroup.add(toggleOption)

            grid.attach(toggleGroup, idx + 3, row_idx, 1, 1)

    def on_default_policy_clicked(self, button, client_mac):
        if self.current_router.apply_default_policy_to_client(client_mac):
            print(_("Default policy applied to client {client_mac}").format(client_mac=client_mac))
            # Обновляем список клиентов после применения политики
            self.show_vpn_clients()
        else:
            print(_("Failed to apply the default policy to client {client_mac}").format(client_mac=client_mac))

    def on_policy_button_clicked(self, button, client_mac, policy_name):
        if self.current_router.apply_policy_to_client(client_mac, policy_name):
            print(_("Policy {policy_name} applied to client {client_mac}").format(policy_name=policy_name, client_mac=client_mac))
            # Обновляем список клиентов после применения политики
            self.show_vpn_clients()
        else:
            print(_("Failed to apply policy {policy_name} to client {client_mac}").format(policy_name=policy_name, client_mac=client_mac))

    def show_online_clients(self):
        # Очистка предыдущего контента
        clear_container(self.clients_page)

        if not self.current_router:
            label = Gtk.Label(label=_("Please select a router."))
            self.clients_page.append(label)
            return

        # Получение данных о онлайн клиентах
        online_clients = self.current_router.get_online_clients()

        if not online_clients:
            label = Gtk.Label(label=_("Failed to retrieve the list of clients."))
            self.clients_page.append(label)
            return

        # Создаем ScrolledWindow
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_min_content_height(400)
        scrolled_window.set_margin_start(10)
        scrolled_window.set_margin_end(10)
        scrolled_window.set_vexpand(True)
        self.clients_page.append(scrolled_window)

        # Отображение клиентов в списке
        listbox = Gtk.ListBox()
        scrolled_window.set_child(listbox)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_column_homogeneous(False)
        grid.set_hexpand(True)
        grid.set_vexpand(False)
        listbox.append(grid)

        for idx, (client) in enumerate(online_clients):
            online =  True if client.get("data", {}).get("link") == "up" else False

            if online:
                create_client_row(client, grid, idx)


    def show_vpn_server_settings(self):
        # Очистка предыдущего контента
        clear_container(self.vpn_server_page)

        if not self.current_router:
            label = Gtk.Label(label=_("Please select a router."))
            self.vpn_server_page.append(label)
            return

        # Получение настроек WireGuard сервера
        wg_data = self.current_router.get_wireguard_peers()

        if not wg_data:
            label = Gtk.Label(label=_("Failed to retrieve VPN server settings."))
            self.vpn_server_page.append(label)
            return

        # Отображение списка пиров
        for interface_name, interface_info in wg_data.items():
            if "peer" in interface_info:
                for peer_name, peer_info in interface_info["peer"].items():
                    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                    self.vpn_server_page.append(hbox)

                    peer_label = Gtk.Label(label=_("Peer: {peer_name}").format(peer_name=peer_name), xalign=0)
                    hbox.append(peer_label)

                    # Кнопка для загрузки конфигурации
                    config_button = Gtk.Button(label=_("Download Configuration"))
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
            version='0.1.0',
            developers=[_('Anton Palgunov (Toxblh)')],
            copyright=_('© 2024 Anton Palgunov (Toxblh)')
        )
        about.add_link("GitHub", "https://github.com/Toxblh/Keenetic-Manager")
        about.add_link("Donate", "https://toxblh.ru/support")
        # Translators: Replace "translator-credits" with your name/username, and optionally an email or URL.
        about.set_translator_credits(_('translator-credits'))
        about.present(self.get_application().get_active_window())
