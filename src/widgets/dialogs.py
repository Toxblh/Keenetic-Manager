# dialogs.py
from .config import save_routers
from .keenetic_router import KeeneticRouter
import keyring
import gi
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk, GLib
import threading
import netifaces


class AddEditRouterDialog(Adw.Window):
    def __init__(self, parent, title, router_info=None):
        super().__init__(transient_for=parent, modal=True)
        self.set_title(title)
        self.set_default_size(300, 200)
        self.parent = parent
        self.router_info = router_info

        # Основной контент
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                              margin_top=20, margin_bottom=20, margin_start=20, margin_end=20)
        self.set_content(content_box)

        # Сетка для полей ввода
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        content_box.append(grid)

        name_label = Gtk.Label(label=_("Name:"))
        grid.attach(name_label, 0, 0, 1, 1)
        self.name_entry = Gtk.Entry()
        grid.attach(self.name_entry, 1, 0, 1, 1)

        address_label = Gtk.Label(label=_("Address*:"))
        grid.attach(address_label, 0, 1, 1, 1)
        self.address_entry = Gtk.Entry()
        self.address_entry.set_placeholder_text('192.168.1.1 // https://example.keenetic.link')
        grid.attach(self.address_entry, 1, 1, 1, 1)

        address_label = Gtk.Label()
        address_label.set_markup('<span size="small"><i>' + _("* 192.168.1.1 or https://example.keenetic.link") + "</i></span>")
        grid.attach(address_label, 0, 2, 2, 1)

        login_label = Gtk.Label(label=_("Login:"))
        grid.attach(login_label, 0, 3, 1, 1)
        self.login_entry = Gtk.Entry()
        grid.attach(self.login_entry, 1, 3, 1, 1)

        password_label = Gtk.Label(label=_("Password:"))
        grid.attach(password_label, 0, 4, 1, 1)
        self.password_entry = Gtk.Entry()
        self.password_entry.set_visibility(False)
        grid.attach(self.password_entry, 1, 4, 1, 1)

        self.error_label = Gtk.Label()
        self.error_label.set_margin_top(5)
        self.error_label.set_margin_bottom(5)
        self.error_label.set_margin_start(5)
        self.error_label.set_margin_end(5)
        self.error_label.set_halign(Gtk.Align.START)
        self.error_label.set_valign(Gtk.Align.CENTER)
        self.error_label.set_use_markup(True)
        self.error_label.set_visible(False)
        self.error_label.set_wrap(True)
        self.error_label.set_max_width_chars(28)
        grid.attach(self.error_label, 0, 5, 2, 1)

        # Кнопки
        button_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content_box.append(button_box)

        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", self.on_cancel_clicked)
        button_box.append(cancel_button)

        self.ok_button = Gtk.Button(label=_("Save"))
        self.ok_button.connect("clicked", self.on_ok_clicked)
        button_box.append(self.ok_button)

        # Если редактируем существующий роутер, заполняем поля
        if self.router_info:
            self.name_entry.set_text(self.router_info['name'])
            self.address_entry.set_text(self.router_info['address'])
            self.login_entry.set_text(self.router_info['login'])
            password = keyring.get_password(
                "router_manager", self.router_info['name'])
            if password and isinstance(password, str):
                self.password_entry.set_text(password)

            info_label = Gtk.Label(label=_("Router Info"))
            info_label.get_style_context().add_class("dim-label")
            grid.attach(info_label, 1, 6, 1, 1)

            dns_label = Gtk.Label(label=_("KeenDNS:"))
            grid.attach(dns_label, 0, 7, 1, 1)

            urls = self.router_info['keendns_urls']
            self.dns_entry = Gtk.Label(label="\n".join(urls))
            self.dns_entry.get_style_context().add_class("dim-label")
            grid.attach(self.dns_entry, 1, 7, 1, 1)


            ip_label = Gtk.Label(label=_("Router IP:"))
            grid.attach(ip_label, 0, 8, 1, 1)

            self.ip_entry = Gtk.Label(label=self.router_info['network_ip'])
            self.ip_entry.get_style_context().add_class("dim-label")
            grid.attach(self.ip_entry, 1, 8, 1, 1)

        else:
            try:
                gws = netifaces.gateways()
                default_gw = gws.get('default', {}).get(netifaces.AF_INET)

                if default_gw:
                    gw = default_gw[0]
                    self.address_entry.set_text(gw)
                    self.login_entry.set_text("admin")
            except Exception:
                pass

        self.show()

    def on_cancel_clicked(self, button):
        self.close()

    def show_error(self, message):
        self.error_label.set_markup(f'<span foreground="red">{message}</span>')
        self.error_label.set_visible(True)
        self.ok_button.set_sensitive(True)

    def clear_error(self):
        self.error_label.set_visible(False)
        self.error_label.set_text("")

    def on_ok_clicked(self, button):
        self.ok_button.set_sensitive(False)
        self.clear_error()
        name = self.name_entry.get_text()
        address = self.address_entry.get_text()
        login = self.login_entry.get_text()
        password = self.password_entry.get_text()

        if address.endswith("/"):
            address = address[:-1]
            self.address_entry.set_text(address)

        if not name or not address or not login or not password:
            self.show_error(_("Please fill in all fields."))
            return

        # Проверяем, не существует ли роутер с таким именем
        existing_router = next(
            (r for r in self.parent.routers if r['name'] == name), None)
        if existing_router and (not self.router_info or existing_router != self.router_info):
            self.show_error(_("A router with this name already exists."))
            return

        # Проверка подключения в отдельном потоке
        def check_connection():
            try:
                router = KeeneticRouter(address, login, password, name)
                clients = router.get_online_clients()
                # Проверяем успешность авторизации и подключения
                if clients is None or clients == []:
                    def show_auth_err():
                        self.show_error(_("Please check your address, login and password."))
                    GLib.idle_add(show_auth_err)
                    return
                network_ip = router.get_network_ip()
                keendns_urls = router.get_keendns_urls()
                # Если всё хорошо, сохраняем (в главном потоке)
                def save():
                    if self.router_info:
                        self.router_info['name'] = name
                        self.router_info['address'] = address
                        self.router_info['login'] = login
                        if network_ip is not None:
                            self.router_info['network_ip'] = network_ip
                        if keendns_urls is not None:
                            self.router_info['keendns_urls'] = keendns_urls
                        keyring.set_password("router_manager", name, password)
                    else:
                        router_info = {
                            'name': name,
                            'address': address,
                            'login': login,
                        }
                        if network_ip is not None:
                            router_info['network_ip'] = network_ip
                        if keendns_urls is not None:
                            router_info['keendns_urls'] = keendns_urls
                        self.parent.routers.append(router_info)
                        self.parent.router_combo.append_text(name)
                        keyring.set_password("router_manager", name, password)
                        if len(self.parent.routers) == 1:
                            self.parent.router_combo.set_active(0)
                            self.parent.current_router = router
                    save_routers(self.parent.routers)
                    self.parent.refresh_router_combo(selected_router_name=name)
                    self.close()
                GLib.idle_add(save)
            except Exception as e:
                def show_err():
                    self.show_error(str(e))
                GLib.idle_add(show_err)
        threading.Thread(target=check_connection, daemon=True).start()
