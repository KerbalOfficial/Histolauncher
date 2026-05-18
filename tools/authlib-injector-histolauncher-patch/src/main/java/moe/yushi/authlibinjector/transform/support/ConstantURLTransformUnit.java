package moe.yushi.authlibinjector.transform.support;

import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.ARETURN;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.ASM9;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.ALOAD;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.ASTORE;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.CHECKCAST;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.DUP;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.F_SAME1;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.IFNULL;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.ILOAD;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.INVOKESTATIC;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.POP;

import java.io.InputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.Collection;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import moe.yushi.authlibinjector.httpd.URLProcessor;
import moe.yushi.authlibinjector.internal.org.objectweb.asm.ClassVisitor;
import moe.yushi.authlibinjector.internal.org.objectweb.asm.Label;
import moe.yushi.authlibinjector.internal.org.objectweb.asm.MethodVisitor;
import moe.yushi.authlibinjector.transform.CallbackMethod;
import moe.yushi.authlibinjector.transform.LdcTransformUnit;
import moe.yushi.authlibinjector.transform.TransformContext;

public class ConstantURLTransformUnit extends LdcTransformUnit {

	private URLProcessor urlProcessor;
	private static volatile URLProcessor textureUrlProcessor;
	private static final int PROFILE_SYNC_TIMEOUT_MS = 850;
	private static final int PROFILE_ASYNC_TIMEOUT_MS = 4500;
	private static final Map<String, String> PROFILE_JSON_CACHE = new ConcurrentHashMap<>();
	private static final Map<String, Object> PROFILE_OBJECT_CACHE = new ConcurrentHashMap<>();
	private static final Map<String, Boolean> PROFILE_REFRESH_INFLIGHT = new ConcurrentHashMap<>();
	private static final Pattern TEXTURES_PROPERTY_PATTERN = Pattern.compile("\\{[^{}]*\\\"name\\\"\\s*:\\s*\\\"textures\\\"[^{}]*\\}");
	private static final String PRELOADED_PROFILE_UUID = System.getenv("HISTOLAUNCHER_AUTHLIB_PRELOAD_UUID");
	private static final String PRELOADED_PROFILE_NAME = System.getenv("HISTOLAUNCHER_AUTHLIB_PRELOAD_NAME");
	private static final String PRELOADED_ACCOUNT_TYPE = System.getenv("HISTOLAUNCHER_AUTHLIB_ACCOUNT_TYPE");
	private static final String PRELOADED_OFFLINE_UUID = offlineUuidForName(PRELOADED_PROFILE_NAME);
	private static final String DEBUG_VERSION_LINE_RECIPE_PREFIX = "Minecraft \u0001 (";

	public ConstantURLTransformUnit(URLProcessor urlProcessor) {
		this.urlProcessor = urlProcessor;
		textureUrlProcessor = urlProcessor;
	}

	@Override
	protected Optional<String> transformLdc(String input) {
		return urlProcessor.transformURL(input);
	}

	@CallbackMethod
	public static String transformTextureUrl(String input) {
		URLProcessor processor = textureUrlProcessor;
		if (processor == null || input == null) {
			return input;
		}
		return processor.transformURL(input).orElse(input);
	}

	public static void cacheProfileResponse(String uuid, String name, boolean requireSecure, String json) {
		String key = profileCacheKey(uuid, name, requireSecure);
		if (!key.isEmpty() && json != null && json.indexOf("\"properties\"") >= 0) {
			PROFILE_JSON_CACHE.put(key, json);
		}
	}

	@CallbackMethod
	public static Object ensureProfileTextures(Object sessionService, Object profile, boolean requireSecure) {
		if (profile == null) {
			return null;
		}
		try {
			if (profileHasTextures(profile)) {
				return profile;
			}
		} catch (Throwable ignored) {
		}

		String uuid = normalizeUuid(invokeString(profile, "getId"));
		if (uuid.isEmpty()) {
			return null;
		}

		String name = invokeString(profile, "getName");
		if (name == null || name.trim().isEmpty()) {
			String preloadName = String.valueOf(PRELOADED_PROFILE_NAME == null ? "" : PRELOADED_PROFILE_NAME).trim();
			if (matchesActiveProfileUuid(uuid, preloadName) && !preloadName.isEmpty()) {
				name = preloadName;
			} else {
				return null;
			}
		}

		if (!shouldHandleLocalProfileTextures(uuid, name)) {
			return null;
		}

		String json = getCachedProfileJson(uuid, name, requireSecure);
		String profileUrl = buildProfileUrl(sessionService, uuid, name, requireSecure);
		if (json == null && profileUrl != null) {
			json = fetchProfileJson(profileUrl, PROFILE_SYNC_TIMEOUT_MS);
			cacheProfileResponse(uuid, name, requireSecure, json);
		}

		Object filled = applyProfileJson(profile, json, requireSecure);
		if (filled != null && profileHasTexturesSafe(filled)) {
			return filled;
		}

		Object lazy = applyLazyLocalSkin(profile, uuid, name);
		return lazy != null && profileHasTexturesSafe(lazy) ? lazy : null;
	}

	@CallbackMethod
	public static Object getPackedTexturesFast(Object sessionService, Object profile) {
		if (profile == null) {
			return null;
		}

		try {
			if (profileHasTextures(profile)) {
				return null;
			}
		} catch (Throwable ignored) {
		}

		String uuid = normalizeUuid(invokeString(profile, "getId"));
		if (uuid.isEmpty()) {
			return null;
		}

		String name = invokeString(profile, "getName");
		if (name == null || name.isEmpty()) {
			String preloadName = String.valueOf(PRELOADED_PROFILE_NAME == null ? "" : PRELOADED_PROFILE_NAME).trim();
			if (matchesActiveProfileUuid(uuid, preloadName) && !preloadName.isEmpty()) {
				name = preloadName;
			}
		}
		if (!shouldHandleLocalProfileTextures(uuid, name)) {
			return null;
		}

		ClassLoader loader = sessionService.getClass().getClassLoader();
		String json = getCachedProfileJson(uuid, name, true);
		if (json == null) {
			String profileUrl = buildProfileUrl(sessionService, uuid, name, true);
			if (profileUrl != null) {
				json = fetchProfileJson(profileUrl, PROFILE_SYNC_TIMEOUT_MS);
				cacheProfileResponse(uuid, name, true, json);
			}
		}
		Object property = createTexturePropertyFromJson(loader, json);
		if (property != null) {
			return property;
		}

		return createLocalTextureProperty(loader, uuid, textureUuidForProfile(uuid, name), name, true);
	}

	@CallbackMethod
	public static Object fetchProfileFast(Object sessionService, Object uuid, boolean requireSecure) {
		if (uuid == null) {
			return null;
		}

		String uuidStr = uuid.toString();
		String normalizedUuid = normalizeUuid(uuidStr);
		if (normalizedUuid.isEmpty() || !isOfflineUuid(normalizedUuid)) {
			return null;
		}

		String name = (matchesActiveProfileUuid(normalizedUuid, PRELOADED_PROFILE_NAME) && PRELOADED_PROFILE_NAME != null && !PRELOADED_PROFILE_NAME.isEmpty())
				? PRELOADED_PROFILE_NAME : "";

		String key = profileCacheKey(normalizedUuid, name, requireSecure);

		Object cached = PROFILE_OBJECT_CACHE.get(key);
		if (cached != null) {
			return cached;
		}

		ClassLoader loader = sessionService.getClass().getClassLoader();

		String json = getCachedProfileJson(normalizedUuid, name, requireSecure);
		if (json == null) {
			String profileUrl = buildProfileUrl(sessionService, normalizedUuid, name, requireSecure);
			if (profileUrl != null) {
				json = fetchProfileJson(profileUrl, PROFILE_SYNC_TIMEOUT_MS);
				cacheProfileResponse(normalizedUuid, name, requireSecure, json);
			}
		}

		if (json != null) {
			String skinName = name.isEmpty() ? "Player" : name;
			Object profile = createGameProfileForUuid(uuid, skinName, loader);
			if (profile != null) {
				Object filled = applyProfileJson(profile, json, requireSecure);
				if (filled != null && profileHasTexturesSafe(filled)) {
					Object result = wrapInProfileResult(filled, loader);
					if (result != null) {
						if (!key.isEmpty()) PROFILE_OBJECT_CACHE.put(key, result);
						return result;
					}
				}
			}
		}

		String skinName = name.isEmpty() ? "Player" : name;
		Object profile = createGameProfileForUuid(uuid, skinName, loader);
		if (profile != null) {
			Object lazy = applyLazyLocalSkin(profile, normalizedUuid, skinName);
			if (lazy != null && profileHasTexturesSafe(lazy)) {
				Object result = wrapInProfileResult(lazy, loader);
				if (result != null) {
					if (!key.isEmpty()) PROFILE_OBJECT_CACHE.put(key, result);
					scheduleProfileRefresh(sessionService, normalizedUuid, name, requireSecure, key);
					return result;
				}
			}
		}

		scheduleProfileRefresh(sessionService, normalizedUuid, name, requireSecure, key);
		return null;
	}

	private static boolean isOfflineUuid(String normalizedUuid) {
		return normalizedUuid.length() == 32 && normalizedUuid.charAt(12) == '3';
	}

	private static boolean isMicrosoftAccount() {
		return "microsoft".equalsIgnoreCase(String.valueOf(PRELOADED_ACCOUNT_TYPE == null ? "" : PRELOADED_ACCOUNT_TYPE).trim());
	}

	private static boolean matchesActiveProfileUuid(String uuid, String name) {
		String normalizedUuid = normalizeUuid(uuid);
		String preloadUuidNorm = normalizeUuid(PRELOADED_PROFILE_UUID == null ? "" : PRELOADED_PROFILE_UUID);
		if (!normalizedUuid.isEmpty() && !preloadUuidNorm.isEmpty() && preloadUuidNorm.equals(normalizedUuid)) {
			return true;
		}
		if (!isMicrosoftAccount()) {
			return false;
		}
		String offlineUuid = normalizeUuid(PRELOADED_OFFLINE_UUID);
		if (offlineUuid.isEmpty() || !offlineUuid.equals(normalizedUuid)) {
			return false;
		}
		String preloadName = String.valueOf(PRELOADED_PROFILE_NAME == null ? "" : PRELOADED_PROFILE_NAME).trim();
		String profileName = String.valueOf(name == null ? "" : name).trim();
		return profileName.isEmpty() || preloadName.isEmpty() || preloadName.equalsIgnoreCase(profileName);
	}

	private static boolean shouldHandleLocalProfileTextures(String uuid, String name) {
		String normalizedUuid = normalizeUuid(uuid);
		if (normalizedUuid.isEmpty()) {
			return false;
		}
		if (matchesActiveProfileUuid(normalizedUuid, name)) {
			return true;
		}
		return isOfflineUuid(normalizedUuid) && name != null && !name.trim().isEmpty();
	}

	private static String textureUuidForProfile(String uuid, String name) {
		String normalizedUuid = normalizeUuid(uuid);
		String preloadUuidNorm = normalizeUuid(PRELOADED_PROFILE_UUID == null ? "" : PRELOADED_PROFILE_UUID);
		String offlineUuid = normalizeUuid(PRELOADED_OFFLINE_UUID);
		if (isMicrosoftAccount() && !preloadUuidNorm.isEmpty() && !offlineUuid.isEmpty() && offlineUuid.equals(normalizedUuid)) {
			String preloadName = String.valueOf(PRELOADED_PROFILE_NAME == null ? "" : PRELOADED_PROFILE_NAME).trim();
			String profileName = String.valueOf(name == null ? "" : name).trim();
			if (profileName.isEmpty() || preloadName.isEmpty() || preloadName.equalsIgnoreCase(profileName)) {
				return preloadUuidNorm;
			}
		}
		return normalizedUuid;
	}

	private static String offlineUuidForName(String name) {
		String value = String.valueOf(name == null ? "" : name).trim();
		if (value.isEmpty()) {
			return "";
		}
		try {
			byte[] digest = MessageDigest.getInstance("MD5").digest(("OfflinePlayer:" + value).getBytes(StandardCharsets.UTF_8));
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
		} catch (Throwable ignored) {
			return "";
		}
	}

	private static Object createGameProfileForUuid(Object uuid, String name, ClassLoader loader) {
		try {
			Class<?> gameProfileClass = Class.forName("com.mojang.authlib.GameProfile", false, loader);
			Constructor<?> ctor = gameProfileClass.getConstructor(UUID.class, String.class);
			return ctor.newInstance((UUID) uuid, name);
		} catch (Throwable ignored) {
			return null;
		}
	}

	private static Object wrapInProfileResult(Object profile, ClassLoader loader) {
		try {
			Class<?> gameProfileClass = Class.forName("com.mojang.authlib.GameProfile", false, loader);
			Class<?> profileResultClass = Class.forName("com.mojang.authlib.yggdrasil.ProfileResult", false, loader);
			Constructor<?> ctor = profileResultClass.getConstructor(gameProfileClass);
			return ctor.newInstance(profile);
		} catch (Throwable ignored) {
			return null;
		}
	}

	@CallbackMethod
	public static Object fillGameProfileFast(Object sessionService, Object profile, boolean requireSecure) {
		if (profile == null) {
			return null;
		}

		try {
			if (profileHasTextures(profile)) {
				return profile;
			}
		} catch (Throwable ignored) {
		}

		String uuid = normalizeUuid(invokeString(profile, "getId"));
		if (uuid.isEmpty()) {
			return null;
		}

		String name = invokeString(profile, "getName");
		String key = profileCacheKey(uuid, name, requireSecure);
		Object cachedProfile = PROFILE_OBJECT_CACHE.get(key);
		if (cachedProfile != null) {
			return cachedProfile;
		}

		String json = getCachedProfileJson(uuid, name, requireSecure);
		String profileUrl = buildProfileUrl(sessionService, uuid, name, requireSecure);
		if (json == null && profileUrl != null) {
			json = fetchProfileJson(profileUrl, PROFILE_SYNC_TIMEOUT_MS);
			cacheProfileResponse(uuid, name, requireSecure, json);
		}

		Object filled = applyProfileJson(profile, json, requireSecure);
		if (filled != null && profileHasTexturesSafe(filled)) {
			PROFILE_OBJECT_CACHE.put(key, filled);
			return filled;
		}

		Object lazy = applyLazyLocalSkin(profile, uuid, name);
		if (lazy != null && profileHasTexturesSafe(lazy)) {
			PROFILE_OBJECT_CACHE.put(key, lazy);
			scheduleProfileRefresh(sessionService, uuid, name, requireSecure, key);
			return lazy;
		}

		scheduleProfileRefresh(sessionService, uuid, name, requireSecure, key);
		return null;
	}

	private static void scheduleProfileRefresh(final Object sessionService, final String uuid, final String name, final boolean requireSecure, final String key) {
		if (key.isEmpty() || PROFILE_REFRESH_INFLIGHT.putIfAbsent(key, Boolean.TRUE) != null) {
			return;
		}
		Thread worker = new Thread(new Runnable() {
			@Override
			public void run() {
				try {
					String profileUrl = buildProfileUrl(sessionService, uuid, name, requireSecure);
					String json = fetchProfileJson(profileUrl, PROFILE_ASYNC_TIMEOUT_MS);
					cacheProfileResponse(uuid, name, requireSecure, json);
				} finally {
					PROFILE_REFRESH_INFLIGHT.remove(key);
				}
			}
		}, "Histolauncher authlib profile cache refresh");
		worker.setDaemon(true);
		worker.start();
	}

	private static String getCachedProfileJson(String uuid, String name, boolean requireSecure) {
		String exact = PROFILE_JSON_CACHE.get(profileCacheKey(uuid, name, requireSecure));
		if (exact != null) {
			return exact;
		}
		if (!requireSecure) {
			return PROFILE_JSON_CACHE.get(profileCacheKey(uuid, name, true));
		}
		return null;
	}

	private static Object applyProfileJson(Object profile, String json, boolean requireSecure) {
		if (json == null || json.trim().isEmpty()) {
			return null;
		}
		Object property = createTexturePropertyFromJson(profile.getClass().getClassLoader(), json);
		if (property == null) {
			return null;
		}
		return addTextureProperty(profile, property);
	}

	private static Object applyLazyLocalSkin(Object profile, String uuid, String name) {
		String textureUuid = textureUuidForProfile(uuid, name);
		String payload = buildLocalTexturesPayload(uuid, textureUuid, name, true);
		if (payload == null) {
			return null;
		}
		String encoded = Base64.getEncoder().encodeToString(payload.getBytes(StandardCharsets.UTF_8));
		return addTextureProperty(profile, encoded, null);
	}

	private static Object createTexturePropertyFromJson(ClassLoader loader, String json) {
		if (json == null || json.trim().isEmpty()) {
			return null;
		}
		String value = null;
		String signature = null;
		Matcher matcher = TEXTURES_PROPERTY_PATTERN.matcher(json);
		while (matcher.find()) {
			String objectJson = matcher.group();
			value = jsonString(objectJson, "value");
			signature = jsonString(objectJson, "signature");
			if (value != null && !value.isEmpty()) {
				break;
			}
		}
		if (value == null || value.isEmpty()) {
			return null;
		}
		return createTextureProperty(loader, value, signature);
	}

	private static Object createLocalTextureProperty(ClassLoader loader, String profileUuid, String textureUuid, String name, boolean includeCape) {
		String payload = buildLocalTexturesPayload(profileUuid, textureUuid, name, includeCape);
		if (payload == null) {
			return null;
		}
		String encoded = Base64.getEncoder().encodeToString(payload.getBytes(StandardCharsets.UTF_8));
		return createTextureProperty(loader, encoded, "AA==");
	}

	private static String buildLocalTexturesPayload(String profileUuid, String textureUuid, String name, boolean includeCape) {
		String port = String.valueOf(System.getenv("HISTOLAUNCHER_PORT") == null ? "" : System.getenv("HISTOLAUNCHER_PORT")).trim();
		if (port.isEmpty()) {
			return null;
		}
		String normalizedProfileUuid = normalizeUuid(profileUuid);
		String normalizedTextureUuid = normalizeUuid(textureUuid);
		if (normalizedProfileUuid.isEmpty() || normalizedTextureUuid.isEmpty()) {
			return null;
		}
		String dashedTextureUuid = dashedUuid(normalizedTextureUuid);
		String safeName = jsonEscape(name == null || name.isEmpty() ? "Player" : name);
		String skinUrl = "http://127.0.0.1:" + port + "/texture/skin/" + dashedTextureUuid;
		String payload = "{\"timestamp\":" + System.currentTimeMillis()
				+ ",\"profileId\":\"" + normalizedProfileUuid + "\""
				+ ",\"profileName\":\"" + safeName + "\""
				+ ",\"textures\":{\"SKIN\":{\"url\":\"" + skinUrl + "\"}";
		if (includeCape) {
			String capeUrl = "http://127.0.0.1:" + port + "/texture/cape/" + dashedTextureUuid;
			payload += ",\"CAPE\":{\"url\":\"" + capeUrl + "\"}";
		}
		return payload + "}}";
	}

	private static Object createTextureProperty(ClassLoader loader, String value, String signature) {
		try {
			Class<?> propertyClass = Class.forName("com.mojang.authlib.properties.Property", false, loader);
			String effectiveSignature = signature;
			if (effectiveSignature == null || effectiveSignature.isEmpty()) {
				effectiveSignature = "AA==";
			}
			if (effectiveSignature != null && !effectiveSignature.isEmpty()) {
				Constructor<?> constructor = propertyClass.getConstructor(String.class, String.class, String.class);
				return constructor.newInstance("textures", value, effectiveSignature);
			}
			Constructor<?> constructor = propertyClass.getConstructor(String.class, String.class);
			return constructor.newInstance("textures", value);
		} catch (Throwable ignored) {
			return null;
		}
	}

	private static Object addTextureProperty(Object profile, String value, String signature) {
		Object property = createTextureProperty(profile.getClass().getClassLoader(), value, signature);
		if (property == null) {
			return null;
		}
		return addTextureProperty(profile, property);
	}

	private static Object addTextureProperty(Object profile, Object property) {
		try {
			Object propertyMap = getProfileProperties(profile);
			if (propertyMap == null) {
				return null;
			}
			Method put = propertyMap.getClass().getMethod("put", Object.class, Object.class);
			put.invoke(propertyMap, "textures", property);
			return profile;
		} catch (Throwable ignored) {
			return null;
		}
	}

	private static boolean profileHasTexturesSafe(Object profile) {
		try {
			return profileHasTextures(profile);
		} catch (Throwable ignored) {
			return false;
		}
	}

	private static boolean profileHasTextures(Object profile) throws Exception {
		Object propertyMap = getProfileProperties(profile);
		if (propertyMap == null) {
			return false;
		}
		Object textures = propertyMap.getClass().getMethod("get", Object.class).invoke(propertyMap, "textures");
		return textures instanceof Collection && !((Collection<?>) textures).isEmpty();
	}

	private static Object getProfileProperties(Object profile) {
		return invokeNoArg(profile, "getProperties", "properties");
	}

	private static String buildProfileUrl(Object sessionService, String uuid, String name, boolean requireSecure) {
		String baseUrl = getBaseUrl(sessionService);
		if (baseUrl == null || baseUrl.isEmpty()) {
			String port = String.valueOf(System.getenv("HISTOLAUNCHER_PORT") == null ? "" : System.getenv("HISTOLAUNCHER_PORT")).trim();
			if (port.isEmpty()) {
				return null;
			}
			baseUrl = "http://127.0.0.1:" + port + "/authserver/sessionserver/session/minecraft/";
		}
		StringBuilder url = new StringBuilder(baseUrl);
		if (!baseUrl.endsWith("/")) {
			url.append('/');
		}
		url.append("profile/").append(uuid).append("?unsigned=").append(!requireSecure);
		if (name != null && !name.trim().isEmpty()) {
			try {
				url.append("&username=").append(URLEncoder.encode(name.trim(), "UTF-8"));
			} catch (Exception ignored) {
			}
		}
		return url.toString();
	}

	private static String getBaseUrl(Object sessionService) {
		try {
			Field field = sessionService.getClass().getDeclaredField("baseUrl");
			field.setAccessible(true);
			Object value = field.get(sessionService);
			return value == null ? "" : String.valueOf(value);
		} catch (Throwable ignored) {
			return "";
		}
	}

	private static String fetchProfileJson(String profileUrl, int timeoutMs) {
		if (profileUrl == null || profileUrl.trim().isEmpty()) {
			return null;
		}
		HttpURLConnection connection = null;
		InputStream in = null;
		try {
			connection = (HttpURLConnection) new URL(profileUrl).openConnection();
			connection.setConnectTimeout(timeoutMs);
			connection.setReadTimeout(timeoutMs);
			connection.setUseCaches(false);
			connection.setRequestProperty("Accept", "application/json");
			connection.setRequestProperty("User-Agent", "HistolauncherAuthlibFastProfile/1.0");
			int code = connection.getResponseCode();
			if (code < 200 || code >= 300) {
				return null;
			}
			in = connection.getInputStream();
			byte[] buffer = new byte[4096];
			StringBuilder out = new StringBuilder();
			while (true) {
				int read = in.read(buffer);
				if (read < 0) {
					break;
				}
				out.append(new String(buffer, 0, read, StandardCharsets.UTF_8));
			}
			return out.toString();
		} catch (Throwable ignored) {
			return null;
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

	private static String jsonString(String json, String key) {
		Pattern pattern = Pattern.compile("\\\"" + Pattern.quote(key) + "\\\"\\s*:\\s*\\\"((?:\\\\.|[^\\\"\\\\])*)\\\"");
		Matcher matcher = pattern.matcher(json == null ? "" : json);
		return matcher.find() ? jsonUnescape(matcher.group(1)) : null;
	}

	private static String jsonUnescape(String value) {
		StringBuilder out = new StringBuilder();
		boolean escaped = false;
		for (int i = 0; i < value.length(); i++) {
			char ch = value.charAt(i);
			if (escaped) {
				switch (ch) {
					case 'n': out.append('\n'); break;
					case 'r': out.append('\r'); break;
					case 't': out.append('\t'); break;
					case 'b': out.append('\b'); break;
					case 'f': out.append('\f'); break;
					default: out.append(ch); break;
				}
				escaped = false;
			} else if (ch == '\\') {
				escaped = true;
			} else {
				out.append(ch);
			}
		}
		if (escaped) {
			out.append('\\');
		}
		return out.toString();
	}

	private static String jsonEscape(String value) {
		return String.valueOf(value == null ? "" : value).replace("\\", "\\\\").replace("\"", "\\\"");
	}

	private static Object invokeNoArg(Object target, String... methodNames) {
		if (target == null || methodNames == null) {
			return null;
		}
		for (String methodName : methodNames) {
			if (methodName == null || methodName.isEmpty()) {
				continue;
			}
			try {
				return target.getClass().getMethod(methodName).invoke(target);
			} catch (Throwable ignored) {
			}
		}
		return null;
	}

	private static String fallbackAccessorName(String methodName) {
		if (methodName == null || !methodName.startsWith("get") || methodName.length() <= 3) {
			return null;
		}
		char first = Character.toLowerCase(methodName.charAt(3));
		if (methodName.length() == 4) {
			return String.valueOf(first);
		}
		return first + methodName.substring(4);
	}

	private static String invokeString(Object target, String methodName) {
		try {
			Object value = invokeNoArg(target, methodName, fallbackAccessorName(methodName));
			return value == null ? "" : String.valueOf(value);
		} catch (Throwable ignored) {
			return "";
		}
	}

	private static String profileCacheKey(String uuid, String name, boolean requireSecure) {
		String cleanUuid = normalizeUuid(uuid);
		if (cleanUuid.isEmpty()) {
			return "";
		}
		return cleanUuid + "|" + String.valueOf(name == null ? "" : name).trim().toLowerCase() + "|" + (requireSecure ? "signed" : "unsigned");
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

	private static String dashedUuid(String uuid) {
		String raw = normalizeUuid(uuid);
		if (raw.isEmpty()) {
			return "";
		}
		return raw.substring(0, 8) + "-" + raw.substring(8, 12) + "-" + raw.substring(12, 16) + "-" + raw.substring(16, 20) + "-" + raw.substring(20);
	}

	@Override
	public Optional<ClassVisitor> transform(ClassLoader classLoader, String className, ClassVisitor writer, TransformContext ctx) {
		if (hasDebugVersionLineRecipe(ctx)) {
			Optional<ClassVisitor> ldcVisitor = super.transform(classLoader, className, writer, ctx);
			final ClassVisitor downstream = ldcVisitor.orElse(writer);
			return Optional.of(new ClassVisitor(ASM9, downstream) {
				@Override
				public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
					MethodVisitor visitor = super.visitMethod(access, name, descriptor, signature, exceptions);
					return new MethodVisitor(ASM9, visitor) {
						private boolean pendingClientBrand;

						@Override
						public void visitMethodInsn(int opcode, String owner, String methodName, String methodDescriptor, boolean isInterface) {
							super.visitMethodInsn(opcode, owner, methodName, methodDescriptor, isInterface);
							pendingClientBrand = opcode == INVOKESTATIC
									&& "net/minecraft/client/ClientBrandRetriever".equals(owner)
									&& "getClientModName".equals(methodName)
									&& "()Ljava/lang/String;".equals(methodDescriptor);
						}

						@Override
						public void visitInvokeDynamicInsn(String invokeName, String invokeDescriptor, moe.yushi.authlibinjector.internal.org.objectweb.asm.Handle bootstrapMethodHandle, Object... bootstrapMethodArguments) {
							if (pendingClientBrand && isDebugVersionLineConcat(invokeName, invokeDescriptor, bootstrapMethodArguments)) {
								ctx.markModified();
								ctx.invokeCallback(this.mv, AuthServerNameInjector.class, "appendDebugClientBrand");
							}
							pendingClientBrand = false;
							super.visitInvokeDynamicInsn(invokeName, invokeDescriptor, bootstrapMethodHandle, bootstrapMethodArguments);
						}

						@Override
						public void visitInsn(int opcode) {
							pendingClientBrand = false;
							super.visitInsn(opcode);
						}

						@Override
						public void visitIntInsn(int opcode, int operand) {
							pendingClientBrand = false;
							super.visitIntInsn(opcode, operand);
						}

						@Override
						public void visitVarInsn(int opcode, int varIndex) {
							pendingClientBrand = false;
							super.visitVarInsn(opcode, varIndex);
						}

						@Override
						public void visitTypeInsn(int opcode, String type) {
							pendingClientBrand = false;
							super.visitTypeInsn(opcode, type);
						}

						@Override
						public void visitFieldInsn(int opcode, String owner, String fieldName, String fieldDescriptor) {
							pendingClientBrand = false;
							super.visitFieldInsn(opcode, owner, fieldName, fieldDescriptor);
						}

						@Override
						public void visitJumpInsn(int opcode, Label label) {
							pendingClientBrand = false;
							super.visitJumpInsn(opcode, label);
						}

						@Override
						public void visitLdcInsn(Object value) {
							pendingClientBrand = false;
							super.visitLdcInsn(value);
						}
					};
				}
			});
		}

		if ("net.minecraft.client.gui.screens.TitleScreen".equals(className)) {
			return Optional.of(new ClassVisitor(ASM9, writer) {
				@Override
				public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
					MethodVisitor visitor = super.visitMethod(access, name, descriptor, signature, exceptions);
					if ("extractRenderState".equals(name) && "(Lnet/minecraft/client/gui/GuiGraphicsExtractor;IIF)V".equals(descriptor)) {
						ctx.markModified();
						return new MethodVisitor(ASM9, visitor) {
							private boolean sawWorldVersionName;
							private boolean captureTitleTextStore;
							private int titleTextLocal = -1;

							@Override
							public void visitMethodInsn(int opcode, String owner, String methodName, String methodDescriptor, boolean isInterface) {
								super.visitMethodInsn(opcode, owner, methodName, methodDescriptor, isInterface);
								if ("net/minecraft/WorldVersion".equals(owner) && "name".equals(methodName) && "()Ljava/lang/String;".equals(methodDescriptor)) {
									sawWorldVersionName = true;
								}
							}

							@Override
							public void visitInvokeDynamicInsn(String invokeName, String invokeDescriptor, moe.yushi.authlibinjector.internal.org.objectweb.asm.Handle bootstrapMethodHandle, Object... bootstrapMethodArguments) {
								super.visitInvokeDynamicInsn(invokeName, invokeDescriptor, bootstrapMethodHandle, bootstrapMethodArguments);
								if (sawWorldVersionName && invokeDescriptor.endsWith(")Ljava/lang/String;")) {
									captureTitleTextStore = true;
									sawWorldVersionName = false;
								}
							}

							@Override
							public void visitVarInsn(int opcode, int varIndex) {
								super.visitVarInsn(opcode, varIndex);
								if (captureTitleTextStore && opcode == ASTORE) {
									titleTextLocal = varIndex;
									captureTitleTextStore = false;
									return;
								}
								if (opcode == ALOAD && varIndex == titleTextLocal) {
									ctx.invokeCallback(this.mv, AuthServerNameInjector.class, "appendTitleScreenBrand");
								}
							}
						};
					}
					return visitor;
				}
			});
		}

		if ("com.mojang.authlib.minecraft.MinecraftProfileTexture".equals(className)) {
			return Optional.of(new ClassVisitor(ASM9, writer) {
				@Override
				public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
					MethodVisitor visitor = super.visitMethod(access, name, descriptor, signature, exceptions);
					if ("getUrl".equals(name) && "()Ljava/lang/String;".equals(descriptor)) {
						ctx.markModified();
						return new MethodVisitor(ASM9, visitor) {
							@Override
							public void visitInsn(int opcode) {
								if (opcode == ARETURN) {
									ctx.invokeCallback(this.mv, ConstantURLTransformUnit.class, "transformTextureUrl");
								}
								super.visitInsn(opcode);
							}
						};
					}
					return visitor;
				}
			});
		}

		if ("com.mojang.authlib.yggdrasil.YggdrasilMinecraftSessionService".equals(className)) {
			Optional<ClassVisitor> ldcVisitor = super.transform(classLoader, className, writer, ctx);
			final ClassVisitor downstream = ldcVisitor.orElse(writer);
			return Optional.of(new ClassVisitor(ASM9, downstream) {
				@Override
				public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
					MethodVisitor visitor = super.visitMethod(access, name, descriptor, signature, exceptions);
					if ("getTextures".equals(name) && "(Lcom/mojang/authlib/GameProfile;Z)Ljava/util/Map;".equals(descriptor)) {
						ctx.markModified();
						return new MethodVisitor(ASM9, visitor) {
							@Override
							public void visitCode() {
								super.visitCode();
								this.mv.visitVarInsn(ALOAD, 0);
								this.mv.visitVarInsn(ALOAD, 1);
								this.mv.visitVarInsn(ILOAD, 2);
								ctx.invokeCallback(this.mv, ConstantURLTransformUnit.class, "ensureProfileTextures");
								this.mv.visitInsn(POP);
							}
						};
					} else if ("getPackedTextures".equals(name) && "(Lcom/mojang/authlib/GameProfile;)Lcom/mojang/authlib/properties/Property;".equals(descriptor)) {
					ctx.markModified();
					return new MethodVisitor(ASM9, visitor) {
						@Override
						public void visitCode() {
							super.visitCode();
							this.mv.visitVarInsn(ALOAD, 0);
							this.mv.visitVarInsn(ALOAD, 1);
							ctx.invokeCallback(this.mv, ConstantURLTransformUnit.class, "getPackedTexturesFast");
							this.mv.visitInsn(DUP);
							Label continueOriginal = new Label();
							this.mv.visitJumpInsn(IFNULL, continueOriginal);
							this.mv.visitTypeInsn(CHECKCAST, "com/mojang/authlib/properties/Property");
							this.mv.visitInsn(ARETURN);
							this.mv.visitLabel(continueOriginal);
							this.mv.visitFrame(F_SAME1, 0, null, 1, new Object[]{"java/lang/Object"});
							this.mv.visitInsn(POP);
						}
					};
				} else if ("fetchProfile".equals(name) && "(Ljava/util/UUID;Z)Lcom/mojang/authlib/yggdrasil/ProfileResult;".equals(descriptor)) {
					ctx.markModified();
					return new MethodVisitor(ASM9, visitor) {
						@Override
						public void visitCode() {
							super.visitCode();
							this.mv.visitVarInsn(ALOAD, 0);
							this.mv.visitVarInsn(ALOAD, 1);
							this.mv.visitVarInsn(ILOAD, 2);
							ctx.invokeCallback(this.mv, ConstantURLTransformUnit.class, "fetchProfileFast");
							this.mv.visitInsn(DUP);
							Label continueOriginal = new Label();
							this.mv.visitJumpInsn(IFNULL, continueOriginal);
							this.mv.visitTypeInsn(CHECKCAST, "com/mojang/authlib/yggdrasil/ProfileResult");
							this.mv.visitInsn(ARETURN);
							this.mv.visitLabel(continueOriginal);
							this.mv.visitFrame(F_SAME1, 0, null, 1, new Object[]{"java/lang/Object"});
							this.mv.visitInsn(POP);
						}
					};
				} else if (("fillGameProfile".equals(name) || "fillProfileProperties".equals(name)) && "(Lcom/mojang/authlib/GameProfile;Z)Lcom/mojang/authlib/GameProfile;".equals(descriptor)) {
						ctx.markModified();
						return new MethodVisitor(ASM9, visitor) {
							@Override
							public void visitCode() {
								super.visitCode();
								this.mv.visitVarInsn(ALOAD, 0);
								this.mv.visitVarInsn(ALOAD, 1);
								this.mv.visitVarInsn(ILOAD, 2);
								ctx.invokeCallback(this.mv, ConstantURLTransformUnit.class, "fillGameProfileFast");
								this.mv.visitInsn(DUP);
								Label continueOriginal = new Label();
								this.mv.visitJumpInsn(IFNULL, continueOriginal);
								this.mv.visitTypeInsn(CHECKCAST, "com/mojang/authlib/GameProfile");
								this.mv.visitInsn(ARETURN);
								this.mv.visitLabel(continueOriginal);
								this.mv.visitFrame(F_SAME1, 0, null, 1, new Object[]{"java/lang/Object"});
								this.mv.visitInsn(POP);
							}
						};
					}
					return visitor;
				}
			});
		}

		return super.transform(classLoader, className, writer, ctx);
	}

	private static boolean hasDebugVersionLineRecipe(TransformContext ctx) {
		for (String constant : ctx.getStringConstants()) {
			if (isDebugVersionLineRecipe(constant)) {
				return true;
			}
		}
		return false;
	}

	private static boolean isDebugVersionLineConcat(String invokeName, String invokeDescriptor, Object... bootstrapMethodArguments) {
		if (!"makeConcatWithConstants".equals(invokeName) || !"(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;".equals(invokeDescriptor)) {
			return false;
		}
		if (bootstrapMethodArguments == null) {
			return false;
		}
		for (Object argument : bootstrapMethodArguments) {
			if (argument instanceof String && isDebugVersionLineRecipe((String) argument)) {
				return true;
			}
		}
		return false;
	}

	private static boolean isDebugVersionLineRecipe(String value) {
		return value != null && value.startsWith(DEBUG_VERSION_LINE_RECIPE_PREFIX) && value.indexOf("/\u0001") >= 0;
	}

	@Override
	public String toString() {
		return "Constant URL Transformer";
	}
}