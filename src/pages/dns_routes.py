"""
DNS Routes page for Keenetic-Manager.
UI for managing domain-based routing rules with v2fly integration.
"""

import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from .keenetic_dns import DnsRoutesManager, DnsRouteGroup
from .v2fly import search_lists, get_available_lists
from .utils import clear_container


def show_dns_routes(self):
    """Main entry point: display DNS Routes page (full load with network requests)."""
    clear_container(self.dns_routes_page)
    # Drop the previous router's data and invalidate any load still in flight
    self._dns_load_gen = getattr(self, '_dns_load_gen', 0) + 1
    self._dns_manager = None
    self._dns_grouped = None
    self._dns_interfaces = None
    self._dns_router_url = self.current_router.base_url if self.current_router else None

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

    # Pre-warm v2fly cache in background
    threading.Thread(target=lambda: get_available_lists(), daemon=True).start()

    router = self.current_router
    _start_load(self, lambda: DnsRoutesManager(router))


def _start_load(self, get_manager, messages=None):
    """Fetch router state in a worker thread and render it.
    The result is dropped if another load or a router switch happened meanwhile.
    `messages` are shown as toasts once the result is on screen."""
    self._dns_load_gen = getattr(self, '_dns_load_gen', 0) + 1
    gen = self._dns_load_gen
    messages = list(messages or [])

    def work():
        try:
            manager = get_manager()
            data, statuses = manager.load_validated()
            grouped = manager.get_grouped_by_slug_cached(data["groups"], data["routes"])
            interfaces = manager.get_vpn_interfaces(data=data["interfaces"])
        except Exception as ex:
            GLib.idle_add(fail, str(ex))
            return
        GLib.idle_add(done, manager, grouped, interfaces, statuses)

    def done(manager, grouped, interfaces, statuses):
        if gen != self._dns_load_gen:
            return False
        self._dns_manager = manager
        self._dns_grouped = grouped
        self._dns_interfaces = interfaces
        overlay = getattr(self, '_dns_toast_overlay', None)
        if overlay:
            overlay.dismiss_all()  # the loading toast and anything about the old state
        _render(self, manager, grouped, interfaces, statuses)
        _show_status_toasts(self, statuses, interfaces)
        for msg in messages:
            _show_toast(self, msg, timeout=8)
        return False

    def fail(msg):
        if gen != self._dns_load_gen:
            return False
        overlay = getattr(self, '_dns_toast_overlay', None)
        if overlay:
            overlay.dismiss_all()
            if getattr(self, '_dns_grouped', None) is None:
                # Nothing to show: say so instead of leaving an empty page
                _render_load_error(self, overlay, msg)
        for m in messages:
            _show_toast(self, m, timeout=8)
        _show_toast(self, _("Error: {msg}").format(msg=msg), timeout=8)
        return False

    threading.Thread(target=work, daemon=True).start()


def _render_load_error(self, overlay, msg):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_valign(Gtk.Align.CENTER)
    box.set_halign(Gtk.Align.CENTER)
    box.set_vexpand(True)
    label = Gtk.Label(label=_("Could not load DNS routes from the router.\n{msg}").format(msg=msg))
    label.set_justify(Gtk.Justification.CENTER)
    label.set_wrap(True)
    box.append(label)
    retry_btn = Gtk.Button(label=_("Retry"))
    retry_btn.set_halign(Gtk.Align.CENTER)
    retry_btn.connect("clicked", lambda _b: show_dns_routes(self))
    box.append(retry_btn)
    overlay.set_child(box)


def _show_status_toasts(self, statuses, interfaces):
    """Show a toast for each repair/update the load performed."""
    for name, status in statuses.items():
        if status.startswith("repaired:"):
            iface_id = status.split(":", 1)[1].replace("→", "")
            _show_toast(self, _("✓ repaired → {name}").format(name=_iface_display(iface_id, interfaces)))
        elif status.startswith("cleaned:"):
            parts = status.split(":")
            iface_id = parts[2].replace("→", "")
            _show_toast(self, _("✓ repaired → {name} ({count})").format(
                name=_iface_display(iface_id, interfaces),
                count=_("cleaned {n} dups").format(n=parts[1])))
        elif status.startswith("updated:"):
            parts = status.split(":", 1)[1].split("→")
            _show_toast(self, _("✓ updated {old} → {new}").format(
                old=parts[0].strip(), new=parts[1].strip() if len(parts) > 1 else ""))


def _refresh_dns_routes(self):
    """Light refresh: re-render with current data, no network requests, no loading toast."""
    _save_scroll_position(self)
    manager = getattr(self, '_dns_manager', None)
    grouped = getattr(self, '_dns_grouped', None)
    interfaces = getattr(self, '_dns_interfaces', None)
    if manager is not None and grouped is not None and interfaces is not None:
        _render(self, manager, grouped, interfaces, {})


def _reload_dns_routes(self, messages=None):
    """Silent reload: re-fetch data, update cache, re-render in-place. No page clear, no loading toast."""
    manager = getattr(self, '_dns_manager', None)
    if manager:
        _save_scroll_position(self)
        _start_load(self, lambda: manager, messages)
        return
    router = self.current_router
    if router and getattr(self, '_dns_toast_overlay', None) and getattr(self, '_dns_router_url', None) == router.base_url:
        # The first load of this page is still in flight: replace it, keeping the messages
        _start_load(self, lambda: DnsRoutesManager(router), messages)
    else:
        show_dns_routes(self)


def _run_op(self, manager, fn, progress=None):
    """Run a router-changing operation off the main thread.
    One operation at a time. Whatever happens, the page is then reloaded from the
    router, so it shows what the router holds rather than what was intended, and a
    failure is shown as a toast. `fn` receives a callback that updates the progress
    toast. Returns False if another operation is still running."""
    if getattr(self, '_dns_busy', False):
        _show_toast(self, _("Another operation is still running."))
        return False
    self._dns_busy = True

    toast = None
    overlay = getattr(self, '_dns_toast_overlay', None)
    if progress and overlay:
        toast = Adw.Toast(title=progress, timeout=0)
        toast.set_priority(Adw.ToastPriority.HIGH)
        overlay.add_toast(toast)

    def set_progress(title):
        if toast:
            GLib.idle_add(lambda: toast.set_title(title) and False)

    def work():
        error = None
        try:
            fn(set_progress)
        except Exception as ex:
            print(f"[dns_routes] Operation failed: {ex}")
            error = str(ex)
        GLib.idle_add(finish, error, manager.pop_warnings())

    def finish(error, warnings):
        self._dns_busy = False
        if toast:
            toast.dismiss()
        # Re-entering the page builds a new manager for the same router, so compare
        # routers, not manager objects
        if manager.router.base_url != getattr(self, '_dns_router_url', None):
            return False  # the page now shows another router
        messages = []
        if warnings:
            messages.append(_("Router rejected {n} address(es): {first}").format(
                n=len(warnings), first=warnings[0]))
        if error:
            messages.append(_("Error: {msg}").format(msg=error))
        _reload_dns_routes(self, messages)
        return False

    threading.Thread(target=work, daemon=True).start()
    return True


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
    name_text = GLib.markup_escape_text(slug)
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
    names = [g.name for g in groups]
    if not _run_op(self, manager, lambda progress: manager.toggle_list(names, state)):
        # Refused (another operation is running): put the switch back
        _refresh_dns_routes(self)
        return True
    return False


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
            names = [g.name for g in groups]
            _run_op(self, manager, lambda progress: manager.delete_list(names))

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
        if selected_slug[0] and query != selected_slug[0]:
            selected_slug[0] = None  # the user typed something else after selecting
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
            if _do_add_list(self, manager, slug, iface_id, interfaces):
                dialog.close()
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
            if _do_add_manual(self, manager, name, domains, iface_id):
                dialog.close()

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


def _do_add_manual(self, manager, name, domains, interface):
    """Create a manual (non-v2fly) domain list."""
    return _run_op(self, manager,
                   lambda progress: manager.apply_list("manual", name, domains, interface, create=True),
                   progress=_("Creating '{name}'...").format(name=name))


def _do_add_list(self, manager, slug, interface, interfaces):
    return _run_op(self, manager,
                   lambda progress: manager.sync_list(slug, interface, create=True),
                   progress=_("Downloading '{slug}'...").format(slug=slug))


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
        name_entry.set_text(primary.slug)
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

    iface_combo = _make_iface_combo(interfaces, active_id=current_iface, keep_unknown=True)
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
        iface_changed = bool(new_iface and new_iface != current_iface)
        new_name = name_entry.get_text().strip() if show_domains else None
        name_changed = bool(new_name and new_name != primary.slug)

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
            if not new_domains:
                _show_toast(self, _("Please enter at least one domain."))
                return

        if not (iface_changed or domains_changed or name_changed):
            dialog.close()
            return

        names = [g.name for g in groups]
        if is_v2fly:
            # Domains come from v2fly: only the interface can change
            op = lambda progress: manager.set_list_interface(names, new_iface)
        elif is_managed:
            # Manual list: re-split across groups as needed
            op = lambda progress: manager.apply_list(
                "manual", primary.slug, new_domains, new_iface or current_iface,
                new_slug=new_name if name_changed else None)
        else:
            # Group created outside the app: edit it in place
            op = lambda progress: manager.edit_group(
                primary.name,
                domains=new_domains if domains_changed else None,
                interface=new_iface if iface_changed else None,
                description=new_name if name_changed else None)
        if _run_op(self, manager, op):
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
    v2fly_items = [groups for groups in grouped.values() if groups[0].source == "v2fly"]
    if not v2fly_items:
        _show_toast(self, _("No v2fly lists to sync"))
        return

    total = len(v2fly_items)

    def sync(progress):
        failed = []
        for i, groups in enumerate(v2fly_items):
            slug = groups[0].slug
            iface = groups[0].interface
            if not iface:
                failed.append(_("{slug}: no interface").format(slug=slug))
                continue
            progress(_("Syncing ({n}/{total}): {slug}").format(n=i + 1, total=total, slug=slug))
            try:
                # sync_list reads the router itself, so it never works from this page's snapshot
                manager.sync_list(slug, iface)
            except Exception as e:
                print(f"[dns_routes] Sync failed for {slug}: {e}")
                failed.append(f"{slug}: {e}")
        if failed:
            raise RuntimeError(_("Sync failed for {lists}").format(lists="; ".join(failed)))

    _run_op(self, manager, sync, progress=_("Syncing (0/{total})...").format(total=total))


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

    from_combo.connect("notify::selected", lambda *a: update_preview())
    to_combo.connect("notify::selected", lambda *a: update_preview())
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
        names = [g.name for groups in grouped.values()
                 if groups[0].interface == from_iface for g in groups]
        if _run_op(self, manager, lambda progress: manager.set_list_interface(names, to_iface),
                   progress=_("Replacing routes...")):
            dialog.close()

    replace_btn.connect("clicked", on_replace)
    btn_box.append(replace_btn)

    dialog.show()


# --- Helpers ---

class _IfaceDropDown(Gtk.DropDown):
    """Interface selector with colored ● dots (green=connected, gray=disconnected).
    A drop-down always has a row selected, so `placeholder` adds a first row that
    stands for "leave as is" (its id is None): an interface that is not in the list
    is then never silently replaced by the first one."""

    def __init__(self, interfaces, placeholder=None):
        labels = []
        ids = []
        if placeholder is not None:
            labels.append(f'<span foreground="gray">{GLib.markup_escape_text(placeholder)}</span>')
            ids.append(None)
        for iface in interfaces:
            desc = iface.get("description", "")
            display = f"{desc} ({iface['id']})" if desc and desc != iface["id"] else iface["id"]
            color = "green" if iface["connected"] else "gray"
            labels.append(f'<span foreground="{color}">●</span> {GLib.markup_escape_text(display)}')
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda f, item: item.set_child(Gtk.Label(xalign=0, use_markup=True)))
        factory.connect("bind", lambda f, item: item.get_child().set_markup(item.get_item().get_string()))
        super().__init__(model=Gtk.StringList.new(labels), factory=factory)
        self._ids = ids + [iface["id"] for iface in interfaces]

    def get_active(self) -> int:
        selected = self.get_selected()
        return selected if selected < len(self._ids) else -1

    def get_active_id(self):
        selected = self.get_active()
        return self._ids[selected] if selected >= 0 else None

    def set_active(self, index: int):
        self.set_selected(index)


def _make_iface_combo(interfaces, active_id=None, keep_unknown=False):
    """Create an interface selector, with `active_id` selected if it is in the list.
    With `keep_unknown`, an `active_id` that is not in the list (or is empty) gets a
    row of its own that means "do not change"."""
    known = [iface["id"] for iface in interfaces]
    if keep_unknown and active_id not in known:
        return _IfaceDropDown(interfaces, placeholder=active_id or "—")
    combo = _IfaceDropDown(interfaces)
    if active_id in known:
        combo.set_active(known.index(active_id))
    return combo


def _prefill_iface_combo(combo, interfaces):
    """Pre-select first connected interface."""
    if interfaces:
        for i, iface in enumerate(interfaces):
            if iface["connected"]:
                combo.set_active(i)
                break
        if combo.get_active() < 0:
            combo.set_active(0)
