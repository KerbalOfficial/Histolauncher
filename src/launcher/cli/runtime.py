from __future__ import annotations

import os
import sys
import traceback

from launcher.cli import terminal, tui
from launcher.cli.commands import build_registry
from launcher.cli.suggest import build_suggester
from launcher.cli.parser import ParseError, split_args
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    BOLD, DIM, FG, c, clear_screen, enable_ansi, print_banner,
    print_error, print_hint, print_info, write, writeln,
)


_BANNER_TAG = "Histolauncher CLI"


def _start_local_server(state: CliState, *, verbose: bool = True) -> bool:
    import random

    try:
        from server.http import start_server
    except Exception as exc:
        state.server_error = f"Could not import local server: {exc}"
        if verbose:
            print_error(state.server_error)
        return False

    last_error: Exception | None = None
    port: int | None = None
    server: object | None = None
    for _ in range(30):
        candidate = random.randint(10000, 20000)
        try:
            server = start_server(candidate)
            port = candidate
            break
        except OSError as exc:
            last_error = exc
            continue

    if port is None or server is None:
        detail = f": {last_error}" if last_error else ""
        state.server_error = f"Could not bind local launcher server{detail}"
        if verbose:
            print_error(state.server_error)
        return False

    state.server_port = port
    state.server = server
    os.environ["HISTOLAUNCHER_PORT"] = str(port)

    try:
        from core.settings import save_global_settings

        save_global_settings({"ygg_port": str(port)})
    except Exception:
        pass

    try:
        from server import yggdrasil as _ygg

        _ygg.prewarm_authlib_texture_properties(port=port, wait_seconds=0.0)
    except Exception:
        pass

    try:
        from launcher.webview_runner import wait_for_server

        wait_for_server(f"http://127.0.0.1:{port}/", timeout=5.0)
    except Exception:
        pass

    if state.debug and verbose:
        print_info(f"Local server listening on port {port}.")
    return True

def _shutdown_local_server(state: CliState) -> None:
    server = state.server
    if server is None:
        return
    try:
        server.shutdown()  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        server.server_close()  # type: ignore[attr-defined]
    except Exception:
        pass
    state.server = None


def _read_local_version() -> str:
    try:
        from launcher._constants import PROJECT_ROOT
        from server.api.version_check import read_local_version

        return str(read_local_version(base_dir=PROJECT_ROOT) or "unknown")
    except Exception:
        return "unknown"


def _resolve_active_account_info(state: CliState) -> tuple[str | None, str | None]:
    try:
        from core.settings import load_global_settings
        from launcher.cli.scopes import with_scope

        settings = with_scope(state, "settings", load_global_settings)
        if not isinstance(settings, dict):
            return None, None
    except Exception:
        return None, None

    name = str(settings.get("username") or "").strip() or None

    raw = str(settings.get("account_type") or "").strip()
    if not raw:
        return name, None
    lower = raw.lower()
    if lower == "microsoft":
        return name, "Microsoft"
    if lower in ("histolauncher", "histo"):
        return name, "Histolauncher"
    if lower == "local":
        return name, "Local"
    return name, raw


def _scope_display_names(state: CliState) -> dict[str, str]:
    out: dict[str, str] = {"versions": "default", "addons": "default", "settings": "default"}
    try:
        from core.settings import (
            get_active_scope_profile_id,
            list_scope_profiles,
        )
    except Exception:
        return out

    for scope in ("versions", "addons", "settings"):
        try:
            override = state.scope_id(scope)
            target_id = override or get_active_scope_profile_id(scope)
            for profile in list_scope_profiles(scope):
                if str(profile.get("id")) == str(target_id):
                    name = str(profile.get("name") or target_id)
                    if override:
                        name = name + "*"
                    out[scope] = name
                    break
            else:
                out[scope] = str(target_id or "default")
        except Exception:
            continue
    return out


def _print_welcome(state: CliState) -> None:
    width, _ = terminal.term_size()
    mode = "debug mode" if state.debug else "user mode"
    writeln("")
    writeln(c("  Welcome to Histolauncher ", BOLD, FG["header"])
            + c(state.version, BOLD, FG["accent"])
            + c(" CLI ", BOLD, FG["header"])
            + c(f"({mode})", FG["muted"]))
    writeln("  " + c("\u2500" * max(20, width - 4), FG["subtle"]))
    print_info("Type " + c("help", BOLD, FG["primary"])
               + " to see what you can do.")

def _do_eula_if_needed() -> bool:
    try:
        from launcher._constants import (
            DATA_DIR_PATH,
            EULA_ACCEPTANCE_MARKER,
            has_accepted_mojang_eula,
        )
    except Exception:
        return True

    if has_accepted_mojang_eula():
        return True

    from launcher.cli.dialogs import confirm
    from launcher.i18n import t

    note = t("native.disclaimer.noteFresh")
    if os.path.exists(DATA_DIR_PATH):
        note = t("native.disclaimer.noteExisting")
    message = t("native.disclaimer.message", {"note": note})

    ok = confirm(
        t("native.disclaimer.title"),
        message,
        yes_label=t("common.ok"), no_label=t("common.cancel"), default_yes=True,
    )
    if not ok:
        return False
    try:
        os.makedirs(DATA_DIR_PATH, exist_ok=True)
        with open(EULA_ACCEPTANCE_MARKER, "w", encoding="utf-8") as f:
            f.write(
                "Minecraft EULA (https://www.minecraft.net/en-us/eula) has been "
                "successfully acknowledged by the user via the CLI.\n"
            )
    except Exception:
        pass
    return True


def _gather_update_info(state: CliState) -> dict:
    try:
        from launcher._constants import PROJECT_ROOT, REMOTE_TIMEOUT
        from launcher.updater import select_latest_release_for_local
        from server.api.version_check import read_local_version

        local = read_local_version(base_dir=PROJECT_ROOT)
        release_info, _reason = select_latest_release_for_local(
            local, timeout=REMOTE_TIMEOUT
        )
        return {"local": local, "release_info": release_info}
    except Exception:
        return {"local": None, "release_info": None}


def _open_instructions() -> None:
    try:
        from launcher._constants import PROJECT_ROOT

        path = os.path.join(PROJECT_ROOT, "INSTRUCTIONS.txt")
        if sys.platform.startswith("win"):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception:
                import subprocess

                subprocess.Popen(["notepad", path])
        elif sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", path])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _run_startup_prompts(state: CliState, update_info: dict | None) -> bool:
    from launcher.cli.dialogs import confirm, show_message
    from launcher.i18n import t

    try:
        from launcher._constants import DATA_FILE_EXISTS, PROJECT_ROOT
    except Exception:
        DATA_FILE_EXISTS, PROJECT_ROOT = True, os.getcwd()

    yes = t("common.yes")
    no = t("common.no")

    # --- new user: offer instructions + shortcut --------------------------
    if not DATA_FILE_EXISTS:
        if confirm(
            t("native.prompts.newUserTitle"),
            t("native.prompts.newUserMessage"),
            yes_label=yes, no_label=no, default_yes=True,
        ):
            _open_instructions()

        if sys.platform.startswith("win") or sys.platform.startswith("linux"):
            try:
                if confirm(
                    t("native.prompts.createShortcutTitle"),
                    t("native.prompts.createShortcutMessage"),
                    yes_label=yes, no_label=no, default_yes=True,
                ):
                    from core.shortcut_manager import install_platform_shortcut

                    if install_platform_shortcut(PROJECT_ROOT):
                        show_message(
                            t("native.prompts.shortcutCreatedTitle"),
                            t("native.prompts.shortcutCreatedMessage"),
                            kind="success",
                        )
                    else:
                        show_message(
                            t("native.prompts.shortcutErrorTitle"),
                            t("native.prompts.shortcutErrorMessage"),
                            kind="error",
                        )
            except Exception:
                pass

    info = update_info or {}
    local = info.get("local")
    release_info = info.get("release_info")

    # --- beta warning -----------------------------------------------------
    try:
        from launcher.updater import should_prompt_beta_warning

        promptb, _ = should_prompt_beta_warning(local)
    except Exception:
        promptb = False
    if promptb:
        show_message(
            t("native.prompts.betaWarningTitle"),
            t("native.prompts.betaWarningMessage", {"local": local}),
            kind="warn",
        )

    # --- update available -------------------------------------------------
    remote = (release_info or {}).get("tag_name") if release_info else None
    try:
        from launcher.updater import should_prompt_update

        promptu, _ = should_prompt_update(local, remote)
    except Exception:
        promptu = False

    if promptu and release_info:
        if confirm(
            t("native.prompts.updateAvailableTitle"),
            t(
                "native.prompts.updateAvailableMessage",
                {"local": local, "remote": remote},
            ),
            yes_label=yes, no_label=no, default_yes=True,
        ):
            from launcher.updater import perform_self_update

            try:
                result = perform_self_update(release_info, local)
            except Exception as exc:
                result = {"success": False, "error": str(exc)}
            if result.get("success"):
                show_message(
                    t("native.prompts.updateInstalledTitle"),
                    t("native.prompts.updateInstalledMessage"),
                    kind="success",
                )
                try:
                    import subprocess

                    subprocess.Popen([sys.executable, *sys.argv])
                except Exception:
                    pass
                return True

            fail_message = t("native.prompts.updateFailedMessage")
            detail = str(result.get("error") or "").strip()
            if detail:
                fail_message = f"{fail_message}\n\n{detail}"
            show_message(
                t("native.prompts.updateFailedTitle"),
                fail_message,
                kind="error",
            )

    return False


def _current_state_signature(state: CliState) -> tuple:
    account, account_type = _resolve_active_account_info(state)
    return (
        tuple(sorted((_scope_display_names(state)).items())),
        account,
        account_type,
    )


def _redraw_header(state: CliState) -> None:
    scopes = _scope_display_names(state)
    account, account_type = _resolve_active_account_info(state)
    tui.draw_header(
        version=state.version,
        debug=state.debug,
        scopes=scopes,
        account=account,
        account_type=account_type,
    )


def _execute_command(state: CliState, tokens: list[str], registry) -> int:
    if not tokens:
        print_error("No command specified.")
        print_hint("Example: python launcher.pyw --cli help")
        return 1

    name, *args = tokens
    cmd = registry.get(name)
    if cmd is None:
        print_error(f"Unknown command: {name}")
        print_hint("Type 'python launcher.pyw --cli help' to list every command.")
        return 1

    try:
        cmd.handler(state, args)
    except KeyboardInterrupt:
        writeln("")
        print_info("Command cancelled.")
        return 130
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return int(code) if isinstance(code, int) else 1
    except Exception as exc:
        print_error(f"Command failed: {exc}")
        if state.debug:
            writeln(c(traceback.format_exc(), DIM, FG["muted"]))
        return 1
    return 0


def run_once(*, command_tokens: list[str], debug: bool = False) -> int:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    enable_ansi()
    try:
        from launcher.cli import cli_theme

        cli_theme.apply_theme()
    except Exception:
        pass

    state = CliState(debug=debug, version=_read_local_version(), one_shot=True)

    from launcher.cli import tui

    tui.enable_standalone_modals(draggable=False)
    exit_code = 1
    try:
        if not _do_eula_if_needed():
            return 0

        try:
            from core.logger import set_console_quiet

            set_console_quiet(True)
        except Exception:
            set_console_quiet = None  # type: ignore[assignment]

        if not _start_local_server(state, verbose=False):
            print_error(
                state.server_error
                or "Cannot run Histolauncher CLI without the local server."
            )
            return 1

        registry = build_registry()
        exit_code = _execute_command(state, command_tokens, registry)
    finally:
        _shutdown_local_server(state)
        tui.disable_standalone_modals()
        try:
            from core.logger import set_console_quiet

            set_console_quiet(False)
        except Exception:
            pass
        try:
            from launcher.cli import cli_theme

            cli_theme.reset_terminal_colors()
        except Exception:
            pass

    return exit_code


def run(*, debug: bool = False) -> int:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    enable_ansi()
    try:
        from launcher.cli import cli_theme
        cli_theme.apply_theme()
    except Exception:
        pass
    state = CliState(debug=debug, version=_read_local_version())

    # --- startup splash: boot the server + check for updates while the
    from launcher.cli.splash import CliSplash, run_with_splash

    try:
        from core.logger import set_console_quiet

        set_console_quiet(True)
    except Exception:
        set_console_quiet = None  # type: ignore[assignment]

    splash = CliSplash()
    splash.show()
    server_ok = False
    update_info: dict | None = None
    relaunching = False
    try:
        server_ok = bool(
            run_with_splash(
                splash, _start_local_server, state, verbose=False,
            )
        )
        if not server_ok:
            splash.close(ensure_minimum=False)
            if set_console_quiet is not None:
                set_console_quiet(False)
            print_error(
                state.server_error
                or "Cannot start Histolauncher CLI without the local server."
            )
            return 1

        update_info = run_with_splash(splash, _gather_update_info, state)

        tui.set_modal_backdrop(splash.draw_dimmed, animator=splash.advance)
        try:
            if not _do_eula_if_needed():
                _shutdown_local_server(state)
                return 0
            relaunching = _run_startup_prompts(state, update_info)
        finally:
            tui.set_modal_backdrop(None)
    finally:
        splash.close(ensure_minimum=server_ok)
        if set_console_quiet is not None:
            set_console_quiet(False)

    if relaunching:
        return 0
    if state.debug:
        print_info(f"Local server listening on port {state.server_port}.")

    registry = build_registry()
    suggester = build_suggester(registry, state)

    tui.enter(debug=debug)
    try:
        _redraw_header(state)
        tui.draw_footer(new_tip=True)
        tui.park_in_scroll_region()
        _print_welcome(state)
        last_signature = _current_state_signature(state)

        while state.running:
            tui.refresh_layout()
            _redraw_header(state)
            tui.draw_footer(prompt_text="")

            try:
                line = tui.read_input_line(
                    history=state.history,
                    validator=lambda name: registry.get(name) is not None,
                    suggester=suggester,
                )
            except KeyboardInterrupt:
                break
            if line is None:
                break
            stripped = line.strip()
            if not stripped:
                continue

            if not state.history or state.history[-1] != stripped:
                state.history.append(stripped)
                if len(state.history) > 200:
                    del state.history[: len(state.history) - 200]

            try:
                tokens = split_args(stripped)
            except ParseError as exc:
                print_error(f"Parse error: {exc}")
                continue

            if not tokens:
                continue

            name, *args = tokens
            cmd = registry.get(name)
            if cmd is None:
                print_error(f"Unknown command: {name}")
                print_hint("Type 'help' to list every command.")
                continue

            try:
                with tui.command_scope():
                    cmd.handler(state, args)
            except KeyboardInterrupt:
                writeln("")
                print_info("Command cancelled.")
            except SystemExit:
                raise
            except Exception as exc:
                print_error(f"Command failed: {exc}")
                if state.debug:
                    writeln(c(traceback.format_exc(), DIM, FG["muted"]))

            new_signature = _current_state_signature(state)
            if new_signature != last_signature:
                last_signature = new_signature

            tui.draw_footer(new_tip=True)
    finally:
        tui.leave()
        _shutdown_local_server(state)
        try:
            from launcher.cli import cli_theme
            cli_theme.reset_terminal_colors()
        except Exception:
            pass

    writeln(c("  Goodbye!", FG["muted"]))
    return 0
