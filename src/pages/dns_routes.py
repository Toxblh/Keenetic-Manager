"""
DNS Routes page for Keenetic-Manager.
UI for managing domain-based routing rules with v2fly integration.
"""

import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk

from .keenetic_dns import DnsRoutesManager, DnsRouteGroup
from .v2fly import search_lists, fetch_domain_list, get_available_lists, DOMAIN_LIMIT
from .utils import clear_container


def show_dns_routes(self):
    """Main entry point: display DNS Routes page (full load with network requests)."""
    clear_container(self.dns_routes_page)

    if not self.current_router:
        label = Gtk.Label(label=_("Please select a router."))
        label.set_margin_top(24)
        self.dns_routes_page.append(label)
        return

    # Create ToastOverlay — all toasts (loading, progress, errors) appear here
    toast_overlay = Adw.ToastOverlay()
    self._dns_toast_overlay = toast_overlay
    self.dns_routes_page.append(toast_overlay)

    # Show loading toast
    loading_toast = Adw.Toast(title=_("Loading DNS routes..."))
    toast_overlay.add_toast(loading_toast)

    def load():
        try:
            manager = DnsRoutesManager(self.current_router)
            self._dns_manager = manager
            # Pre-warm v2fly cache in background
            threading.Thread(target=lambda: get_available_lists(), daemon=True).start()
            print("[dns_routes] Fetching all data (single POST)...")
            all_data = manager.fetch_all_route_data()
            groups_data = all_data["groups"]
            routes_data = all_data["routes"]
            ifaces_data = all_data["interfaces"]
            print("[dns_routes] Got groups={}, routes={}, ifaces={}".format(
                len(groups_data) if isinstance(groups_data, dict) else "?",
                len(routes_data) if isinstance(routes_data, list) else "?",
                len(ifaces_data) if isinstance(ifaces_data, dict) else "?",
            ))
            self._dns_grouped = manager.get_grouped_by_slug_cached(groups_data, routes_data)
            print("[dns_routes] Fetching interfaces...")
            self._dns_interfaces = manager.get_vpn_interfaces(data=ifaces_data)
            print("[dns_routes] Validating...")
            statuses = manager.validate_and_repair_cached(groups_data, routes_data)
            # Show toast for each repair/update
            for name, status in statuses.items():
                if status.startswith("repaired:"):
                    iface_id = status.split(":", 1)[1].replace("→", "")
                    iface_name = _iface_display(iface_id, self._dns_interfaces if hasattr(self, '_dns_interfaces') else [])
                    GLib.idle_add(lambda n=iface_name: _show_toast(self, _("✓ repaired → {name}").format(name=n)))
                elif status.startswith("cleaned:"):
                    parts = status.split(":")
                    n = parts[1]
                    iface_id = parts[2].replace("→", "")
                    iface_name = _iface_display(iface_id, self._dns_interfaces if hasattr(self, '_dns_interfaces') else [])
                    GLib.idle_add(lambda n=iface_name, c=n: _show_toast(self, _("✓ repaired → {name} ({count})").format(name=n, count=_("cleaned {n} dups").format(n=c))))
                elif status.startswith("updated:"):
                    detail = status.split(":", 1)[1]
                    parts = detail.split("→")
                    old_name = parts[0].strip()
                    new_name = parts[1].strip() if len(parts) > 1 else ""
                    GLib.idle_add(lambda o=old_name, n=new_name: _show_toast(self, _("✓ updated {old} → {new}").format(old=o, new=n)))
            GLib.idle_add(lambda: _render(self, manager, self._dns_grouped, self._dns_interfaces, statuses))
        except Exception as ex:
            msg = str(ex)
            GLib.idle_add(lambda: _show_toast(self, _("Error: {msg}").format(msg=msg)))

    threading.Thread(target=load, daemon=True).start()


def _refresh_dns_routes(self):
    """Light refresh: re-render with current data, no network requests, no loading toast."""
    _save_scroll_position(self)
    manager = getattr(self, '_dns_manager', None)
    grouped = getattr(self, '_dns_grouped', None)
    interfaces = getattr(self, '_dns_interfaces', None)
    if manager and grouped and interfaces:
        _render(self, manager, grouped, interfaces, {})


def _save_scroll_position(self):
    """Save current scroll position before rebuild."""
    overlay = getattr(self, '_dns_toast_overlay', None)
    if overlay:
        child = overlay.get_child()
        if isinstance(child, Gtk.Box):
            # Find the ScrolledWindow inside the content box
            scrolled = child.get_last_child()
            while scrolled and not isinstance(scrolled, Gtk.ScrolledWindow):
                scrolled = scrolled.get_prev_sibling()
            if scrolled:
                self._dns_scroll_value = scrolled.get_vadjustment().get_value()


def _show_toast(self, message: str, timeout: int = 3):
    """Show a toast notification on the DNS routes page."""
    overlay = getattr(self, '_dns_toast_overlay', None)
    if overlay:
        toast = Adw.Toast(title=message, timeout=timeout)
        overlay.add_toast(toast)


def _iface_display(iface_id: str, interfaces: list[dict]) -> str:
    """Get human-readable interface display name."""
    for iface in interfaces:
        if iface["id"] == iface_id:
            desc = iface.get("description", "")
            if desc and desc != iface_id:
                return desc
            return iface_id
    return iface_id


def _render(self, manager: DnsRoutesManager, grouped: dict, interfaces: list[dict], statuses: dict = None):
    """Render the DNS routes UI."""
    overlay = getattr(self, '_dns_toast_overlay', None)
    if overlay:
        overlay.dismiss_all()
    if statuses is None:
        statuses = {}
    print(f"[dns_routes] _render: {len(grouped)} slug(s), {len(interfaces)} interface(s), statuses={statuses}")

    # Build the main content box inside the toast overlay
    content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    if overlay:
        overlay.set_child(content_box)

    # --- Header with sync button ---
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    header.set_margin_start(12)
    header.set_margin_end(12)
    header.set_margin_top(12)
    header.set_margin_bottom(12)

    title = Gtk.Label()
    title.set_markup(f"<b>{_('DNS Routes')}</b>")
    title.set_xalign(0)
    title.set_hexpand(True)
    header.append(title)

    sync_btn = Gtk.Button(label=_("Sync All"))
    sync_btn.set_icon_name("view-refresh-symbolic")
    sync_btn.set_tooltip_text(_("Update all domain lists from v2fly"))
    sync_btn.connect("clicked", lambda _: _sync_all(self, manager, grouped, interfaces))
    header.append(sync_btn)

    add_btn = Gtk.Button(label=_("Add List"))
    add_btn.set_icon_name("list-add-symbolic")
    add_btn.set_tooltip_text(_("Add a new domain list from v2fly"))
    add_btn.connect("clicked", lambda _: _show_add_dialog(self, manager, interfaces))
    header.append(add_btn)

    # Mass replace button
    mass_replace_btn = Gtk.Button(label=_("Replace All"))
    mass_replace_btn.set_icon_name("object-flip-horizontal-symbolic")
    mass_replace_btn.set_tooltip_text(_("Replace one VPN interface with another for all routes"))
    mass_replace_btn.connect("clicked", lambda _: _show_mass_replace_dialog(self, manager, grouped, interfaces))
    header.append(mass_replace_btn)

    content_box.append(header)

    separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
    content_box.append(separator)

    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_vexpand(True)
    content_box.append(scrolled)

    # Restore scroll position after rebuild
    saved_scroll = getattr(self, '_dns_scroll_value', None)
    if saved_scroll is not None:
        def restore_scroll():
            adj = scrolled.get_vadjustment()
            adj.set_value(min(saved_scroll, adj.get_upper() - adj.get_page_size()))
            return False
        GLib.idle_add(restore_scroll)

    if not grouped:
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_halign(Gtk.Align.CENTER)
        empty_box.set_vexpand(True)
        empty_label = Gtk.Label(label=_("No DNS routes configured yet.\nClick 'Add List' to get started."))
        empty_label.set_justify(Gtk.Justification.CENTER)
        empty_box.append(empty_label)
        scrolled.set_child(empty_box)
        return

    list_box = Gtk.ListBox()
    list_box.set_selection_mode(Gtk.SelectionMode.NONE)
    list_box.add_css_class("rich-list")
    list_box.connect("row-activated", lambda lb, row: _on_row_activated(self, manager, row, interfaces))

    for slug, groups in sorted(grouped.items()):
        if not groups:
            continue
        row = _create_group_row(self, manager, slug, groups, interfaces, statuses)
        list_box.append(row)

    scrolled.set_child(list_box)


def _on_row_activated(self, manager, row, interfaces):
    """Handle click on a group row → open edit dialog."""
    slug = getattr(row, 'slug', None)
    groups = getattr(row, 'groups', None)
    if slug and groups:
        _show_edit_dialog(self, manager, slug, groups, interfaces)


def _create_group_row(self, manager, slug, groups, interfaces, statuses=None):
    primary = groups[0]
    batch_count = len(groups)
    total_domains = sum(len(g.domains) for g in groups)
    if statuses is None:
        statuses = {}

    row = Gtk.ListBoxRow()
    row.add_css_class("activatable")

    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    hbox.set_margin_start(12)
    hbox.set_margin_end(12)
    hbox.set_margin_top(8)
    hbox.set_margin_bottom(8)

    name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    name_box.set_hexpand(True)

    name_label = Gtk.Label()
    name_label.set_xalign(0)
    name_text = slug
    # Status tag — parse structured format from API
    group_statuses = [statuses.get(g.name, "ok") for g in groups]
    repaired_s = [s for s in group_statuses if s.startswith("repaired:")]
    cleaned_s = [s for s in group_statuses if s.startswith("cleaned:")]
    updated_s = [s for s in group_statuses if s.startswith("updated:")]
    if repaired_s:
        # repaired:→{iface}
        iface_id = repaired_s[0].split(":", 1)[1].replace("→", "")
        name_text += "  <small><span foreground='orange'>⚠ → {}</span></small>".format(_iface_display(iface_id, interfaces))
    elif cleaned_s:
        # cleaned:{N}:→{iface}
        parts = cleaned_s[0].split(":")
        n = parts[1]
        iface_id = parts[2].replace("→", "")
        name_text += "  <small><span foreground='orange'>⚠ → {} ({})</span></small>".format(
            _iface_display(iface_id, interfaces),
            _("cleaned {n} dups").format(n=n))
    elif updated_s:
        # updated:{old}→{new}
        detail = updated_s[0].split(":", 1)[1]
        parts = detail.split("→")
        old_name = _iface_display(parts[0].strip(), interfaces)
        new_name = _iface_display(parts[1].strip(), interfaces)
        name_text += "  <small><span foreground='orange'>↻ {} → {}</span></small>".format(old_name, new_name)
    elif "error" in group_statuses:
        name_text += "  <small><span foreground='red'>✗ {}</span></small>".format(_("error"))
    elif "no_interface" in group_statuses:
        name_text += "  <small><span foreground='red'>✗ {}</span></small>".format(_("no route"))
    if batch_count > 1:
        name_text += f"  <small><span foreground='gray'>{batch_count} {_('batches')}</span></small>"
    if groups and not groups[0].enabled:
        name_text += "  <small><span foreground='red'>({})</span></small>".format(_("disabled"))
    name_label.set_markup(f"<b>{name_text}</b>")
    name_box.append(name_label)

    subtitle = Gtk.Label()
    subtitle.set_xalign(0)
    date_str = primary.date or "???"
    if len(date_str) == 6:
        date_formatted = f"{date_str[:2]}.{date_str[2:4]}.{date_str[4:]}"
    else:
        date_formatted = date_str
    status_text = f"{total_domains} {_('domains')} · {_('updated')}: {date_formatted}"
    is_managed = DnsRouteGroup.is_managed(primary.description)
    if primary.source == "v2fly":
        status_text += f"  <small><span foreground='#5b9bd5'>v2fly</span></small>"
        if primary.is_outdated:
            status_text += f"  <span foreground='orange'>⚠ {_('update available')}</span>"
    elif is_managed:
        status_text += f"  <small><span foreground='gray'>· {_('manual')}</span></small>"
    else:
        status_text += f"  <small><span foreground='gray'>· {_('manual')}</span></small>"
    subtitle.set_markup(f"<small>{status_text}</small>")
    name_box.append(subtitle)
    hbox.append(name_box)

    iface_label = Gtk.Label()
    iface_label.set_xalign(1.0)
    iface_label.set_halign(Gtk.Align.END)
    iface_text = _iface_display(primary.interface, interfaces) if primary.interface else "—"
    # Add connection status dot (small, inline with text)
    dot_markup = ""
    for iface in interfaces:
        if iface["id"] == primary.interface:
            color = "green" if iface.get("connected") else "gray"
            dot_markup = f'<span foreground="{color}">•</span> '
            break
    iface_label.set_markup(f"<small>{dot_markup}{iface_text}</small>")
    iface_label.set_width_chars(12)
    hbox.append(iface_label)

    # Show edit/delete/toggle for ALL groups (managed or not)
    # Managed groups have extra features (sync, auto-repair)
    is_managed = DnsRouteGroup.is_managed(primary.description)

    edit_btn = Gtk.Button()
    edit_btn.set_icon_name("document-edit-symbolic")
    edit_btn.set_tooltip_text(_("Edit list"))
    edit_btn.set_has_frame(False)
    edit_btn.connect("clicked", lambda _, s=slug, gs=groups: _show_edit_dialog(self, manager, s, gs, interfaces))
    hbox.append(edit_btn)

    switch = Gtk.Switch()
    switch.set_active(primary.enabled)
    switch.set_valign(Gtk.Align.CENTER)
    switch.connect("state-set", lambda sw, state, gs=groups, m=manager: _on_toggle(sw, state, gs, m, self))
    hbox.append(switch)

    del_btn = Gtk.Button()
    del_btn.set_icon_name("user-trash-symbolic")
    del_btn.set_tooltip_text(_("Delete list"))
    del_btn.set_has_frame(False)
    del_btn.add_css_class("destructive-action")
    del_btn.connect("clicked", lambda _, s=slug, gs=groups: _confirm_delete(self, manager, s, gs, interfaces))
    hbox.append(del_btn)

    row.set_child(hbox)
    # Store slug for row-activated handler
    row.slug = slug
    row.groups = groups
    return row


def _on_toggle(switch, state, groups, manager, self):
    for g in groups:
        try:
            manager.toggle_route(g.name, state)
            g.enabled = state
        except Exception as e:
            print(f"[dns_routes] Toggle failed for {g.name}: {e}")
    _refresh_dns_routes(self)


def _confirm_delete(self, manager, slug, groups, interfaces):
    dialog = Adw.MessageDialog(
        transient_for=self,
        heading=_("Delete '{slug}'?").format(slug=slug),
        body=_("This will remove all {n} batch(es) and their routing rules.").format(n=len(groups)),
    )
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("delete", _("Delete"))
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

    def on_response(dialog, response):
        dialog.destroy()
        if response == "delete":
            for g in groups:
                try:
                    manager.delete_group(g.name)
                except Exception as e:
                    print(f"[dns_routes] Delete failed for {g.name}: {e}")
            # Remove from local cache and refresh
            grouped = getattr(self, '_dns_grouped', {})
            grouped.pop(slug, None)
            _refresh_dns_routes(self)

    dialog.connect("response", on_response)
    dialog.present()


def _show_add_dialog(self, manager, interfaces):
    """Show dialog to add a new domain list. Choice between v2fly and manual."""
    print("[dns_routes] Opening add dialog...")

    dialog = Adw.Window(transient_for=self, modal=True)
    dialog.set_title(_("Add Domain List"))
    dialog.set_default_size(480, 480)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    content.set_margin_start(20)
    content.set_margin_end(20)
    content.set_margin_top(20)
    content.set_margin_bottom(20)
    dialog.set_content(content)

    # Mode switch: v2fly or manual
    mode_stack = Gtk.Stack()
    mode_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

    # === V2FLY MODE ===
    v2fly_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

    v2fly_box.append(Gtk.Label(label=_("Search v2fly domain list:"), xalign=0))
    search_entry = Gtk.SearchEntry()
    search_entry.set_placeholder_text(_("Type to search (e.g. youtube, instagram)..."))
    v2fly_box.append(search_entry)

    results_label = Gtk.Label(xalign=0)
    v2fly_box.append(results_label)

    scrolled = Gtk.ScrolledWindow()
    scrolled.set_max_content_height(180)
    scrolled.set_vexpand(True)
    v2fly_box.append(scrolled)

    results_list = Gtk.ListBox()
    results_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
    scrolled.set_child(results_list)

    selected_slug = [None]

    def on_search_changed(entry):
        query = entry.get_text().strip()
        if len(query) < 1:
            results_list.remove_all()
            results_label.set_text("")
            return
        results = search_lists(query)
        results_list.remove_all()
        results_label.set_text(_("{n} results").format(n=len(results)))
        for name in results:
            lbl = Gtk.Label(label=name, xalign=0)
            lbl.set_margin_start(8)
            lbl.set_margin_end(8)
            lbl.set_margin_top(3)
            lbl.set_margin_bottom(3)
            results_list.append(lbl)

    search_entry.connect("changed", on_search_changed)

    def on_row_selected(listbox, row):
        if row:
            child = row.get_child()
            if isinstance(child, Gtk.Label):
                selected_slug[0] = child.get_text()
                search_entry.set_text(selected_slug[0])
                results_list.remove_all()
                results_label.set_text(_("Selected: {name}").format(name=selected_slug[0]))

    results_list.connect("row-activated", on_row_selected)

    mode_stack.add_titled(v2fly_box, "v2fly", _("v2fly"))

    # === MANUAL MODE ===
    manual_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

    manual_box.append(Gtk.Label(label=_("List name:"), xalign=0))
    name_entry = Gtk.Entry()
    name_entry.set_placeholder_text(_("My custom list"))
    manual_box.append(name_entry)

    manual_box.append(Gtk.Label(label=_("Domains (one per line):"), xalign=0))
    domains_text = Gtk.TextView()
    domains_text.set_wrap_mode(Gtk.WrapMode.WORD)
    domains_scroll = Gtk.ScrolledWindow()
    domains_scroll.set_max_content_height(180)
    domains_scroll.set_vexpand(True)
    domains_scroll.set_child(domains_text)
    manual_box.append(domains_scroll)

    mode_stack.add_titled(manual_box, "manual", _("manual"))

    # Mode switcher
    mode_switcher = Gtk.StackSwitcher()
    mode_switcher.set_stack(mode_stack)
    mode_switcher.set_halign(Gtk.Align.CENTER)
    content.append(mode_switcher)
    content.append(mode_stack)

    # Interface (shared)
    content.append(Gtk.Label(label=_("Route through:"), xalign=0, margin_top=8))

    iface_combo = _make_iface_combo(interfaces)
    _prefill_iface_combo(iface_combo, interfaces)
    content.append(iface_combo)

    # Error
    error_label = Gtk.Label(use_markup=True, visible=False)
    content.append(error_label)

    # Buttons
    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_top=12)
    btn_box.set_halign(Gtk.Align.END)
    content.append(btn_box)

    cancel_btn = Gtk.Button(label=_("Cancel"))
    cancel_btn.connect("clicked", lambda b: dialog.close())
    btn_box.append(cancel_btn)

    add_btn = Gtk.Button(label=_("Add"))
    add_btn.add_css_class("suggested-action")

    def on_add_clicked(btn):
        is_v2fly = mode_stack.get_visible_child_name() == "v2fly"
        iface_id = iface_combo.get_active_id()
        if not iface_id:
            error_label.set_markup(f'<span foreground="red">{_("Please select an interface.")}</span>')
            error_label.set_visible(True)
            return

        if is_v2fly:
            slug = selected_slug[0] or search_entry.get_text().strip()
            if not slug:
                error_label.set_markup(f'<span foreground="red">{_("Please select a domain list.")}</span>')
                error_label.set_visible(True)
                return
            dialog.close()
            _do_add_list(self, manager, slug, iface_id, interfaces)
        else:
            name = name_entry.get_text().strip()
            buf = domains_text.get_buffer()
            raw = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            domains = [d.strip() for d in raw.split("\n") if d.strip()]
            if not name:
                error_label.set_markup(f'<span foreground="red">{_("Please enter a list name.")}</span>')
                error_label.set_visible(True)
                return
            if not domains:
                error_label.set_markup(f'<span foreground="red">{_("Please enter at least one domain.")}</span>')
                error_label.set_visible(True)
                return
            dialog.close()
            _do_add_manual(self, manager, name, domains, iface_id)

    add_btn.connect("clicked", on_add_clicked)
    btn_box.append(add_btn)

    # Auto-focus: search on v2fly tab, name on manual tab
    def on_mode_changed(stack, param):
        if stack.get_visible_child_name() == "v2fly":
            search_entry.grab_focus()
        else:
            name_entry.grab_focus()
    mode_stack.connect("notify::visible-child", on_mode_changed)

    dialog.show()
    search_entry.grab_focus()


def _reload_dns_routes(self):
    """Silent reload: re-fetch data, update cache, re-render in-place. No page clear, no loading toast."""
    manager = getattr(self, '_dns_manager', None)
    if not manager:
        show_dns_routes(self)
        return

    def reload():
        try:
            all_data = manager.fetch_all_route_data()
            groups_data = all_data["groups"]
            routes_data = all_data["routes"]
            ifaces_data = all_data["interfaces"]
            self._dns_grouped = manager.get_grouped_by_slug_cached(groups_data, routes_data)
            self._dns_interfaces = manager.get_vpn_interfaces(data=ifaces_data)
            statuses = manager.validate_and_repair_cached(groups_data, routes_data)
            # Show repair/update toasts
            for name, status in statuses.items():
                if status.startswith("repaired:"):
                    iface_id = status.split(":", 1)[1].replace("→", "")
                    iface_name = _iface_display(iface_id, self._dns_interfaces)
                    GLib.idle_add(lambda n=iface_name: _show_toast(self, _("✓ repaired → {name}").format(name=n)))
                elif status.startswith("cleaned:"):
                    parts = status.split(":")
                    n = parts[1]
                    iface_id = parts[2].replace("→", "")
                    iface_name = _iface_display(iface_id, self._dns_interfaces)
                    GLib.idle_add(lambda name=iface_name, c=n: _show_toast(self,
                        _("✓ repaired → {name} ({count})").format(name=name, count=_("cleaned {n} dups").format(n=c))))
                elif status.startswith("updated:"):
                    detail = status.split(":", 1)[1]
                    parts = detail.split("→")
                    old_name = parts[0].strip()
                    new_name = parts[1].strip() if len(parts) > 1 else ""
                    GLib.idle_add(lambda o=old_name, n=new_name: _show_toast(self, _("✓ updated {old} → {new}").format(old=o, new=n)))
            GLib.idle_add(lambda: _render(self, manager, self._dns_grouped, self._dns_interfaces, statuses))
        except Exception as ex:
            msg = str(ex)
            GLib.idle_add(lambda: _show_toast(self, _("Error: {msg}").format(msg=msg)))

    _save_scroll_position(self)
    threading.Thread(target=reload, daemon=True).start()


def _do_add_manual(self, manager, name, domains, interface):
    """Create a manual (non-v2fly) domain list."""
    _show_toast(self, _("Creating '{name}'...").format(name=name), timeout=0)

    def add():
        try:
            today = __import__('datetime').datetime.now().strftime("%d%m%y")
            existing = manager.get_groups()
            used = set()
            for g in existing:
                if g.name.startswith("rt_"):
                    try:
                        used.add(int(g.name[3:]))
                    except ValueError:
                        pass
            idx = 0
            while idx in used:
                idx += 1
            group_name = f"rt_{idx}"
            desc = f"{name}*{interface}*{today}*1"
            commands = [
                f"object-group fqdn {group_name}",
                f"object-group fqdn {group_name} description \"{desc}\"",
            ]
            for d in domains[:300]:
                commands.append(f"object-group fqdn {group_name} include {d}")
            commands.append(f"no dns-proxy route object-group {group_name}")
            commands.append(f"dns-proxy route object-group {group_name} {interface} auto")
            payload = [{"parse": c} for c in commands]
            payload.append({"parse": "system configuration save"})
            for i in range(0, len(payload), 50):
                batch = payload[i:i+50]
                manager._rci_post("rci/", batch)
            GLib.idle_add(lambda: _reload_dns_routes(self))
        except Exception as ex:
            msg = str(ex)
            GLib.idle_add(lambda: _show_toast(self, _("Error: {msg}").format(msg=msg)))

    threading.Thread(target=add, daemon=True).start()


def _do_add_list(self, manager, slug, interface, interfaces):
    _show_toast(self, _("Downloading '{slug}'...").format(slug=slug), timeout=0)

    def add():
        try:
            manager.sync_list(slug, interface)
            GLib.idle_add(lambda: _reload_dns_routes(self))
        except Exception as ex:
            msg = str(ex)
            GLib.idle_add(lambda: _show_toast(self, _("Error: {msg}").format(msg=msg)))

    threading.Thread(target=add, daemon=True).start()


def _show_edit_dialog(self, manager, slug, groups, interfaces):
    """Edit dialog: change VPN interface, and for manual groups also edit domains."""
    primary = groups[0]
    is_managed = DnsRouteGroup.is_managed(primary.description)
    is_v2fly = DnsRouteGroup.is_v2fly(primary.description) if is_managed else False
    show_domains = not is_v2fly  # Show editable domains for manual and external groups

    dialog = Adw.Window(transient_for=self, modal=True)
    dialog.set_title(_("Edit '{slug}'").format(slug=slug))
    dialog.set_default_size(450, 350 if show_domains else 300)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    content.set_margin_start(20)
    content.set_margin_end(20)
    content.set_margin_top(20)
    content.set_margin_bottom(20)
    dialog.set_content(content)

    domains_text = None  # For save handler

    if show_domains:
        content.append(Gtk.Label(label=_("List name:"), xalign=0))
        name_entry = Gtk.Entry()
        name_entry.set_text(slug)
        content.append(name_entry)

        content.append(Gtk.Label(label=_("Domains (one per line):"), xalign=0))
        domains_text = Gtk.TextView()
        domains_text.set_wrap_mode(Gtk.WrapMode.WORD)
        all_domains = []
        for g in groups:
            all_domains.extend(g.domains)
        domains_text.get_buffer().set_text("\n".join(all_domains))
        domains_scroll = Gtk.ScrolledWindow()
        domains_scroll.set_max_content_height(150)
        domains_scroll.set_vexpand(True)
        domains_scroll.set_child(domains_text)
        content.append(domains_scroll)
        content.append(Gtk.Label(label=_("Route through:"), xalign=0, margin_top=6))
    else:
        # v2fly: show domains read-only in a text view
        content.append(Gtk.Label(label=_("Domains (managed automatically):"), xalign=0))
        all_domains = []
        for g in groups:
            all_domains.extend(g.domains)
        domains_text = Gtk.TextView()
        domains_text.set_wrap_mode(Gtk.WrapMode.WORD)
        domains_text.set_editable(False)
        domains_text.set_cursor_visible(False)
        domains_text.get_style_context().add_class("dim-label")
        domains_text.get_buffer().set_text("\n".join(all_domains))
        domains_scroll = Gtk.ScrolledWindow()
        domains_scroll.set_max_content_height(150)
        domains_scroll.set_vexpand(True)
        domains_scroll.set_child(domains_text)
        content.append(domains_scroll)
        content.append(Gtk.Label(label=_("Route through:"), xalign=0, margin_top=6))

    current_iface = groups[0].interface if groups else ""

    iface_combo = _make_iface_combo(interfaces, active_id=current_iface)
    content.append(iface_combo)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_top=12)
    btn_box.set_halign(Gtk.Align.END)
    content.append(btn_box)

    cancel_btn = Gtk.Button(label=_("Cancel"))
    cancel_btn.connect("clicked", lambda b: dialog.close())
    btn_box.append(cancel_btn)

    save_btn = Gtk.Button(label=_("Save"))
    save_btn.add_css_class("suggested-action")

    def on_save(btn):
        new_iface = iface_combo.get_active_id()
        iface_changed = new_iface and new_iface != current_iface
        new_name = name_entry.get_text().strip() if show_domains else None
        name_changed = bool(new_name and new_name != slug)

        # For non-v2fly groups, also check if domains changed
        domains_changed = False
        new_domains = None
        if show_domains:
            buf = domains_text.get_buffer()
            new_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            new_domains = [d.strip() for d in new_text.split("\n") if d.strip()]
            old_domains = []
            for g in groups:
                old_domains.extend(g.domains)
            domains_changed = set(new_domains) != set(old_domains)

        if iface_changed or domains_changed or name_changed:
            for g in groups:
                try:
                    if domains_changed and new_domains:
                        manager.update_group_domains(g.name, new_domains[:300])
                        g.domains = new_domains[:300]
                    if iface_changed:
                        manager.update_group_interface(g.name, new_iface)
                        g.interface = new_iface
                    if name_changed:
                        # Update slug in description and local cache
                        g.slug = new_name
                        g.description = g.encode_description()
                        manager._parse_batch([
                            f"object-group fqdn {g.name} description \"{g.description}\""
                        ])
                except Exception as e:
                    print(f"[dns_routes] Edit failed for {g.name}: {e}")
            # Update grouped cache if name changed
            if name_changed:
                grouped_cache = getattr(self, '_dns_grouped', {})
                if slug in grouped_cache:
                    grouped_cache[new_name] = grouped_cache.pop(slug)
            _refresh_dns_routes(self)
        dialog.close()

    save_btn.connect("clicked", on_save)
    btn_box.append(save_btn)

    dialog.show()
    # Focus on iface combo, not name entry
    GLib.idle_add(lambda: iface_combo.grab_focus())


def _sync_all(self, manager, grouped, interfaces):
    if not grouped:
        return

    # Only sync v2fly lists
    v2fly_items = [(slug, groups) for slug, groups in grouped.items() if groups[0].source == "v2fly"]
    if not v2fly_items:
        _show_toast(self, _("No v2fly lists to sync"))
        return

    total = len(v2fly_items)
    # Collect all existing group names once (avoid re-fetching in sync_list)
    all_existing_names = set()
    for gs in grouped.values():
        for g in gs:
            all_existing_names.add(g.name)

    # Single persistent progress toast that we update
    progress_toast = Adw.Toast(title=_("Syncing (0/{total})...").format(total=total), timeout=0)
    progress_toast.set_priority(Adw.ToastPriority.HIGH)
    overlay = getattr(self, '_dns_toast_overlay', None)
    if overlay:
        overlay.add_toast(progress_toast)

    def sync():
        for i, (slug, groups) in enumerate(v2fly_items):
            iface = groups[0].interface
            if not iface:
                print(f"[dns_routes] Skip {slug}: no interface")
                continue
            # Update progress toast title in-place
            GLib.idle_add(lambda s=slug, n=i+1: progress_toast.set_title(
                _("Syncing ({n}/{total}): {slug}").format(n=n, total=total, slug=s)))
            try:
                # Pass pre-fetched data to avoid extra HTTP requests
                existing_for_slug = grouped.get(slug, [])
                manager.sync_list(slug, iface,
                                  existing_groups_for_slug=existing_for_slug,
                                  all_existing_names=all_existing_names)
            except Exception as e:
                print(f"[dns_routes] Sync failed for {slug}: {e}")
        GLib.idle_add(lambda: _reload_dns_routes(self))

    threading.Thread(target=sync, daemon=True).start()


def _show_mass_replace_dialog(self, manager, grouped, interfaces):
    """Dialog to mass-replace one VPN interface with another across all routes."""
    if not grouped:
        return

    # Collect unique interfaces currently in use
    used_ifaces = set()
    for slug, groups in grouped.items():
        iface = groups[0].interface
        if iface:
            used_ifaces.add(iface)

    if not used_ifaces:
        return

    dialog = Adw.Window(transient_for=self, modal=True)
    dialog.set_title(_("Mass Replace VPN Interface"))
    dialog.set_default_size(420, 280)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    content.set_margin_start(20)
    content.set_margin_end(20)
    content.set_margin_top(20)
    content.set_margin_bottom(20)
    dialog.set_content(content)

    content.append(Gtk.Label(label=_("Replace all routes using:"), xalign=0))

    # Filter: only interfaces actually used in routes, but with status dots
    used_iface_list = [i for i in interfaces if i["id"] in used_ifaces]
    from_combo = _make_iface_combo(used_iface_list, active_id=used_iface_list[0]["id"] if used_iface_list else None)
    content.append(from_combo)

    content.append(Gtk.Label(label=_("With:"), xalign=0))

    to_combo = _make_iface_combo(interfaces)
    _prefill_iface_combo(to_combo, interfaces)
    content.append(to_combo)

    # Preview
    preview_label = Gtk.Label(xalign=0)
    preview_label.set_margin_top(6)

    def update_preview():
        from_iface = from_combo.get_active_id()
        to_iface = to_combo.get_active_id()
        if not from_iface or not to_iface or from_iface == to_iface:
            preview_label.set_text("")
            return
        count = sum(1 for slug, groups in grouped.items() if groups[0].interface == from_iface)
        preview_label.set_markup(f"<small>{_('Will replace in {n} list(s)').format(n=count)}</small>")

    from_combo.connect("changed", lambda c: update_preview())
    to_combo.connect("changed", lambda c: update_preview())
    update_preview()
    content.append(preview_label)

    # Buttons
    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_top=12)
    btn_box.set_halign(Gtk.Align.END)
    content.append(btn_box)

    cancel_btn = Gtk.Button(label=_("Cancel"))
    cancel_btn.connect("clicked", lambda b: dialog.close())
    btn_box.append(cancel_btn)

    replace_btn = Gtk.Button(label=_("Replace"))
    replace_btn.add_css_class("destructive-action")

    def on_replace(btn):
        from_iface = from_combo.get_active_id()
        to_iface = to_combo.get_active_id()
        if not from_iface or not to_iface or from_iface == to_iface:
            return
        dialog.close()

        _show_toast(self, _("Replacing routes..."), timeout=0)

        def do_replace():
            count = 0
            for slug, groups in grouped.items():
                if groups[0].interface == from_iface:
                    for g in groups:
                        try:
                            manager.update_group_interface(g.name, to_iface)
                            count += 1
                        except Exception as e:
                            print(f"[dns_routes] Mass replace failed for {g.name}: {e}")
            print(f"[dns_routes] Mass replace: {count} routes updated")
            GLib.idle_add(lambda: _reload_dns_routes(self))

        threading.Thread(target=do_replace, daemon=True).start()

    replace_btn.connect("clicked", on_replace)
    btn_box.append(replace_btn)

    dialog.show()


# --- Helpers ---

def _make_iface_combo(interfaces, active_id=None):
    """Create a ComboBox with colored ● dots (green=connected, gray=disconnected)."""
    store = Gtk.ListStore(str, str)  # id, markup text
    for iface in interfaces:
        desc = iface.get("description", "")
        display = f"{desc} ({iface['id']})" if desc and desc != iface["id"] else iface["id"]
        if iface["connected"]:
            label = f'<span foreground="green">●</span> {display}'
        else:
            label = f'<span foreground="gray">●</span> {display}'
        store.append([iface["id"], label])
    combo = Gtk.ComboBox(model=store)
    renderer = Gtk.CellRendererText()
    combo.pack_start(renderer, True)
    combo.add_attribute(renderer, "markup", 1)  # Column 1 sets markup=True (non-empty string = truthy)
    combo.add_attribute(renderer, "text", 1)    # Column 1 has the Pango markup text
    combo.set_id_column(0)
    if active_id:
        for i, iface in enumerate(interfaces):
            if iface["id"] == active_id:
                combo.set_active(i)
                break
    return combo


def _prefill_iface_combo(combo, interfaces):
    """Pre-select first connected interface in a markup combo."""
    if interfaces:
        for i, iface in enumerate(interfaces):
            if iface["connected"]:
                combo.set_active(i)
                break
        if combo.get_active() < 0:
            combo.set_active(0)
