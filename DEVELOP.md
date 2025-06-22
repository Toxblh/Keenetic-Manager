## Разработка

Для разработки подготовленно всё для VSCode

Альтернативно для сборки Flatpak рекомендую пользоваться Gnome Builder

## Сборка и запуск локально (установка в _build/testdir)
* `make local` - подготовит локальный билд
* `make start` - запуск локальной сборки

### Подготовка к релизу

* Проверить версии
    * `make start` - локальная
    * Сборка Flatpak:
        * VSCode - ctrl+alt+b или через ctrl+p `Flatpak:`
        * Или Gnome Builder
* Написать [changelog](data/ru.toxblh.KeeneticManager.metainfo.xml.in)
* Обновить переводы
    * Обновить файлы [po](po/POTFILES.in), проще всего из [meson](src/meson.build) и [gresources](src/keeneticmanager.gresource.xml)
    * `make translate`
    * Обновить переводы в [Poedit](https://flathub.org/apps/net.poedit.Poedit)
    * проверить в `make start-ru`

### Траблашут

Если VSCode Flatpak ругается на доступ к папке в ./.flatpak/... 
Сделай `umount` её

### Flathub обнова
Зайти - https://github.com/flathub/ru.toxblh.KeeneticManager 
Пушнуть PR c обновлением пакета [тут](https://github.com/flathub/ru.toxblh.KeeneticManager/blob/master/ru.toxblh.KeeneticManager.json#L46) перед этим проверить, что все SDK и библиотеки соотносятся с локальной
