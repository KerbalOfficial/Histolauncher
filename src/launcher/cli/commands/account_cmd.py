from __future__ import annotations

from launcher.cli.commands import ArgSpec, Command, register
from launcher.cli.dialogs import confirm, select_one, text_input
from launcher.cli.scopes import scope_override
from launcher.cli.state import CliState
from launcher.cli.terminal import (
    BOLD, FG, c, print_error, print_hint, print_info, print_section,
    print_success, writeln,
)


def _cmd_whoami(state: CliState, args: list[str]) -> None:
    from core.settings import load_global_settings
    from server.api.routes.account import api_account_current

    with scope_override(state, "settings"):
        info = api_account_current() or {}
        settings = load_global_settings() or {}

    raw_type = str(info.get("account_type") or info.get("type") or settings.get("account_type") or "Local").strip() or "Local"
    username = info.get("username") or settings.get("username") or "(none)"
    uuid = info.get("uuid") or "(none)"

    print_section("Active account")
    writeln("  " + c("Username : ", FG["muted"]) + c(str(username), BOLD, FG["accent"]))
    writeln("  " + c("UUID     : ", FG["muted"]) + c(str(uuid), FG["value"]))
    writeln("  " + c("Type     : ", FG["muted"]) + c(raw_type, FG["tag"]))
    if info.get("skin_url"):
        writeln("  " + c("Skin URL : ", FG["muted"]) + c(str(info["skin_url"]), FG["muted"]))
    if not info.get("ok") and raw_type.lower() in {"microsoft", "histolauncher"}:
        err = str(info.get("error") or "Not authenticated")
        print_hint(f"Online account not authenticated: {err}")
        print_hint("Run 'login' to sign in again.")


def _cmd_login(state: CliState, args: list[str]) -> None:
    account_types = ["Local", "Histolauncher", "Microsoft"]
    pre_selected = args[0].strip().lower() if args else ""
    idx = next((i for i, t in enumerate(account_types) if t.lower() == pre_selected), None)
    if idx is None:
        idx = select_one("Choose account type", "Which account type would you like to use?",
                         account_types, default=0)
        if idx is None:
            print_info("Cancelled.")
            return
    account_type = account_types[idx]

    if account_type == "Local":
        username = text_input("Local account", "Enter the in-game username to use:",
                              default="Player",
                              validator=lambda v: None if 1 <= len(v.strip()) <= 16 else "1-16 characters")
        if username is None:
            print_info("Cancelled.")
            return
        from server.api.routes.settings import api_settings

        with scope_override(state, "settings"):
            result = api_settings({"account_type": "Local", "username": username.strip()})
        if not result.get("ok"):
            print_error(result.get("error") or "Save failed.")
            return
        print_success(f"Now using local account '{username.strip()}'.")
        return

    if account_type == "Histolauncher":
        username = text_input("Histolauncher login", "Username:")
        if username is None:
            print_info("Cancelled.")
            return
        password = text_input("Histolauncher login", "Password:", password=True)
        if password is None:
            print_info("Cancelled.")
            return
        from server.api.routes.account import api_account_login

        with scope_override(state, "settings"):
            result = api_account_login({"username": username, "password": password})
        if not result.get("ok"):
            print_error(result.get("error") or "Login failed.")
            return
        print_success(f"Logged in as {result.get('username') or username}.")
        return

    if account_type == "Microsoft":
        from server.api.routes.account import api_account_microsoft_device_code, api_account_microsoft_poll

        with scope_override(state, "settings"):
            code_info = api_account_microsoft_device_code() or {}
        if not code_info.get("ok", True) and code_info.get("error"):
            print_error(code_info["error"])
            return
        url = code_info.get("verification_uri") or "https://www.microsoft.com/link"
        user_code = code_info.get("user_code") or "(see Microsoft login flow)"
        device_code = code_info.get("device_code") or ""
        print_section("Microsoft sign-in")
        writeln("  Open " + c(url, BOLD, FG["accent"]))
        writeln("  Enter the code: " + c(user_code, BOLD, FG["header"]))
        print_hint("This window will poll until you approve the sign-in. Press Esc or Ctrl+C to cancel.")

        import sys as _sys
        import time as _t
        from launcher.cli import keys, tui

        interactive = _sys.stdin.isatty()
        use_tui = tui.is_active()
        next_poll = _t.monotonic() + 3.0
        try:
            while True:
                if interactive:
                    k = tui.pump_idle(0.2) if use_tui else keys.read_key(0.2)
                    if k in (keys.KEY_CTRL_C, keys.KEY_ESC) or k == "q":
                        print_info("Cancelled.")
                        return
                    if _t.monotonic() < next_poll:
                        continue
                else:
                    _t.sleep(3)
                next_poll = _t.monotonic() + 3.0
                with scope_override(state, "settings"):
                    poll = api_account_microsoft_poll({"device_code": device_code}) or {}
                if poll.get("ok"):
                    print_success("Microsoft account linked.")
                    return
                if poll.get("pending"):
                    continue
                err = (poll.get("error") or "").lower()
                if not err or "pending" in err or "slow_down" in err:
                    continue
                print_error(poll.get("error") or "Microsoft sign-in failed.")
                return
        except KeyboardInterrupt:
            print_info("Cancelled.")
            return


def _cmd_logout(state: CliState, args: list[str]) -> None:
    if not confirm("Sign out", "Sign out of the current account?",
                   yes_label="Sign out", no_label="Stay", default_yes=False):
        print_info("Cancelled.")
        return
    with scope_override(state, "settings"):
        from server.api.routes.account import api_account_disconnect

        result = api_account_disconnect() or {}
    if not result.get("ok", True) and result.get("error"):
        print_error(result["error"])
        return
    print_success("Signed out.")


def _cmd_refresh_assets(state: CliState, args: list[str]) -> None:
    from server.api.routes.account import api_account_refresh_assets

    with scope_override(state, "settings"):
        result = api_account_refresh_assets() or {}
    if not result.get("ok"):
        print_error(result.get("error") or "Could not refresh account assets.")
        if result.get("unauthorized"):
            print_hint("Run 'login' to sign in again.")
        return
    name = result.get("username") or "your account"
    print_success(f"Refreshed skin and profile data for {name}.")


register(Command(
    name="account",
    summary="Show the current account (username, UUID, type).",
    handler=_cmd_whoami,
    usage="account",
    aliases=("whoami",),
    category="Account",
))
register(Command(
    name="login",
    summary="Sign in to a Local, Histolauncher, or Microsoft account.",
    handler=_cmd_login,
    usage="login [Local|Histolauncher|Microsoft]",
    details="If no type is given, an interactive picker is shown. Microsoft uses the device-code flow.",
    category="Account",
    args=(ArgSpec("type", ("Local", "Histolauncher", "Microsoft"), required=False),),
))
register(Command(
    name="refreshAssets",
    summary="Re-fetch your skin, cape, and profile from the account server.",
    handler=_cmd_refresh_assets,
    usage="refreshAssets",
    category="Account",
))
register(Command(
    name="logout",
    summary="Sign out of the current account.",
    handler=_cmd_logout,
    usage="logout",
    category="Account",
    aliases=("signOut",),
))
