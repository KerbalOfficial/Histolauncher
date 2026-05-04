from __future__ import annotations

from launcher.dialogs import (
    ask_custom_okcancel,
    ask_custom_yesno,
    show_custom_warning,
)
from launcher.i18n import t


__all__ = [
    "prompt_create_shortcut",
    "prompt_new_user",
    "prompt_user_update",
    "prompt_beta_warning",
]


def prompt_create_shortcut():
    try:
        return ask_custom_yesno(
            t("native.prompts.createShortcutTitle"),
            t("native.prompts.createShortcutMessage"),
            kind="question",
        )
    except Exception:
        return False


def prompt_new_user():
    try:
        return ask_custom_okcancel(
            t("native.prompts.newUserTitle"),
            t("native.prompts.newUserMessage"),
            kind="question",
        )
    except Exception:
        return False


def prompt_user_update(local, remote):
    try:
        return ask_custom_yesno(
            t("native.prompts.updateAvailableTitle"),
            t(
                "native.prompts.updateAvailableMessage",
                {"local": local, "remote": remote},
            ),
            kind="question",
        )
    except Exception:
        return False


def prompt_beta_warning(local):
    try:
        show_custom_warning(
            t("native.prompts.betaWarningTitle"),
            t("native.prompts.betaWarningMessage", {"local": local}),
        )
        return True
    except Exception:
        return False
