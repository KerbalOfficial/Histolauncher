This directory contains the small source patch used to rebuild the two
authlib-injector classes that Histolauncher replaces inside
`src/assets/authlib-injector.jar`.

Patch purpose:

- Keep skin and cape texture downloads on Histolauncher's local
  `127.0.0.1` backend so the launcher can cache textures, apply the user's URL
  proxy, and support offline use.
- Retarget LAN peer texture URLs that contain another launcher's old localhost
  port back to the current launcher's dynamic local backend at
  `MinecraftProfileTexture.getUrl()` time.
- Retarget plain Mojang `textures.minecraft.net/texture/<hash>` URLs to
  Histolauncher's local `/texture/raw/<hash>` proxy so peer skins/capes can be
  cached and served through the same fast local path.
- Preload the active player's local session profile in a daemon thread when
  authlib-injector initializes. Histolauncher passes the UUID/name through
  `HISTOLAUNCHER_AUTHLIB_PRELOAD_UUID` and
  `HISTOLAUNCHER_AUTHLIB_PRELOAD_NAME`, which warms the launcher-side signed
  profile and texture cache before Minecraft asks during world join.
- Allow LAN peers to verify Histolauncher texture payloads even when each
  launcher instance has its own local Yggdrasil signing key. Histolauncher
  embeds the signing public key in the signed texture payload; the patched
  verifier tries that embedded key only after the normal trusted-key list
  fails.

Build from the repository root with JDK 11 or newer. Always rebuild the jar
from a clean extraction of the upstream binary instead of using `jar uf`:
incremental updates have been observed to leave the jar in a state where the
JVM cannot resolve unrelated bundled inner classes (for example
`NanoHTTPD$ClientHandler`), which silently kills the agent's local httpd
listener.

`ConstantURLTransformUnit` compiles into anonymous visitor classes such as
`ConstantURLTransformUnit$1` and `ConstantURLTransformUnit$1$1`. The overlay
step above copies every `*.class` file produced by `javac` so those nested
classes are always packaged; otherwise Minecraft logs `NoClassDefFoundError`
when authlib-injector transforms `MinecraftProfileTexture`.

The rest of authlib-injector remains the upstream binary. Upstream source is
available at https://github.com/yushijinhun/authlib-injector.