from __future__ import annotations

from launcher.dialogs import (
    ask_custom_okcancel,
    ask_custom_yesno,
    show_custom_warning,
)


__all__ = [
    "prompt_create_shortcut",
    "prompt_new_user",
    "prompt_user_update",
    "prompt_beta_warning",
]


def prompt_create_shortcut():
    try:
        msg = (
            "Would you like Histolauncher to create a shortcut now?\n\n"
            "This adds Histolauncher to your Start Menu on Windows or your "
            "applications menu on Linux, and it can be repaired later with "
            "shortcut.pyw or shortcut.sh."
        )
        return ask_custom_yesno("Create shortcut?", msg, kind="question")
    except Exception:
        return False


def prompt_new_user():
    try:
        msg = (
            "Hi there, new user! Welcome to Histolauncher!\n\n"
            "Would you like to read INSTRUCTIONS.txt for more information "
            "about this launcher and how to enable special features (such as "
            "debug mode)?"
        )
        return ask_custom_okcancel("Welcome!", msg, kind="question")
    except Exception:
        return False


def prompt_user_update(local, remote):
    try:
        msg = (
            "Histolauncher is out-dated!\n\n"
            "Would you like to automatically download the latest version "
            "now? Be aware that this will delete everything inside the "
            "launcher directory and will reinstall everything freshly from "
            "the Histolauncher GitHub repository.\n\n"
            f"(your version: {local}, latest version: {remote})"
        )
        return ask_custom_yesno(
            "Launcher update available", msg, kind="question"
        )
    except Exception:
        return False


def prompt_beta_warning(local):
    try:
        msg = (
            "This is a beta version of Histolauncher, you may encounter many "
            "bugs during usage so please keep that in mind. If you did "
            "encounter any problems or bugs, please report it to us in the "
            "GitHub/Discord as soon as possible!\n\n"
            f"(beta version: {local})"
        )
        show_custom_warning("Beta version warning", msg)
        return True
    except Exception:
        return False
