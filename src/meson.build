pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'keeneticmanager'
gnome = import('gnome')

gnome.compile_resources('keeneticmanager',
  'keeneticmanager.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

python = import('python')

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'keeneticmanager.in',
  output: 'keeneticmanager',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'r-xr-xr-x'
)

keeneticmanager_sources = [
  '__init__.py',
  'api/keenetic_router.py',
  'config.py',
  'helpers/utils.py',
  'main.py',
  'pages/clients.py',
  'pages/me/me.py',
  'pages/settings.py',
  'pages/vpn.py',
  'pages/wg_server.py',
  'pages/zero_tier.py',
  'router_manager.py',
  'router_manager_app.py',
  'widgets/dialogs.py',
  'widgets/policy_toggle.py',
  'widgets/ui.py',
]

install_data(keeneticmanager_sources, install_dir: moduledir)
