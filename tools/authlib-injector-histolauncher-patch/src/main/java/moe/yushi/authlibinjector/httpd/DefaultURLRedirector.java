package moe.yushi.authlibinjector.httpd;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.net.URLEncoder;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import moe.yushi.authlibinjector.APIMetadata;
import moe.yushi.authlibinjector.transform.support.ConstantURLTransformUnit;

public class DefaultURLRedirector implements URLRedirector {

	private Map<String, String> domainMapping = new HashMap<>();
	private String apiRoot;
	private String localRoot;

	public DefaultURLRedirector(APIMetadata config) {
		warmNanoHttpdClientHandler();
		initDomainMapping();

		apiRoot = config.getApiRoot();
		localRoot = computeLocalRoot(apiRoot);
		startHistolauncherProfilePreload();
	}

	private void startHistolauncherProfilePreload() {
		final String uuid = normalizeUuid(System.getenv("HISTOLAUNCHER_AUTHLIB_PRELOAD_UUID"));
		if (uuid.isEmpty()) {
			return;
		}
		final String name = String.valueOf(System.getenv("HISTOLAUNCHER_AUTHLIB_PRELOAD_NAME") == null ? "" : System.getenv("HISTOLAUNCHER_AUTHLIB_PRELOAD_NAME")).trim();
		final String accountType = String.valueOf(System.getenv("HISTOLAUNCHER_AUTHLIB_ACCOUNT_TYPE") == null ? "" : System.getenv("HISTOLAUNCHER_AUTHLIB_ACCOUNT_TYPE")).trim();
		final String offlineUuid = "microsoft".equalsIgnoreCase(accountType) ? offlineUuidForName(name) : "";
		final String root = ensureTrailingSlash(apiRoot);
		Thread worker = new Thread(new Runnable() {
			@Override
			public void run() {
				for (int attempt = 0; attempt < 4; attempt++) {
					boolean primaryReady = preloadHistolauncherProfile(root, uuid, name);
					boolean offlineAliasReady = offlineUuid.isEmpty() || offlineUuid.equals(uuid) || preloadHistolauncherProfile(root, offlineUuid, name);
					if (primaryReady && offlineAliasReady) {
						return;
					}
					try {
						Thread.sleep(250L + (attempt * 750L));
					} catch (InterruptedException ignored) {
						return;
					}
				}
			}
		}, "Histolauncher authlib profile preloader");
		worker.setDaemon(true);
		worker.start();
	}

	private static String normalizeUuid(String value) {
		String raw = String.valueOf(value == null ? "" : value).replace("-", "").trim().toLowerCase();
		if (raw.length() != 32) {
			return "";
		}
		for (int i = 0; i < raw.length(); i++) {
			char ch = raw.charAt(i);
			if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'))) {
				return "";
			}
		}
		return raw;
	}

	private static boolean preloadHistolauncherProfile(String root, String uuid, String name) {
		HttpURLConnection connection = null;
		InputStream in = null;
		try {
			String url = root + "sessionserver/session/minecraft/profile/" + uuid + "?unsigned=false";
			if (!name.isEmpty()) {
				url += "&username=" + URLEncoder.encode(name, "UTF-8");
			}
			connection = (HttpURLConnection) new URL(url).openConnection();
			connection.setConnectTimeout(1000);
			connection.setReadTimeout(1800);
			connection.setUseCaches(false);
			connection.setRequestProperty("User-Agent", "HistolauncherAuthlibPreload/1.0");
			int code = connection.getResponseCode();
			in = code >= 200 && code < 400 ? connection.getInputStream() : connection.getErrorStream();
			StringBuilder body = new StringBuilder();
			if (in != null) {
				byte[] buffer = new byte[1024];
				while (true) {
					int read = in.read(buffer);
					if (read < 0) {
						break;
					}
					body.append(new String(buffer, 0, read, "UTF-8"));
				}
			}
			if (code >= 200 && code < 300) {
				ConstantURLTransformUnit.cacheProfileResponse(uuid, name, true, body.toString());
			}
			return code >= 200 && code < 300;
		} catch (Exception ignored) {
			return false;
		} finally {
			if (in != null) {
				try {
					in.close();
				} catch (Exception ignored) {
				}
			}
			if (connection != null) {
				connection.disconnect();
			}
		}
	}

	private static String offlineUuidForName(String name) {
		String value = String.valueOf(name == null ? "" : name).trim();
		if (value.isEmpty()) {
			return "";
		}
		try {
			byte[] digest = MessageDigest.getInstance("MD5").digest(("OfflinePlayer:" + value).getBytes("UTF-8"));
			digest[6] = (byte) ((digest[6] & 0x0F) | 0x30);
			digest[8] = (byte) ((digest[8] & 0x3F) | 0x80);
			StringBuilder out = new StringBuilder(32);
			for (byte b : digest) {
				String hex = Integer.toHexString(b & 0xFF);
				if (hex.length() == 1) {
					out.append('0');
				}
				out.append(hex);
			}
			return out.toString();
		} catch (Exception ignored) {
			return "";
		}
	}

	private static void warmNanoHttpdClientHandler() {
		try {
			Class.forName("moe.yushi.authlibinjector.internal.fi.iki.elonen.NanoHTTPD$ClientHandler");
		} catch (ClassNotFoundException ignored) {
		}
	}

	private void initDomainMapping() {
		domainMapping.put("api.mojang.com", "api");
		domainMapping.put("authserver.mojang.com", "authserver");
		domainMapping.put("sessionserver.mojang.com", "sessionserver");
		domainMapping.put("skins.minecraft.net", "skins");
		domainMapping.put("api.minecraftservices.com", "minecraftservices");
	}

	private static String computeLocalRoot(String apiRoot) {
		try {
			URI uri = new URI(apiRoot);
			String path = uri.getPath();
			if (path == null) {
				path = "";
			}
			while (path.endsWith("/") && path.length() > 1) {
				path = path.substring(0, path.length() - 1);
			}
			if (path.endsWith("/authserver")) {
				path = path.substring(0, path.length() - "/authserver".length());
			}
			if (path.length() == 0) {
				path = "/";
			} else if (!path.endsWith("/")) {
				path = path + "/";
			}

			return new URI(uri.getScheme(), uri.getAuthority(), path, null, null).toString();
		} catch (Exception ignored) {
			String value = String.valueOf(apiRoot);
			int index = value.indexOf("/authserver");
			if (index >= 0) {
				return ensureTrailingSlash(value.substring(0, index));
			}
			return ensureTrailingSlash(value);
		}
	}

	private static String ensureTrailingSlash(String value) {
		if (value.endsWith("/")) {
			return value;
		}
		return value + "/";
	}

	private static Optional<String> texturePath(String path) {
		String value = path == null ? "" : path;
		if (value.startsWith("/texture/skin/") || value.startsWith("/texture/cape/") || value.startsWith("/texture/raw/")) {
			return Optional.of(value.substring(1));
		}
		if (value.startsWith("/texture/")) {
			String textureId = value.substring("/texture/".length());
			if (!textureId.isEmpty()) {
				return Optional.of("texture/raw/" + textureId);
			}
		}
		if (value.startsWith("/skin/") || value.startsWith("/cape/")) {
			return Optional.of("texture" + value);
		}
		return Optional.empty();
	}

	private static String normalizedHost(String domain) {
		String value = String.valueOf(domain == null ? "" : domain).trim().toLowerCase();
		if (value.endsWith(".")) {
			value = value.substring(0, value.length() - 1);
		}
		if (value.startsWith("[")) {
			int end = value.indexOf(']');
			if (end > 0) {
				return value.substring(1, end);
			}
		}
		int firstColon = value.indexOf(':');
		if (firstColon >= 0 && value.indexOf(':', firstColon + 1) < 0) {
			value = value.substring(0, firstColon);
		}
		return value;
	}

	private static boolean isLoopbackDomain(String domain) {
		String host = normalizedHost(domain);
		return "127.0.0.1".equals(host)
				|| "localhost".equals(host)
				|| "::1".equals(host)
				|| "0:0:0:0:0:0:0:1".equals(host);
	}

	@Override
	public Optional<String> redirect(String domain, String path) {
		Optional<String> texturePath = texturePath(path);
		if (texturePath.isPresent()) {
			String host = normalizedHost(domain);
			if ("textures.minecraft.net".equals(host) || "textures.histolauncher.org".equals(host) || isLoopbackDomain(domain)) {
				return Optional.of(localRoot + texturePath.get());
			}
		}

		String subdirectory = domainMapping.get(domain);
		if (subdirectory == null) {
			return Optional.empty();
		}

		return Optional.of(apiRoot + subdirectory + path);
	}

}