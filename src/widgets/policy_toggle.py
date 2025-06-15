from gi.repository import Gtk, Adw
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')


class PolicyToggleWidget(Gtk.Box):
    def __init__(self, policies, current_policy=None, deny=False, router=None, mac=None, policy_names=None, sensitive=True, policy_label=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.policies = policies
        self.current_policy = current_policy
        self.deny = deny
        self.router = router
        self.mac = mac
        self.policy_names = policy_names or []
        self.policy_label = policy_label
        self.toggle_group = Adw.ToggleGroup()
        self.toggle_group.set_css_classes(["round"])
        self.set_sensitive(sensitive)
        self._build()

    def _build(self):
        self.toggle_group.remove_all()
        # Block option
        block_toggle = Adw.Toggle(
            label="Block", name="Block", tooltip="Block access to the Internet")
        self.toggle_group.add(block_toggle)
        # Default option
        default_toggle = Adw.Toggle(label="Default", name="Default")
        self.toggle_group.add(default_toggle)
        # Policy options
        for policy_name, policy_desc in self.policies:
            toggle = Adw.Toggle(label=policy_desc, name=policy_name,
                                tooltip=f"Apply {policy_name} policy")
            self.toggle_group.add(toggle)
        self.append(self.toggle_group)
        self._set_active_from_state()
        self.toggle_group.connect("notify::active", self._on_toggle)

    def _set_active_from_state(self):
        if self.deny:
            self.toggle_group.set_active(0)
        elif self.current_policy is None:
            self.toggle_group.set_active(1)
        else:
            for idx, (policy_name, _) in enumerate(self.policies):
                if self.current_policy == policy_name:
                    self.toggle_group.set_active(idx + 2)
                    break
            else:
                self.toggle_group.set_active(1)

    def _on_toggle(self, toggle_group, _):
        idx = toggle_group.get_active()
        name = toggle_group.get_active_name()

        # Применяем политику
        if self.router and self.mac:
            if idx == 0:
                self.router.set_client_block(self.mac)
                result = "Blocked"
            elif idx == 1:
                self.router.apply_policy_to_client(self.mac, None)
                result = "Default"
            else:
                self.router.apply_policy_to_client(self.mac, name)
                for pname, pdesc in self.policy_names:
                    if name == pname:
                        result = pdesc
                        break
                else:
                    result = name

            if self.policy_label:
                self.policy_label.set_text(result)
        else:
            if self.policy_label:
                self.policy_label.set_text(name)

    def update_state(self, current_policy=None, deny=None, sensitive=None):
        # Disconnect from notify::active to avoid recursive calls
        if self.toggle_group is not None:
            self.toggle_group.disconnect_by_func(self._on_toggle)

        if current_policy is not None:
            self.current_policy = current_policy
        if deny is not None:
            self.deny = deny
        if sensitive is not None:
            self.set_sensitive(sensitive)
        self._set_active_from_state()

        # Reconnect to notify::active
        self.toggle_group.connect("notify::active", self._on_toggle)

    def set_sensitive(self, value):
        self.toggle_group.set_sensitive(value)
        super().set_sensitive(value)
