#!/bin/sh

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" 2>/dev/null && pwd)
if [ -z "$SCRIPT_DIR" ]; then
    echo "Error: Could not determine the Histolauncher folder."
    exit 1
fi

cd "$SCRIPT_DIR" || exit 1

find_python() {
    if command -v python3 > /dev/null 2>&1; then
        command -v python3
        return 0
    fi
    if command -v python > /dev/null 2>&1; then
        command -v python
        return 0
    fi
    return 1
}

PYTHON_CMD=$(find_python)
if [ -z "$PYTHON_CMD" ]; then
    echo "Error: Python 3 is not installed. Run launcher.sh first or install Python manually."
    exit 1
fi

if ! "$PYTHON_CMD" -c "import tkinter" > /dev/null 2>&1; then
    echo "Error: Tkinter is not installed. Run launcher.sh first or install your distro's Tkinter package."
    exit 1
fi

SHORTCUT_SCRIPT="$SCRIPT_DIR/shortcut.pyw"
if [ ! -f "$SHORTCUT_SCRIPT" ]; then
    echo "Error: Could not find shortcut.pyw."
    exit 1
fi

exec "$PYTHON_CMD" "$SHORTCUT_SCRIPT"