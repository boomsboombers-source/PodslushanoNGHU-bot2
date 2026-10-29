# services/plugin_registry.py
"""
Реестр подключённых плагинов.

Плагины при импорте регистрируют свои метаданные через register().
Админ-панель читает get_all() для отображения меню «🔌 Плагины».

Структура метаданных (PLUGIN_INFO в плагине):
    {
        "name": "Конкурс аватарок ТГК",          # отображаемое имя
        "description": "Конкурс на аватарку",     # краткое описание
        "commands": [                              # список (команда, описание)
            ("!начать_конкурс", "запустить (админ)"),
            ("!конкурс", "отправить фото (все)"),
        ],
    }
"""

import logging

# Внутренний список. Заполняется при загрузке плагинов.
_PLUGINS: list[dict] = []


def register(info: dict) -> None:
    """Регистрирует плагин. Вызывается из load_plugins() в bot.py."""
    if not isinstance(info, dict):
        logging.warning(f"plugin_registry: пропущен не-dict: {info!r}")
        return

    name = info.get("name") or "Без названия"

    # Защита от дублей (если плагин импортируют дважды)
    if any(p.get("name") == name for p in _PLUGINS):
        logging.warning(f"plugin_registry: дубль плагина '{name}' — пропущен")
        return

    _PLUGINS.append(info)
    logging.info(f"plugin_registry: зарегистрирован '{name}'")


def get_all() -> list[dict]:
    """Возвращает копию списка (чтобы хендлер не мог случайно изменить реестр)."""
    return list(_PLUGINS)


def is_empty() -> bool:
    """True, если ни одного плагина не зарегистрировано."""
    return len(_PLUGINS) == 0