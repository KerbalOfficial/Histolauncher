#!/bin/sh

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" 2>/dev/null && pwd)
if [ -z "$SCRIPT_DIR" ]; then
    echo "Error: Could not determine the Histolauncher folder."
    exit 1
fi

cd "$SCRIPT_DIR" || exit 1

SUDO_MODE=""
PASSWD=""

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

prompt_sudo() {
    if command -v pkexec > /dev/null 2>&1; then
        SUDO_MODE="pkexec"
    elif command -v gksudo > /dev/null 2>&1; then
        SUDO_MODE="gksudo"
    elif command -v kdesudo > /dev/null 2>&1; then
        SUDO_MODE="kdesudo"
    elif command -v zenity > /dev/null 2>&1 && command -v sudo > /dev/null 2>&1; then
        PASSWD=$(zenity --password --title="sudo password required")
        if [ $? -ne 0 ] || [ -z "$PASSWD" ]; then
            echo "Error: Password prompt cancelled."
            return 1
        fi
        SUDO_MODE="sudo-stdin"
    elif command -v sudo > /dev/null 2>&1 && [ -t 0 ]; then
        SUDO_MODE="sudo"
    else
        echo "Error: sudo/pkexec is required to install Python packages."
        echo "Please install Python 3, Tkinter, venv, and pip manually."
        return 1
    fi
}

run_sudo() {
    case "$SUDO_MODE" in
        pkexec)
            pkexec "$@"
            ;;
        gksudo)
            gksudo -- "$@"
            ;;
        kdesudo)
            kdesudo -- "$@"
            ;;
        sudo-stdin)
            printf '%s\n' "$PASSWD" | sudo -S "$@"
            ;;
        sudo)
            sudo "$@"
            ;;
        *)
            return 1
            ;;
    esac
}

install_python_packages() {
    prompt_sudo || return 1

    if command -v apt-get > /dev/null 2>&1; then
        run_sudo apt-get update && \
            run_sudo apt-get install -y python3 python3-venv python3-pip python3-tk xdg-utils
    elif command -v pacman > /dev/null 2>&1; then
        run_sudo pacman -S --needed --noconfirm python python-pip tk xdg-utils
    elif command -v dnf > /dev/null 2>&1; then
        run_sudo dnf install -y python3 python3-pip python3-tkinter xdg-utils
    elif command -v zypper > /dev/null 2>&1; then
        run_sudo zypper --non-interactive install python3 python3-pip python3-tk xdg-utils
    elif command -v yum > /dev/null 2>&1; then
        run_sudo yum install -y python3 python3-pip python3-tkinter xdg-utils
    else
        echo "Error: Could not detect a supported package manager."
        echo "Please install Python 3, Tkinter, venv, and pip manually."
        return 1
    fi
}

PYTHON_CMD=$(find_python)
if [ -z "$PYTHON_CMD" ]; then
    echo "Python 3 is not installed. Attempting to install it..."
    install_python_packages || exit 1
    PYTHON_CMD=$(find_python)
fi

if [ -z "$PYTHON_CMD" ]; then
    echo "Error: Python installation failed. Please install Python 3 manually."
    exit 1
fi

if ! "$PYTHON_CMD" -c "import tkinter, venv, ensurepip" > /dev/null 2>&1; then
    echo "Python is installed, but Tkinter/venv/pip support is missing. Attempting to install it..."
    install_python_packages || true
fi

LAUNCHER_SCRIPT="$SCRIPT_DIR/launcher.pyw"
if [ ! -f "$LAUNCHER_SCRIPT" ]; then
    LAUNCHER_SCRIPT="$SCRIPT_DIR/launcher.py"
fi

if [ ! -f "$LAUNCHER_SCRIPT" ]; then
    echo "Error: Could not find launcher.pyw or launcher.py."
    exit 1
fi

exec "$PYTHON_CMD" "$LAUNCHER_SCRIPT"