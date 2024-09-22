# utils.py
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

import netifaces

def get_local_mac_addresses():
    mac_addresses = []
    for interface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(interface)
        if netifaces.AF_LINK in addrs:
            for link in addrs[netifaces.AF_LINK]:
                mac = link.get('addr')
                if mac:
                    mac_addresses.append(mac.lower())
    return mac_addresses

def clear_container(container):
    child = container.get_first_child()
    while child:
        next_child = child.get_next_sibling()
        container.remove(child)
        child = next_child

def show_message_dialog(parent, message):
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text=message,
    )
    dialog.connect("response", lambda d, r: d.destroy())
    dialog.show()

def show_confirmation_dialog(parent, message, callback):
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.OK_CANCEL,
        text=message,
    )
    def on_response(dialog, response):
        dialog.destroy()
        callback(response)
    dialog.connect("response", on_response)
    dialog.show()
