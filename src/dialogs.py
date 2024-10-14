# dialogs.py
import gi
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk

import keyring
from .keenetic_router import KeeneticRouter
from .utils import show_message_dialog
from .config import save_routers

class AddEditRouterDialog(Adw.Window):
    def __init__(self, parent, title, router_info=None):
        super().__init__(transient_for=parent, modal=True)
        self.set_title(title)
        self.set_default_size(300, 200)
        self.parent = parent
        self.router_info = router_info

        # Основной контент
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=20, margin_bottom=20, margin_start=20, margin_end=20)
        self.set_content(content_box)

        # Сетка для полей ввода
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        content_box.append(grid)

        name_label = Gtk.Label(label="Название:")
        grid.attach(name_label, 0, 0, 1, 1)
        self.name_entry = Gtk.Entry()
        grid.attach(self.name_entry, 1, 0, 1, 1)

        address_label = Gtk.Label(label="Адрес:")
        grid.attach(address_label, 0, 1, 1, 1)
        self.address_entry = Gtk.Entry()
        grid.attach(self.address_entry, 1, 1, 1, 1)

        login_label = Gtk.Label(label="Логин:")
        grid.attach(login_label, 0, 2, 1, 1)
        self.login_entry = Gtk.Entry()
        grid.attach(self.login_entry, 1, 2, 1, 1)

        password_label = Gtk.Label(label="Пароль:")
        grid.attach(password_label, 0, 3, 1, 1)
        self.password_entry = Gtk.Entry()
        self.password_entry.set_visibility(False)
        grid.attach(self.password_entry, 1, 3, 1, 1)

        # Кнопки
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content_box.append(button_box)

        cancel_button = Gtk.Button(label="Отмена")
        cancel_button.connect("clicked", self.on_cancel_clicked)
        button_box.append(cancel_button)

        ok_button = Gtk.Button(label="Сохранить")
        ok_button.connect("clicked", self.on_ok_clicked)
        button_box.append(ok_button)

        # Если редактируем существующий роутер, заполняем поля
        if self.router_info:
            self.name_entry.set_text(self.router_info['name'])
            self.address_entry.set_text(self.router_info['address'])
            self.login_entry.set_text(self.router_info['login'])
            password = keyring.get_password("router_manager", self.router_info['name'])
            if password:
                self.password_entry.set_text(password)

        self.show()

    def on_cancel_clicked(self, button):
        self.close()

    def on_ok_clicked(self, button):
        name = self.name_entry.get_text()
        address = self.address_entry.get_text()
        login = self.login_entry.get_text()
        password = self.password_entry.get_text()

        if not name or not address or not login or not password:
            show_message_dialog(self.parent, "Пожалуйста, заполните все поля.")
            return

        # Проверяем, не существует ли роутер с таким именем
        existing_router = next((r for r in self.parent.routers if r['name'] == name), None)
        if self.router_info:
            # Редактирование
            if existing_router and existing_router != self.router_info:
                show_message_dialog(self.parent, "Роутер с таким именем уже существует.")
                return
            # Обновляем информацию о роутере
            self.router_info['name'] = name
            self.router_info['address'] = address
            self.router_info['login'] = login
            # Сохраняем пароль в keyring
            keyring.set_password("router_manager", name, password)
        else:
            # Добавление нового роутера
            if existing_router:
                show_message_dialog(self.parent, "Роутер с таким именем уже существует.")
                return
            router_info = {
                'name': name,
                'address': address,
                'login': login
            }
            self.parent.routers.append(router_info)
            self.parent.router_combo.append_text(name)
            # Сохраняем пароль в keyring
            keyring.set_password("router_manager", name, password)
            if len(self.parent.routers) == 1:
                self.parent.router_combo.set_active(0)
                self.parent.current_router = KeeneticRouter(
                    address,
                    login,
                    password,
                    name
                )

        save_routers(self.parent.routers)
        self.close()
