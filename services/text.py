# services/text.py
"""Утилиты для работы с текстом команд."""

import re
import html


def esc(s) -> str:
    """Экранирует пользовательский текст для parse_mode=HTML."""
    return html.escape(s or "", quote=False)


def strip_command_prefix(text: str, command: str) -> str:
    """
    Убирает префикс команды из текста/подписи, регистронезависимо.
    Пример: strip_command_prefix("!ЛС @user привет", "!лс") -> "@user привет"
    """
    if not text:
        return ""
    pattern = rf"^{re.escape(command)}\s*"
    return re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()


def strip_command_and_target(text: str, command: str, target: str) -> str:
    """
    Убирает префикс команды и target (ID или @username) из текста.
    Пример: strip_command_and_target("!лс @user привет", "!лс", "@user") -> "привет"
    """
    if not text:
        return ""
    # Сначала убираем команду
    cleaned = strip_command_prefix(text, command)
    # Потом target в начале
    if target and cleaned.startswith(target):
        cleaned = cleaned[len(target):].lstrip()
    return cleaned