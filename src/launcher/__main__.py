from __future__ import annotations

import sys

from launcher.bootstrap import main


def _is_cli_invocation() -> bool:
    for arg in sys.argv[1:]:
        if arg in ("--cli", "-c", "--cli-mode"):
            return True
    return False


if __name__ == "__main__":
    if _is_cli_invocation():
        try:
            from launcher.venv_manager import (
                activate_venv_site_packages,
                ensure_venv,
                venv_exists,
            )

            if not venv_exists():
                ensure_venv(log=lambda *_a, **_k: None)
            activate_venv_site_packages()
        except Exception:
            pass

        from launcher.cli import run_cli

        if sys.platform.startswith("win"):
            debug = not (sys.executable or "").lower().endswith("pythonw.exe")
        else:
            debug = False
        raise SystemExit(run_cli(debug=debug))
    main()
