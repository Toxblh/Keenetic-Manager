import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

class PolicyToggleWidget(Gtk.Box):
    def __init__(self, policies, current_policy=None, deny=False, on_policy_change=None, sensitive=True):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.policies = policies
        self.current_policy = current_policy
        self.deny = deny
        self.on_policy_change = on_policy_change
        self.toggle_group = Adw.ToggleGroup()
        self.set_sensitive(sensitive)
        self._build()

    def _build(self):
        self.toggle_group.remove_all()
        # Block option
        block_toggle = Adw.Toggle(label="Block", name="Block", tooltip="Block access to the Internet")
        self.toggle_group.add(block_toggle)
        # Default option
        default_toggle = Adw.Toggle(label="Default", name="Default")
        self.toggle_group.add(default_toggle)
        # Policy options
        for policy_name, policy_desc in self.policies:
            toggle = Adw.Toggle(label=policy_desc, name=policy_name, tooltip=f"Apply {policy_name} policy")
            self.toggle_group.add(toggle)
        self.append(self.toggle_group)
        self.toggle_group.connect("notify::active", self._on_toggle)
        self._set_active_from_state()

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
        if self.on_policy_change:
            self.on_policy_change(idx, name)

    def update_state(self, current_policy=None, deny=None, sensitive=None):
        if current_policy is not None:
            self.current_policy = current_policy
        if deny is not None:
            self.deny = deny
        if sensitive is not None:
            self.set_sensitive(sensitive)
        self._set_active_from_state()

    def set_sensitive(self, value):
        self.toggle_group.set_sensitive(value)
        super().set_sensitive(value)
