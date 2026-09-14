authlib-injector Histolauncher patch
====================================

This directory contains the source patch used to rebuild the authlib-injector
classes that Histolauncher replaces inside `src/assets/authlib-injector.jar`,
plus the build script that produces that jar.

**Current upstream base: v1.2.8.**

Building
--------

From the repository root, with a JDK 11 or newer on `PATH`:

	python tools/authlib-injector-histolauncher-patch/build.py --download 1.2.8

or, against a jar you already have:

	python tools/authlib-injector-histolauncher-patch/build.py --upstream path/to/authlib-injector-1.2.8.jar

The script writes `src/assets/authlib-injector.jar` and verifies the result
before installing it. Classes are compiled with `--release 8` to match the
class file version upstream ships; a newer target would refuse to load on the
older JREs Histolauncher supports for legacy Minecraft versions.

The build always starts from a **clean extraction** of the upstream binary.
Never use `jar uf` to update the jar in place: incremental updates have been
observed to leave the archive in a state where the JVM cannot resolve unrelated
bundled inner classes (for example `NanoHTTPD$ClientHandler`), which silently
kills the agent's local httpd listener.

The overlay step copies **every** `*.class` file `javac` produces, not just the
top-level ones. `ConstantURLTransformUnit` alone compiles into a dozen
anonymous visitor classes (`ConstantURLTransformUnit$1`,
`ConstantURLTransformUnit$1$1`, ...); if any of them is left out, Minecraft
logs `NoClassDefFoundError` when authlib-injector transforms
`MinecraftProfileTexture`. Note that the exact number of anonymous classes
depends on the JDK used to compile, so do not hard-code the list.

Patched classes
---------------

Everything not listed here is the upstream binary, untouched.

### `httpd/DefaultURLRedirector`

- Keep skin and cape texture downloads on Histolauncher's local `127.0.0.1`
  backend so the launcher can cache textures, apply the user's URL proxy, and
  support offline use.
- Retarget LAN peer texture URLs that contain another launcher's old localhost
  port back to the current launcher's dynamic local backend at
  `MinecraftProfileTexture.getUrl()` time.
- Retarget plain Mojang `textures.minecraft.net/texture/<hash>` URLs to
  Histolauncher's local `/texture/raw/<hash>` proxy so peer skins and capes can
  be cached and served through the same fast local path.
- Preload the active player's local session profile in a daemon thread when
  authlib-injector initializes. Histolauncher passes the UUID/name through
  `HISTOLAUNCHER_AUTHLIB_PRELOAD_UUID` and `HISTOLAUNCHER_AUTHLIB_PRELOAD_NAME`,
  which warms the launcher-side signed profile and texture cache before
  Minecraft asks during world join.

### `transform/support/ConstantURLTransformUnit`

- Rewrite `MinecraftProfileTexture.getUrl()` results through the local texture
  proxy.
- Short-circuit session service profile and texture lookups (`getTextures`,
  `getPackedTextures`, `fetchProfile`, `fillGameProfile` /
  `fillProfileProperties`) against a launcher-side cache, so world join does
  not block on the network.

  `getPackedTextures` is also what makes skins work on **offline-mode servers**:
  those send player profiles with no `textures` property at all, and the hook
  synthesises one from the launcher for any profile carrying an offline UUID
  (`shouldHandleLocalProfileTextures`). Without it every player on an offline
  server renders with the default skin.

  Two class layouts are matched, because Minecraft 26.3 / authlib 10 deleted the
  whole `com.mojang.authlib.yggdrasil` package:

  | Minecraft | authlib | session service |
  |---|---|---|
  | 26.2 and older | 9 and older | `com.mojang.authlib.yggdrasil.YggdrasilMinecraftSessionService` |
  | 26.3 and newer | 10+ | `com.mojang.authlib.services.MinecraftServicesSessionService` |

  `getPackedTextures` has the same descriptor in both; only `ProfileResult`
  moved package, which is why the `fetchProfile` descriptor and its `CHECKCAST`
  are built from `profileResultType`.
- Hook `TitleScreen` and the F3 client-brand line to show the Histolauncher
  build label.

### `transform/support/YggdrasilKeyTransformUnit`

- Allow LAN peers to display Histolauncher texture payloads even though each
  launcher instance signs with its own local Yggdrasil key: the patched
  verifier accepts a property named `textures` without checking its signature
  against the trusted-key list. This is what lets Histolauncher skins and
  Mojang skins render side by side in the same world.
- Reject empty signatures, and verify payload bytes as UTF-8 instead of the
  platform default charset.

### `transform/support/AccountTypeTransformer`

- Keep `--userType mojang` on Minecraft 1.12 and older. Upstream unconditionally
  rewrites it to `msa`, which breaks legacy session authentication on the old
  versions Histolauncher targets.

### `transform/support/AuthServerNameInjector`

- Append the Histolauncher brand to the title screen and F3 version line.

Rebasing onto a new upstream release
------------------------------------

1. Diff the upstream sources between the old and new tags and check whether any
   of the five files above changed:

		diff -r authlib-injector-<old>/src authlib-injector-<new>/src

2. Merge any upstream change into the corresponding file here, and update the
   "Modified by the Histolauncher project" note in its header.
3. Check whether the new release adds a `URLFilter`. Filters take precedence
   over `URLRedirector` in `URLProcessor.transform`, so a filter that claims a
   domain `DefaultURLRedirector` also handles would silently take that domain
   away from the Histolauncher texture proxy.
4. Rebuild, then confirm the patched classes decompile to the same logic as
   before plus your intended change. Any decompiler works; CFR was used for the
   1.2.7 -> 1.2.8 rebase.

Checking against a new Minecraft version
----------------------------------------

Independently of upstream releases, every class and method this patch names is
matched by **exact string**. When Mojang renames or moves one, the hook becomes
a silent no-op: nothing throws, nothing is logged, the feature just stops
working. That is exactly how offline-server skins broke on Minecraft 26.3 --
authlib 10 deleted `com.mojang.authlib.yggdrasil` wholesale, so every hook in
`ConstantURLTransformUnit` stopped matching while the launcher looked healthy.

So when a new Minecraft version ships, check the names against its bundled
`authlib-*.jar` before assuming the launcher still works:

	javap -p -cp authlib-<version>.jar com.mojang.authlib.services.MinecraftServicesSessionService
	javap -p -cp authlib-<version>.jar com.mojang.authlib.minecraft.MinecraftProfileTexture

Running the game with `-Dauthlibinjector.debug` lists every class the agent
actually transformed. If `…SessionService` is missing from that list, the
profile and texture hooks are not running.

Upstream source is available at
https://github.com/yushijinhun/authlib-injector.

Licensing
---------

authlib-injector is AGPL-3.0-or-later with the "AUTHLIB-INJECTOR" exception.
The files here are modified versions of AGPL sources and carry the upstream
copyright header plus a notice of what Histolauncher changed, as AGPL section 5
requires. See `src/assets/authlib-injector.LICENSE` for the full picture,
including why the modified jar is not covered by the exception's "unaltered
binary" clause.
