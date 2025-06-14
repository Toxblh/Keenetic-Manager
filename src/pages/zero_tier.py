from gi.repository import Gtk

class ZeroTierPage(Gtk.Box):
    def __init__(self, router_manager, *args, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, *args, **kwargs)
        self.router_manager = router_manager

        # UI элементы
        self.network_id_entry = Gtk.Entry()
        self.network_id_entry.set_placeholder_text("Network ID")
        self.append(self.network_id_entry)

        self.accept_addresses_switch = Gtk.Switch()
        self.accept_addresses_label = Gtk.Label(label="Accept addresses")
        self.accept_addresses_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.accept_addresses_box.append(self.accept_addresses_label)
        self.accept_addresses_box.append(self.accept_addresses_switch)
        self.append(self.accept_addresses_box)

        self.accept_routes_switch = Gtk.Switch()
        self.accept_routes_label = Gtk.Label(label="Accept routes")
        self.accept_routes_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.accept_routes_box.append(self.accept_routes_label)
        self.accept_routes_box.append(self.accept_routes_switch)
        self.append(self.accept_routes_box)

        self.connect_button = Gtk.Button(label="Connect")
        self.append(self.connect_button)

        self.delete_button = Gtk.Button(label="Delete interface")
        self.append(self.delete_button)

        # self.status_label = Gtk.Label(label="Status: ...")
        self.status_textview = Gtk.TextView()
        self.status_textview.set_editable(False)
        self.status_textview.set_cursor_visible(False)
        self.status_textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.status_textview.set_monospace(True)
        self.append(self.status_textview)

        self.peers_label = Gtk.Label(label="Peers:")
        self.append(self.peers_label)

        self.peers_list = Gtk.ListBox()
        self.append(self.peers_list)

        # Сигналы
        self.connect_button.connect("clicked", self.on_connect_clicked)
        self.delete_button.connect("clicked", self.on_delete_clicked)
        self.accept_addresses_switch.connect("notify::active", self.on_accept_addresses_toggled)
        self.accept_routes_switch.connect("notify::active", self.on_accept_routes_toggled)
        self.network_id_entry.connect("activate", self.on_network_id_entered)

        # Инициализация состояния
        self.refresh_status()
        self.refresh_peers()

    def refresh_status(self):
        status = self.get_zerotier_status()
        buffer = self.status_textview.get_buffer()
        buffer.set_text(status)

    def refresh_peers(self):
        # Очистка ListBox в GTK4
        child = self.peers_list.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.peers_list.remove(child)
            child = next_child
        peers = self.get_zerotier_peers()
        if peers:
            for peer in peers:
                self.peers_list.append(Gtk.Label(label=peer))
        else:
            self.peers_list.append(Gtk.Label(label="No peers"))

    def get_zerotier_status(self):
        # Пример: получить статус через router_manager.current_router
        if not self.router_manager.current_router:
            return '{"error": "No router selected"}'
        status = self.router_manager.current_router.zt_get_status()
        import json
        if isinstance(status, dict):
            return json.dumps(status, ensure_ascii=False, indent=2)
        return str(status)

    def set_zerotier_network_id(self, network_id):
        if not self.router_manager.current_router:
            return
        self.router_manager.current_router.zt_set_network_id(network_id)

    def set_zerotier_accept_addresses(self, enabled):
        if not self.router_manager.current_router:
            return
        self.router_manager.current_router.zt_set_accept_addresses(enabled)

    def set_zerotier_accept_routes(self, enabled):
        if not self.router_manager.current_router:
            return
        self.router_manager.current_router.zt_set_accept_routes(enabled)

    def connect_zerotier_interface(self, via=None):
        if not self.router_manager.current_router:
            return
        self.router_manager.current_router.zt_connect_interface(via)

    def get_zerotier_peers(self):
        if not self.router_manager.current_router:
            return []
        return self.router_manager.current_router.zt_get_peers()

    def delete_zerotier_interface(self):
        if not self.router_manager.current_router:
            return
        self.router_manager.current_router.zt_delete_interface()

    def reset_zerotier_identity(self):
        if not self.router_manager.current_router:
            return
        self.router_manager.current_router.zt_reset_identity()

    # Callbacks
    def on_connect_clicked(self, button):
        self.connect_zerotier_interface()
        self.refresh_status()
        self.refresh_peers()

    def on_delete_clicked(self, button):
        self.delete_zerotier_interface()
        self.refresh_status()
        self.refresh_peers()

    def on_accept_addresses_toggled(self, switch, param):
        self.set_zerotier_accept_addresses(switch.get_active())
        self.refresh_status()

    def on_accept_routes_toggled(self, switch, param):
        self.set_zerotier_accept_routes(switch.get_active())
        self.refresh_status()

    def on_network_id_entered(self, entry):
        self.set_zerotier_network_id(entry.get_text())
        self.refresh_status()
