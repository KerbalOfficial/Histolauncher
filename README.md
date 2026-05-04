# Histolauncher
A lightweight, open-source Minecraft launcher built for players who want access to every version — from the latest release to the oldest archive — with a clean, modern interface.

Join the Discord Server: **https://discord.gg/P8dddrXFkn**

Official Website: **https://histolauncher.org**
Backup Website: **https://histolauncher.pages.dev**

---

## Features

### Versions
- Browse and install **all official Mojang releases** (releases, snapshots, beta, and alpha)
- Install **legacy clients via Omniarchive** (rare and archived builds)
- Per-version **display name, custom image, and storage directory** overrides
- Import/export versions as `.zip` archives (with loaders, assets, and config)
- Favorite versions and filter/search by category

### Mod Loaders
- Install and manage **Fabric, NeoForge, Forge, Quilt, Babric, and ModLoader (Risugami)**
- Multiple loader versions per Minecraft version; upgrade or remove individually

### Add-ons (Mods, Modpacks, Resource Packs, Shader Packs)
- Search and install from **Modrinth** and **CurseForge**
- Import local `.jar`, `.zip`, and archive files
- Enable/disable individual add-ons without deleting them
- Move mods between loader categories
- Bulk select, delete, and move
- Import and Export modpacks as **Histolauncher `.hlmp`**, **Modrinth `.mrpack`**, or **CurseForge `.zip`**

### World Manager
- Browse installed worlds across storage directories
- Edit world NBT data (simple form + raw JSON tree editor)
- Import/export worlds as `.zip` archives
- Download worlds from CurseForge
- Edit game mode, difficulty, game rules, player stats, inventory, and position

### Account types
- **Offline/local** accounts
- **Histolauncher** accounts (with skin/cape management on histolauncher.org)
- **Microsoft/Xbox** accounts via device-code login

### Java
- Auto-detect installed Java runtimes across the system
- One-click **Java download and install** from within the launcher (JRE 8, JDK 11/16/17/21/25)
- Auto-select the right Java version per Minecraft version
- Override Java path per version or globally

### Profiles
- Separate **settings profiles** (account, settings) with rename/delete
- Separate **version profiles** and **add-on profiles** for scoped setups

### Launch & Crash Tools
- Launch with loader selection prompt when multiple loaders are installed
- Automatic crash-log analysis (Java mismatch, OOM, mod errors, missing resources, etc.)
- Open crash logs directly from the crash dialog
- Clear old logs to free disk space
- **Discord Rich Presence** during launcher use and gameplay

### Diagnostics & Support
- Generate a full **diagnostics report** from Settings (platform, Java, disk, paths, settings, versions, add-ons, recent logs)
- Copy report to clipboard or save to file for fast support

### Customization
- 14 **color themes** (dark/light variants)
- UI size (small → extra-large), layout density, compact sidebar
- Multi-language with **RTL support**; locale files
- Optional background image, reduced animations mode
- Desktop notifications, URL proxy for restricted networks, low-data mode

---

# Requirements
You will need:
- **Java** for the clients *(only **1** java required!)*:
  - **JRE 8** - used by versions **oldest - 1.16.5**
  - **JDK 16** - used by versions **1.17 - 1.17.1**
  - **JDK 17** - used by versions **1.18 - 1.20.4**
  - **JDK 21** - used by versions **1.20.5 - 1.21.11**
  - **JDK 25** *(recommended)* - used by versions **26.1 - latest**
- **Python 3.x** for the launcher

## How to install:
### Java (8, 11, 16, 17, 21, 25):
1. Go to the download page:
  - JRE 8 (**oldest - 1.16.5**): **https://adoptium.net/en-GB/temurin/releases?version=8**
  - JDK 11 (**Mods & Tools**): **https://adoptium.net/en-GB/temurin/releases?version=11**
  - JDK 16 (**1.17 - 1.17.1**): **https://adoptium.net/en-GB/temurin/releases?version=16**
  - JDK 17 (**1.18 - 1.20.4**): **https://adoptium.net/en-GB/temurin/releases?version=17**
  - JDK 21 (**1.20.5 - 1.21.11**): **https://adoptium.net/en-GB/temurin/releases?version=21**
  - JDK 25 (*recommended*, **26.1 - latest**): **https://adoptium.net/en-GB/temurin/releases?version=25**
2. Find your operating system (Windows, macOS, or Linux).
3. Select the correct architecture (64‑bit for most modern systems).
4. Download the installer.
5. Run the installer and follow the on‑screen steps.
6. Done! The clients should load once you try to launch them!

### Python 3.x:
- METHOD 1:
  1. Download from **https://www.python.org/downloads/**
  2. Click on the latest release (should be a bugfix or security patch, pre-releases are probably not recommended)
  3. Click on the OS your computer is using
  4. Follow the instructions the installer tells you
  5. Done! The launcher should load once you try to open it!
- METHOD 2:
  1. For **Windows**, install it using the 'Microsoft store' version *(Python 3.13)*: **https://apps.microsoft.com/detail/9pnrbtzxmb4z**

# Opening the Launcher
To open the launcher, download the latest release from the **[release page](https://github.com/KerbalOfficial/Histolauncher/releases)**. After it installs, unzip the `.zip` (or `.tar.gz` for Linux) file. Then, make sure you have the requirements *(instructions for installing them are above)*. After that, run `launcher.pyw` (`launcher.sh` for Linux) which will start the launcher.

Enjoy!