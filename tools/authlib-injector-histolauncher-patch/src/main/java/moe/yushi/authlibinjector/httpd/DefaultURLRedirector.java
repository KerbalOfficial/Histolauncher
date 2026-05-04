package moe.yushi.authlibinjector.httpd;

import java.net.URI;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import moe.yushi.authlibinjector.APIMetadata;

public class DefaultURLRedirector implements URLRedirector {

	private Map<String, String> domainMapping = new HashMap<>();
	private String apiRoot;
	private String localRoot;

	public DefaultURLRedirector(APIMetadata config) {
		warmNanoHttpdClientHandler();
		initDomainMapping();

		apiRoot = config.getApiRoot();
		localRoot = computeLocalRoot(apiRoot);
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
		if (value.startsWith("/texture/skin/") || value.startsWith("/texture/cape/")) {
			return Optional.of(value.substring(1));
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
			if ("textures.minecraft.net".equals(host) || isLoopbackDomain(domain)) {
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