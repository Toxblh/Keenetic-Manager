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
  'dialogs.py',
  'keenetic_router.py',
  'main.py',
  'router_manager_app.py',
  'router_manager.py',
  'utils.py',
  'config.py',
]

install_data(keeneticmanager_sources, install_dir: moduledir)
