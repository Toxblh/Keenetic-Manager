## Разработка

Для сборки рекомендую пользоваться Gnome Builder
Для разработки подготовленно всё для vscode

### Подготовка к релизу

* Проверить версии
    * `make run`
* Написать [changelog](data/ru.toxblh.KeeneticManager.metainfo.xml.in)
* Обновить переводы
    * `make translate`
    * Обновить в poetry
    * проверить в `make russian`

Если VSCode Flatpak ругается на доступ к папке в ./.flatpak/... 
Сделай `umount` её

### Flatpak
Зайти - https://github.com/flathub/ru.toxblh.KeeneticManager 
Пушнуть PR c обновлением пакета [тут](https://github.com/flathub/ru.toxblh.KeeneticManager/blob/master/ru.toxblh.KeeneticManager.json#L46)
