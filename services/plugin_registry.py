# services/plugin_registry.py
"""
Реестр подключённых плагинов.
Плагины при импорте регистрируют свои метаданные через register().
Админ-панель читает get_all() для меню «🔌 Плагины».
"""

import logging

_PLUGINS: list[dict] = []


def register(info: dict) -> None:
    if not isinstance(info, dict):
        logging.warning(f"plugin_registry: пропущен не-dict: {info!r}")
        return
    name = info.get("name") or "Без названия"
    if any(p.get("name") == name for p in _PLUGINS):
        logging.warning(f"plugin_registry: дубль плагина '{name}' — пропущен")
        return
    _PLUGINS.append(info)
    logging.info(f"plugin_registry: зарегистрирован '{name}'")


def get_all() -> list[dict]:
    return list(_PLUGINS)


def is_empty() -> bool:
    return len(_PLUGINS) == 0
