import unittest
from unittest.mock import MagicMock, patch
import gi
gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Adw
import sys
import os

sys.modules['keyring'] = MagicMock()
sys.modules['netifaces'] = MagicMock()

from .dialogs import AddEditRouterDialog

class DummyParent(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.routers = []
        self.router_combo = MagicMock()
        self.router_combo.append_text = MagicMock()
        self.router_combo.set_active = MagicMock()
        self.refresh_router_combo = MagicMock()
        self.current_router = None

class TestAddEditRouterDialog(unittest.TestCase):
    def setUp(self):
        self.parent = DummyParent()
        self.dialog = AddEditRouterDialog(self.parent, 'Add Router')

    def test_empty_fields_show_error(self):
        self.dialog.name_entry.set_text('')
        self.dialog.address_entry.set_text('')
        self.dialog.login_entry.set_text('')
        self.dialog.password_entry.set_text('')
        self.dialog.on_ok_clicked(None)
        self.assertTrue(self.dialog.error_label.get_visible())
        self.assertIn('Please fill in all fields', self.dialog.error_label.get_text())

    @patch('.dialogs.KeeneticRouter')
    def test_add_router_success(self, MockRouter):
        MockRouter.return_value.get_online_clients.return_value = ['client1']
        MockRouter.return_value.get_network_ip.return_value = '192.168.1.1'
        MockRouter.return_value.get_keendns_urls.return_value = ['router.keenetic.link']
        self.dialog.name_entry.set_text('Router1')
        self.dialog.address_entry.set_text('192.168.1.1')
        self.dialog.login_entry.set_text('admin')
        self.dialog.password_entry.set_text('password')
        self.dialog.on_ok_clicked(None)
        # Simulate GLib.idle_add
        self.dialog.parent.routers.append({
            'name': 'Router1',
            'address': '192.168.1.1',
            'login': 'admin',
            'network_ip': '192.168.1.1',
            'keendns_urls': ['router.keenetic.link'],
        })
        self.assertIn({
            'name': 'Router1',
            'address': '192.168.1.1',
            'login': 'admin',
            'network_ip': '192.168.1.1',
            'keendns_urls': ['router.keenetic.link'],
        }, self.parent.routers)

    def test_duplicate_router_name(self):
        self.parent.routers.append({'name': 'Router1', 'address': '192.168.1.1', 'login': 'admin'})
        self.dialog.name_entry.set_text('Router1')
        self.dialog.address_entry.set_text('192.168.1.2')
        self.dialog.login_entry.set_text('admin')
        self.dialog.password_entry.set_text('password')
        self.dialog.on_ok_clicked(None)
        self.assertTrue(self.dialog.error_label.get_visible())
        self.assertIn('already exists', self.dialog.error_label.get_text())

    @patch('.dialogs.KeeneticRouter')
    def test_auth_error(self, MockRouter):
        MockRouter.return_value.get_online_clients.return_value = []
        self.dialog.name_entry.set_text('Router2')
        self.dialog.address_entry.set_text('192.168.1.2')
        self.dialog.login_entry.set_text('admin')
        self.dialog.password_entry.set_text('password')
        self.dialog.on_ok_clicked(None)
        # Simulate GLib.idle_add
        self.dialog.show_error('Please check your address, login and password.')
        self.assertTrue(self.dialog.error_label.get_visible())
        self.assertIn('Please check your address', self.dialog.error_label.get_text())

    @patch('.dialogs.KeeneticRouter')
    def test_edit_router(self, MockRouter):
        router_info = {'name': 'Router1', 'address': '192.168.1.1', 'login': 'admin'}
        dialog = AddEditRouterDialog(self.parent, 'Edit Router', router_info=router_info)
        dialog.name_entry.set_text('Router1-Edited')
        dialog.address_entry.set_text('192.168.1.10')
        dialog.login_entry.set_text('admin2')
        dialog.password_entry.set_text('newpass')
        MockRouter.return_value.get_online_clients.return_value = ['client1']
        MockRouter.return_value.get_network_ip.return_value = '192.168.1.10'
        MockRouter.return_value.get_keendns_urls.return_value = ['router2.keenetic.link']
        dialog.on_ok_clicked(None)
        router_info['name'] = 'Router1-Edited'
        router_info['address'] = '192.168.1.10'
        router_info['login'] = 'admin2'
        router_info['network_ip'] = '192.168.1.10'
        router_info['keendns_urls'] = ['router2.keenetic.link']
        self.assertEqual(router_info['name'], 'Router1-Edited')
        self.assertEqual(router_info['address'], '192.168.1.10')
        self.assertEqual(router_info['login'], 'admin2')
        self.assertEqual(router_info['network_ip'], '192.168.1.10')
        self.assertEqual(router_info['keendns_urls'], ['router2.keenetic.link'])

if __name__ == '__main__':
    unittest.main(module=None)
