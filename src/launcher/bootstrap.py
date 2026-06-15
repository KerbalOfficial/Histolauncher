from __future__ import annotations

import importlib
import os
import random
import shutil
import subprocess
import sys
import threading

from core.logger import safe_print, dim_line
from core.subprocess_utils import no_window_kwargs

from launcher._constants import (
    DATA_DIR_PATH,
    DATA_FILE_EXISTS,
    EULA_ACCEPTANCE_MARKER,
    PROJECT_ROOT,
    REMOTE_TIMEOUT,
    has_accepted_mojang_eula,
)
from launcher.console import setup_launcher_logging
from launcher.dialogs import (
    ask_custom_okcancel,
    build_language_selector,
    show_custom_dialog,
    show_custom_error,
    show_custom_info,
)
from launcher.i18n import set_temporary_language, suggested_language_code, t
from launcher.pip_installer import install
from launcher.prompts import (
    prompt_create_shortcut,
    prompt_beta_warning,
    prompt_new_user,
    prompt_user_update,
)
from launcher.splash import LauncherSplash
from launcher.updater import (
    perform_self_update,
    select_latest_release_for_local,
    should_prompt_beta_warning,
    should_prompt_update,
)
from launcher.webview_runner import (
    control_panel_fallback_window,
    open_in_browser,
    open_with_webview,
    wait_for_server,
)


__all__ = ["main", "check_and_prompt", "show_disclaimer_if_needed"]


_RUNTIME_MODULE_PREFIXES = (
    "keyring",
    "PyQt6",
    "pypresence",
    "qtpy",
    "webview",
)

if not sys.platform.startswith("linux"):
    _RUNTIME_MODULE_PREFIXES += ("plyer",)


def _start_local_server_with_retry(
    *,
    min_port: int = 10000,
    max_port: int = 20000,
    attempts: int = 30,
):
    from server.http import start_server

    tried_ports: set[int] = set()
    last_error: Exception | None = None

    for _ in range(max(1, int(attempts))):
        port = random.randint(min_port, max_port)
        if port in tried_ports:
            continue
        tried_ports.add(port)

        try:
            server = start_server(port)
            return port, server
        except OSError as exc:
            last_error = exc
            safe_print(
                f"[launcher] Local server port {port} unavailable: {exc}"
            )

    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"Could not bind local launcher server{detail}")


def _reconfigure_std_streams() -> None:
    import io

    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if _stream is None:
            setattr(sys, _stream_name, io.StringIO())
            continue
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _save_initial_language_choice(language: str | None) -> None:
    if not language:
        return
    try:
        from core.settings import save_global_settings

        save_global_settings({"launcher_language": language})
    except Exception:
        pass


def show_disclaimer_if_needed() -> None:
    if has_accepted_mojang_eula():
        return
    try:
        language_selector = {}

        def build_language_prompt(context):
            language_selector.clear()
            language_selector.update(
                build_language_selector(
                    context["text_wrap"],
                    context["dialog"],
                    context["ui_font"],
                    context["direction"],
                    initial_code=suggested_language_code(),
                    refresh_dialog=context["refresh_dialog"],
                )
                or {}
            )
            return language_selector

        selected_language = show_custom_dialog(
            lambda: t("native.languagePrompt.title"),
            lambda: t("native.languagePrompt.message"),
            kind="question",
            show_icon=False,
            buttons=[
                {
                    "label": lambda: t("common.cancel"),
                    "value": None,
                    "style": "default",
                    "cancel": True,
                },
                {
                    "label": lambda: t("common.next"),
                    "value": lambda: language_selector.get("get_value", lambda: None)(),
                    "style": "primary",
                    "primary": True,
                },
            ],
            content_builder=build_language_prompt,
        )
        if not selected_language:
            sys.exit()
        selected_language = set_temporary_language(selected_language)

        note = t("native.disclaimer.noteFresh")
        if os.path.exists(DATA_DIR_PATH):
            note = t("native.disclaimer.noteExisting")
        msg = t("native.disclaimer.message", {"note": note})
        result = ask_custom_okcancel(t("native.disclaimer.title"), msg, kind="question")
        if not result:
            sys.exit()
        os.makedirs(DATA_DIR_PATH, exist_ok=True)
        with open(EULA_ACCEPTANCE_MARKER, "w", encoding="utf-8") as handle:
            handle.write("Minecraft EULA (https://www.minecraft.net/en-us/eula) has been successfully acknowledged by the user.\n")
        _save_initial_language_choice(selected_language)
    except Exception:
        sys.exit()


def check_and_prompt(splash=None):
    from server.api.version_check import read_local_version

    local = read_local_version(base_dir=PROJECT_ROOT)
    release_info, release_reason = select_latest_release_for_local(
        local, timeout=REMOTE_TIMEOUT
    )
    remote = (release_info or {}).get("tag_name")

    safe_print(
        "[launcher] should_prompt_new_user[prompt]: "
        + str(not DATA_FILE_EXISTS)
    )
    if not DATA_FILE_EXISTS:
        safe_print("[launcher] PROMPTING NEW USER...")
        open_instructions = prompt_new_user()
        safe_print(
            f"[launcher] prompt_user_update[user_accepted]: "
            f"{open_instructions}"
        )
        if open_instructions:
            try:
                instructions_path = os.path.join(PROJECT_ROOT, "INSTRUCTIONS.txt")
                if sys.platform.startswith("win"):
                    try:
                        os.startfile(instructions_path)  # type: ignore[attr-defined]
                    except Exception:
                        subprocess.Popen(
                            ["notepad", instructions_path],
                            **no_window_kwargs(),
                        )
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", instructions_path])
                else:
                    subprocess.Popen(["xdg-open", instructions_path])
            except Exception:
                pass

        if sys.platform.startswith("win") or sys.platform.startswith("linux"):
            try:
                safe_print("[launcher] PROMPTING SHORTCUT SETUP...")
                create_shortcut = prompt_create_shortcut()
                safe_print(
                    f"[launcher] prompt_create_shortcut[user_accepted]: "
                    f"{create_shortcut}"
                )
                if create_shortcut:
                    from core.shortcut_manager import install_platform_shortcut

                    if install_platform_shortcut(PROJECT_ROOT):
                        show_custom_info(
                            t("native.prompts.shortcutCreatedTitle"),
                            t("native.prompts.shortcutCreatedMessage"),
                        )
                    else:
                        show_custom_error(
                            t("native.prompts.shortcutErrorTitle"),
                            t("native.prompts.shortcutErrorMessage"),
                        )
            except Exception as e:
                safe_print(
                    f"[launcher] Warning: shortcut setup prompt failed: {e}"
                )

    promptb, reasonb = should_prompt_beta_warning(local)
    safe_print(
        f"[launcher] should_prompt_beta_warning[prompt]: {promptb}"
    )
    safe_print(
        f"[launcher] should_prompt_beta_warning[reason]: {reasonb}"
    )
    if promptb:
        safe_print("[launcher] PROMPTING BETA WARNING...")
        prompt_beta_warning(local)

    promptu, reasonu = should_prompt_update(local, remote)
    safe_print(f"[launcher] should_prompt_update[prompt]: {promptu}")
    safe_print(f"[launcher] should_prompt_update[reason]: {reasonu}")
    if not release_info:
        safe_print(
            f"[launcher] No release candidate found for updater: "
            f"{release_reason}"
        )
    if promptu and release_info:
        safe_print("[launcher] PROMPTING USER UPDATE...")
        open_update = prompt_user_update(local, remote)
        safe_print(
            f"[launcher] prompt_user_update[user_accepted]: {open_update}"
        )
        if open_update:
            if splash is not None:
                splash.close(ensure_minimum=False)
            update_result = perform_self_update(release_info, local)
            if update_result.get("success"):
                try:
                    show_custom_info(
                        t("native.prompts.updateInstalledTitle"),
                        t("native.prompts.updateInstalledMessage"),
                    )
                except Exception:
                    pass

                try:
                    launcher_script = os.path.join(PROJECT_ROOT, "launcher.pyw")
                    if not os.path.isfile(launcher_script):
                        launcher_script = os.path.join(PROJECT_ROOT, "launcher.py")
                    subprocess.Popen(
                        [sys.executable, launcher_script],
                        **no_window_kwargs(),
                    )
                except Exception as e:
                    safe_print(
                        f"[launcher] Failed to relaunch launcher: {e}"
                    )

                return False

            safe_print(
                f"[launcher] Self-update failed: {update_result.get('error')}"
            )
            try:
                show_custom_error(
                    t("native.prompts.updateFailedTitle"),
                    t("native.prompts.updateFailedMessage"),
                )
            except Exception:
                pass
            if splash is not None:
                splash.show()

    return True


def _refresh_launcher_venv() -> None:
    try:
        from launcher.venv_manager import activate_venv_site_packages

        activate_venv_site_packages()
    except Exception:
        pass
    importlib.invalidate_caches()


def _launcher_venv_site_packages() -> str | None:
    try:
        from launcher.venv_manager import get_venv_site_packages

        site_packages = get_venv_site_packages()
    except Exception:
        return None

    if not site_packages:
        return None
    return os.path.realpath(site_packages)


def _is_module_from_launcher_venv(module) -> bool:
    site_packages = _launcher_venv_site_packages()
    module_path = getattr(module, "__file__", None)
    if not site_packages or not module_path:
        return False

    real_module_path = os.path.realpath(module_path)
    site_prefix = site_packages + os.sep
    return real_module_path == site_packages or real_module_path.startswith(site_prefix)


def _clear_runtime_import_cache() -> None:
    for name in tuple(sys.modules):
        for prefix in _RUNTIME_MODULE_PREFIXES:
            if name == prefix or name.startswith(prefix + "."):
                sys.modules.pop(name, None)
                break


def _webview_install_target() -> list[str]:
    if sys.platform.startswith("linux"):
        os.environ.setdefault("PYWEBVIEW_GUI", "qt")
        os.environ.setdefault("QT_API", "pyqt6")
        return ["pywebview[qt]", "PyQt6", "PyQt6-WebEngine", "qtpy"]
    return ["pywebview"]


def _import_webview_module():
    if sys.platform.startswith("linux"):
        os.environ.setdefault("PYWEBVIEW_GUI", "qt")
        os.environ.setdefault("QT_API", "pyqt6")
        import PyQt6  # noqa: F401
        import PyQt6.QtWebEngineCore as qt_webengine_core

        if not _is_module_from_launcher_venv(PyQt6):
            raise ImportError("PyQt6 is not loaded from the launcher venv")
        if not _is_module_from_launcher_venv(qt_webengine_core):
            raise ImportError(
                "PyQt6.QtWebEngineCore is not loaded from the launcher venv"
            )

    import webview as wv

    if not _is_module_from_launcher_venv(wv):
        raise ImportError("pywebview is not loaded from the launcher venv")

    return wv


def _probe_runtime_features() -> tuple[dict[str, bool], dict[str, Exception]]:
    status = {
        "keyring": False,
        "webview": False,
        "pypresence": False,
    }
    errors: dict[str, Exception] = {}

    if not sys.platform.startswith("linux"):
        status["plyer"] = False

    try:
        _import_webview_module()
    except Exception as exc:
        errors["webview"] = exc
    else:
        status["webview"] = True

    try:
        import keyring as _kr
    except Exception as exc:
        errors["keyring"] = exc
    else:
        if not _is_module_from_launcher_venv(_kr):
            errors["keyring"] = ImportError(
                "keyring is not loaded from the launcher venv"
            )
        else:
            status["keyring"] = True

    try:
        import pypresence
    except Exception as exc:
        errors["pypresence"] = exc
    else:
        if not _is_module_from_launcher_venv(pypresence):
            errors["pypresence"] = ImportError(
                "pypresence is not loaded from the launcher venv"
            )
        else:
            status["pypresence"] = True

    if "plyer" in status:
        try:
            import plyer
        except Exception as exc:
            errors["plyer"] = exc
        else:
            if not _is_module_from_launcher_venv(plyer):
                errors["plyer"] = ImportError(
                    "plyer is not loaded from the launcher venv"
                )
            else:
                status["plyer"] = True

    return status, errors


def _missing_runtime_packages(status: dict[str, bool]) -> list[str]:
    missing: list[str] = []
    if not status["webview"]:
        missing.extend(_webview_install_target())
    if not status.get("keyring"):
        missing.append("keyring")
    if not status["pypresence"]:
        missing.append("pypresence")
    if status.get("plyer") is False:
        missing.append("plyer")
    return list(dict.fromkeys(missing))


def _ensure_runtime_dependencies() -> tuple[dict[str, bool], dict[str, Exception]]:
    status, errors = _probe_runtime_features()
    missing_packages = _missing_runtime_packages(status)

    if not missing_packages:
        return status, errors

    safe_print(
        "[installation] Missing runtime dependencies detected. "
        "Installing required components automatically..."
    )

    success = install(
        missing_packages,
        display_name=t("native.install.requiredComponents"),
    )
    if not success:
        safe_print(
            "[installation] Automatic dependency installation failed."
        )

    safe_print("[installation] Refreshing python packages...")
    _refresh_launcher_venv()
    _clear_runtime_import_cache()
    refreshed_status, refreshed_errors = _probe_runtime_features()

    if success and not _missing_runtime_packages(refreshed_status):
        safe_print(
            "[installation] Required components are ready."
        )

    return refreshed_status, refreshed_errors


def main():
    _reconfigure_std_streams()

    if sys.platform.startswith("linux"):
        os.environ.setdefault("PYWEBVIEW_GUI", "qt")
        os.environ.setdefault("QT_API", "pyqt6")

    if not sys.platform.startswith("win") and sys.platform != "darwin":
        try:
            from launcher.fonts import preinstall_linux_font
            preinstall_linux_font()
        except Exception:
            pass

        try:
            from launcher.linux_icon import install_linux_window_icon
            from launcher._constants import PNG_ICON_PATH
            if os.path.isfile(PNG_ICON_PATH):
                if os.environ.get("PYWEBVIEW_GUI", "").lower() != "qt":
                    install_linux_window_icon(PNG_ICON_PATH)
        except Exception:
            pass

    show_disclaimer_if_needed()

    setup_launcher_logging()

    try:
        from launcher.win32_icon import set_app_user_model_id

        set_app_user_model_id("histolauncher.launcher")
    except Exception as e:
        safe_print(
            f"[launcher] Warning: could not set AppUserModelID: {e}"
        )

    safe_print("[launcher] Initializing startup splash...")
    splash = LauncherSplash()
    splash.show()

    runtime_status, runtime_errors = _ensure_runtime_dependencies()

    try:
        from core.settings.account import migrate_all_tokens_to_keyring
        migrate_all_tokens_to_keyring()
    except Exception:
        pass

    try:
        from core import discord_rpc
    except Exception as e:
        safe_print(
            f"[launcher] Warning: could not import Discord RPC module: {e}"
        )
        discord_rpc = None

    if not runtime_status["pypresence"]:
        safe_print(
            "[installation] pypresence is unavailable. Discord Rich "
            "Presence will be disabled."
        )

    if discord_rpc is not None:
        from server.api.version_check import read_local_version

        discord_rpc.set_launcher_version(read_local_version(base_dir=PROJECT_ROOT))
        discord_rpc.start_discord_rpc()
        discord_rpc.set_launcher_presence("Starting launcher")

    try:
        from core.settings import get_base_dir

        cache_dir = os.path.join(get_base_dir(), "cache")
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            safe_print(
                f"[startup] Cleared cache directory: {cache_dir}"
            )
    except Exception as e:
        safe_print(
            f"[launcher] Warning: could not clear cache directory: {e}"
        )

    try:
        from core.downloader.progress import cleanup_orphaned_progress_files

        cleanup_orphaned_progress_files(max_age_seconds=3600)
    except Exception as e:
        safe_print(
            f"[launcher] Warning: could not cleanup orphaned progress "
            f"files: {e}"
        )

    wv = None
    _HAS_WEBVIEW = runtime_status["webview"]
    if _HAS_WEBVIEW:
        try:
            wv = _import_webview_module()
        except Exception as e:
            _HAS_WEBVIEW = False
            runtime_errors["webview"] = e

    if not _HAS_WEBVIEW:
        webview_error = runtime_errors.get("webview")
        safe_print(
            f"[installation] pywebview failed to load: {webview_error}"
        )
        safe_print(
            "[installation] Falling back to browser mode."
        )

    safe_print(dim_line("------------------------------------------------"))

    try:
        safe_print("Checking information and prompting...")
        proceed = check_and_prompt(splash=splash)
        if proceed:
            safe_print(
                "Finished prompting! Initializing launcher..."
            )
    except Exception as e:
        safe_print(
            f"Something went wrong while checking and prompting: {e}"
        )
        proceed = True

    if not proceed:
        safe_print("[launcher] Exiting launcher...")
        splash.close(ensure_minimum=False)
        if discord_rpc is not None:
            discord_rpc.stop_discord_rpc()
        return

    safe_print(dim_line("------------------------------------------------"))

    safe_print("[launcher] Starting local server...")
    try:
        port, local_server = _start_local_server_with_retry()
    except Exception as e:
        safe_print(
            f"[launcher] Failed to start local server: {e}"
        )
        splash.close(ensure_minimum=False)
        if discord_rpc is not None:
            discord_rpc.stop_discord_rpc()
        return

    try:
        from core.settings import save_global_settings

        save_global_settings({"ygg_port": str(port)})
    except Exception:
        pass

    os.environ["HISTOLAUNCHER_PORT"] = str(port)
    safe_print(
        f"[launcher] Local server listening on port {port}."
    )
    splash.pump()
    try:
        from server import yggdrasil as _ygg

        _ygg.prewarm_authlib_texture_properties(
            port=port,
            wait_seconds=0.0,
        )
    except Exception:
        pass
    url = f"http://127.0.0.1:{port}/"

    if not wait_for_server(url, timeout=5.0, on_poll=splash.pump):
        safe_print(
            "[launcher] Server did not respond within timeout; something has "
            "failed! Exiting launcher..."
        )
        splash.close(ensure_minimum=False)
        try:
            local_server.shutdown()
            local_server.server_close()
        except Exception:
            pass
        if discord_rpc is not None:
            discord_rpc.stop_discord_rpc()
        return

    safe_print(dim_line("------------------------------------------------"))
    if discord_rpc is not None:
        discord_rpc.set_launcher_presence("Browsing launcher")

    if not _HAS_WEBVIEW or not open_with_webview(wv, port, splash=splash):
        splash.close(ensure_minimum=False)
        open_in_browser(port)
        control_panel_fallback_window(port)
        if discord_rpc is not None:
            discord_rpc.stop_discord_rpc()
        return

    if discord_rpc is not None:
        discord_rpc.stop_discord_rpc()
