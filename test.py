import gi
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, Gtk, GLib

# Базовый компонент
class Component:
    def __init__(self, **props):
        self.props = props
        self.state = {}
        self._widget = None

    def set_state(self, **kwargs):
        self.state.update(kwargs)
        GLib.idle_add(self._render)

    def _render(self):
        parent = self._widget.get_parent()
        self._widget = self.render()
        if parent:
            # Для Adw.ToolbarView и подобных используем set_content
            if hasattr(parent, "set_content"):
                parent.set_content(self._widget)
            # Для Gtk.Box и других контейнеров используем append
            elif hasattr(parent, "append"):
                parent.append(self._widget)
            # Для старых контейнеров Gtk3 можно добавить add
            elif hasattr(parent, "add"):
                parent.add(self._widget)
            # show_all только если есть такой метод
            if hasattr(parent, "show_all"):
                parent.show_all()
        return False

    def render(self):
        raise NotImplementedError

    def widget(self):
        if self._widget is None:
            self._widget = self.render()
        return self._widget

# Функции-компоненты для виджетов
def Box(props, *children):
    box = Gtk.Box(orientation=props.get("orientation", Gtk.Orientation.VERTICAL))
    for child in children:
        box.append(child)
    return box

def Label(props):
    return Gtk.Label(label=props["label"])

def Button(props):
    btn = Gtk.Button(label=props["label"])
    if "on_click" in props:
        btn.connect("clicked", lambda b: props["on_click"]())
    return btn

# Пример компонента-счетчика
class Counter(Component):
    def __init__(self, **props):
        super().__init__(**props)
        self.state = {"count": 0}

    def render(self):
        return Box({},
            Label({"label": f"Count: {self.state['count']}"}),
            Button({"label": "Increment", "on_click": lambda: self.set_state(count=self.state["count"] + 1)})
        )

# Использование
def main():
    app = Adw.Application()

    def on_activate(app):
        win = Adw.ApplicationWindow(application=app)
        win.set_title("Keenetic Manager")
        win.set_default_size(1200, 600)
        view = Adw.ToolbarView()
        counter = Counter()
        view.set_content(counter.widget())
        win.set_content(view)
        win.present()

    app.connect("activate", on_activate)
    app.run()

if __name__ == "__main__":
    main()
