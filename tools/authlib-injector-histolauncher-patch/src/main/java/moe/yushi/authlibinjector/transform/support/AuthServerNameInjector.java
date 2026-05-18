package moe.yushi.authlibinjector.transform.support;

import java.util.Locale;
import java.util.Map;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import moe.yushi.authlibinjector.APIMetadata;
import moe.yushi.authlibinjector.transform.CallbackMethod;
import moe.yushi.authlibinjector.util.Logging;
import moe.yushi.authlibinjector.util.Logging.Level;

public final class AuthServerNameInjector {

	private static final Pattern SNAPSHOT_VERSION_PATTERN = Pattern.compile("^(\\d{2})w\\d{2}[a-z]$");
	private static volatile String activeServerName;

	private AuthServerNameInjector() {
	}

	private static String getServerName(APIMetadata metadata) {
		Map<String, Object> metadataMap = metadata.getMeta();
		Object serverName = metadataMap.get("serverName");
		if (serverName instanceof String) {
			return (String) serverName;
		}
		return metadata.getApiRoot();
	}

	public static void init(final APIMetadata metadata) {
		activeServerName = getServerName(metadata);
		MainArgumentsTransformer.getArgumentsListeners().add(new Function<String[], String[]>() {
			@Override
			public String[] apply(String[] arguments) {
				return rewriteArguments(metadata, arguments);
			}
		});
	}

	private static String[] rewriteArguments(APIMetadata metadata, String[] arguments) {
		if (arguments == null) {
			return null;
		}

		String serverName = getServerName(metadata);
		activeServerName = serverName;
		for (int argumentIndex = 0; argumentIndex < arguments.length; argumentIndex++) {
			String argument = arguments[argumentIndex];
			if (argument == null) {
				continue;
			}

			if ("--versionType".equals(argument) && argumentIndex < arguments.length - 1) {
				Logging.log(Level.DEBUG, "Setting versionType to server name: " + serverName);
				arguments[argumentIndex + 1] = serverName;
				continue;
			}

			if (argument.startsWith("--versionType=")) {
				Logging.log(Level.DEBUG, "Setting versionType to server name: " + serverName);
				arguments[argumentIndex] = "--versionType=" + serverName;
				continue;
			}

		}

		return arguments;
	}

	@CallbackMethod
	public static String appendTitleScreenBrand(String titleText) {
		String serverName = activeServerName;
		if (titleText == null || serverName == null || serverName.trim().isEmpty()) {
			return titleText;
		}
		if (titleText.contains("/" + serverName) || titleText.contains(serverName)) {
			return titleText;
		}

		String prefix = "Minecraft ";
		if (!titleText.startsWith(prefix)) {
			return titleText;
		}

		int versionStart = prefix.length();
		int versionEnd = versionStart;
		while (versionEnd < titleText.length() && !Character.isWhitespace(titleText.charAt(versionEnd))) {
			versionEnd++;
		}

		String versionName = titleText.substring(versionStart, versionEnd);
		if (!isVersionName26Point1OrNewer(versionName)) {
			return titleText;
		}

		String brandedTitleText = titleText.substring(0, versionEnd) + "/" + serverName + titleText.substring(versionEnd);
		if (!stringEquals(brandedTitleText, titleText)) {
			Logging.log(Level.DEBUG, "Setting title screen version to server name: " + brandedTitleText);
		}
		return brandedTitleText;
	}

	@CallbackMethod
	public static String appendDebugClientBrand(String clientBrand) {
		String serverName = activeServerName;
		if (clientBrand == null || serverName == null || serverName.trim().isEmpty()) {
			return clientBrand;
		}
		if (!shouldAppendDebugClientBrand()) {
			return clientBrand;
		}
		if (clientBrand.contains("/" + serverName) || clientBrand.contains(serverName)) {
			return clientBrand;
		}
		String brandedClientBrand = clientBrand + "/" + serverName;
		Logging.log(Level.DEBUG, "Setting debug client brand to server name: " + brandedClientBrand);
		return brandedClientBrand;
	}

	private static boolean shouldAppendDebugClientBrand() {
		String versionName = detectCurrentMinecraftVersionName();
		if (versionName.isEmpty()) {
			return false;
		}
		return isVersionName1Point17OrNewer(versionName) || isVersionName26Point1OrNewer(versionName);
	}

	private static String detectCurrentMinecraftVersionName() {
		String activeVersionIdentifier = String.valueOf(System.getenv("HISTOLAUNCHER_ACTIVE_VERSION_IDENTIFIER") == null ? "" : System.getenv("HISTOLAUNCHER_ACTIVE_VERSION_IDENTIFIER")).trim();
		if (!activeVersionIdentifier.isEmpty()) {
			return activeVersionIdentifier;
		}

		try {
			Class<?> sharedConstantsClass = Class.forName("net.minecraft.SharedConstants");
			Object currentVersion = sharedConstantsClass.getMethod("getCurrentVersion").invoke(null);
			String name = invokeString(currentVersion, "name");
			if (!name.isEmpty()) {
				return name;
			}
			return invokeString(currentVersion, "getName");
		} catch (Throwable ignored) {
			return "";
		}
	}

	private static String invokeString(Object target, String methodName) {
		if (target == null) {
			return "";
		}
		try {
			Object value = target.getClass().getMethod(methodName).invoke(target);
			return value instanceof String ? ((String) value).trim() : "";
		} catch (Throwable ignored) {
			return "";
		}
	}

	private static boolean isVersionName26Point1OrNewer(String versionName) {
		int[] parts = parseVersionParts(versionName);
		if (parts.length >= 2 && (parts[0] > 26 || (parts[0] == 26 && parts[1] >= 1))) {
			return true;
		}

		String normalizedVersion = normalizeComparableVersionName(versionName);
		Matcher snapshotMatcher = SNAPSHOT_VERSION_PATTERN.matcher(normalizedVersion.toLowerCase(Locale.ROOT));
		return snapshotMatcher.matches() && parseInteger(snapshotMatcher.group(1), 0) >= 26;
	}

	private static boolean isVersionName1Point17OrNewer(String versionName) {
		int[] parts = parseVersionParts(versionName);
		if (parts.length < 2) {
			return false;
		}
		return parts[0] > 1 || (parts[0] == 1 && parts[1] >= 17);
	}

	private static int[] parseVersionParts(String versionName) {
		String normalizedVersion = normalizeComparableVersionName(versionName);
		if (normalizedVersion.isEmpty()) {
			return new int[0];
		}

		String[] rawParts = normalizedVersion.split("\\.");
		int[] parts = new int[Math.min(rawParts.length, 3)];
		for (int i = 0; i < parts.length; i++) {
			parts[i] = parseInteger(rawParts[i], -1);
			if (parts[i] < 0) {
				return new int[0];
			}
		}
		return parts;
	}

	private static String normalizeComparableVersionName(String versionName) {
		String normalizedVersion = String.valueOf(versionName).trim().replace('\\', '/');
		if (normalizedVersion.isEmpty()) {
			return "";
		}

		int slashIndex = normalizedVersion.lastIndexOf('/');
		if (slashIndex >= 0) {
			String tail = normalizedVersion.substring(slashIndex + 1);
			if (looksLikeVersionName(tail)) {
				normalizedVersion = tail;
			} else {
				normalizedVersion = normalizedVersion.substring(0, slashIndex);
			}
		}

		int dashIndex = normalizedVersion.indexOf('-');
		if (dashIndex >= 0) {
			normalizedVersion = normalizedVersion.substring(0, dashIndex);
		}
		return normalizedVersion;
	}

	private static boolean looksLikeVersionName(String value) {
		String text = String.valueOf(value == null ? "" : value).trim();
		return !text.isEmpty() && Character.isDigit(text.charAt(0));
	}

	private static int parseInteger(String value, int fallback) {
		try {
			return Integer.parseInt(value);
		} catch (NumberFormatException ignored) {
			return fallback;
		}
	}

	private static boolean stringEquals(String first, String second) {
		return first == null ? second == null : first.equals(second);
	}
}