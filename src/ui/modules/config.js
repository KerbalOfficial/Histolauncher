// ui/modules/config.js

export const ADD_PROFILE_OPTION = '__add_new_profile__';

export const JAVA_RUNTIME_AUTO = 'auto';
export const JAVA_RUNTIME_PATH = '__java_path_default__';
export const JAVA_RUNTIME_INSTALL_OPTION = '__install_java_runtime__';

export const AVAILABLE_PAGE_SIZE = 30;

export let SIGNUP_URL = 'https://histolauncher.org/signup';

export const setHistolauncherWebsiteUrls = ({ websiteOrigin, signupUrl } = {}) => {
  const origin = String(websiteOrigin || signupUrl || '').trim().replace(/\/+$/, '');
  if (origin) {
    SIGNUP_URL = signupUrl || `${origin}/signup`;
  }
};

export const INSTALL_POLL_MS_ACTIVE = 500;
export const INSTALL_POLL_MS_PAUSED = 1500;
export const INSTALL_POLL_MS_BACKOFF_BASE = 800;
export const INSTALL_POLL_MS_BACKOFF_MAX = 2000;

export const unicodeList = {
  warning: '⚠',
  dropdown_open: '⏷',
  dropdown_close: '⏵',
  sort_asc: '▲',
  sort_desc: '▼',
  empty: '—',
};

export const LOADER_UI_ORDER = ['fabric', 'legacyfabric', 'babric', 'ornithe', 'forge', 'liteloader', 'modloader', 'neoforge', 'quilt'];

export const CURSEFORGE_MODPACK_LOADER_ORDER = ['vanilla', 'fabric', 'forge', 'neoforge', 'quilt'];
export const CURSEFORGE_ADDON_LOADER_ORDER = ['fabric', 'forge', 'liteloader', 'neoforge', 'quilt'];

export const MODPACK_EXPORT_LOADER_ORDER = ['vanilla', ...LOADER_UI_ORDER];

export const getModsLoaderFilterOrder = (addonType = 'mods', provider = 'modrinth') => {
  const normalizedType = String(addonType || 'mods').toLowerCase();
  const normalizedProvider = String(provider || 'modrinth').toLowerCase();
  if ((normalizedType === 'mods' || normalizedType === 'modpacks') && normalizedProvider === 'curseforge') {
    return CURSEFORGE_ADDON_LOADER_ORDER;
  }
  if (normalizedType === 'mods' || normalizedType === 'modpacks') {
    return LOADER_UI_ORDER;
  }
  return [];
};

export const getModpackExportLoaderOrder = (exportFormat = 'histolauncher') => {
  if (String(exportFormat || 'histolauncher').toLowerCase() === 'curseforge') {
    return CURSEFORGE_MODPACK_LOADER_ORDER;
  }
  return MODPACK_EXPORT_LOADER_ORDER;
};

export const LOADER_UI_CONFIG = {
  vanilla: {
    name: 'Vanilla',
    buttonClass: 'vanilla',
    accent: '#6b8e4e',
    descriptionKey: 'loaders.vanilla.description',
    subtitleKey: 'loaders.vanilla.subtitle',
    image: 'assets/images/java_icon.png',
  },
  fabric: {
    name: 'Fabric',
    buttonClass: 'fabric',
    accent: '#bebb88',
    descriptionKey: 'loaders.fabric.description',
    subtitleKey: 'loaders.fabric.subtitle',
    image: 'assets/images/modloader-fabric-versioncard.png',
  },
  legacyfabric: {
    name: 'Legacy Fabric',
    buttonClass: 'fabric',
    accent: '#bebb88',
    descriptionKey: 'loaders.legacyfabric.description',
    subtitleKey: 'loaders.legacyfabric.subtitle',
    image: 'assets/images/modloader-legacyfabric-versioncard.png',
  },
  babric: {
    name: 'Babric',
    buttonClass: 'babric',
    accent: '#bebb88',
    descriptionKey: 'loaders.babric.description',
    subtitleKey: 'loaders.babric.subtitle',
    image: 'assets/images/modloader-babric-versioncard.png',
  },
  ornithe: {
    name: 'Ornithe',
    buttonClass: 'ornithe',
    accent: '#b14fa0',
    descriptionKey: 'loaders.ornithe.description',
    subtitleKey: 'loaders.ornithe.subtitle',
    image: 'assets/images/modloader-ornithe-versioncard.png',
  },
  forge: {
    name: 'Forge',
    buttonClass: 'forge',
    accent: '#646ec9',
    descriptionKey: 'loaders.forge.description',
    subtitleKey: 'loaders.forge.subtitle',
    image: 'assets/images/modloader-forge-versioncard.png',
  },
  liteloader: {
    name: 'LiteLoader',
    buttonClass: 'liteloader',
    accent: '#9bb9d4',
    descriptionKey: 'loaders.liteloader.description',
    subtitleKey: 'loaders.liteloader.subtitle',
    image: 'assets/images/modloader-liteloader-versioncard.png',
  },
  modloader: {
    name: 'ModLoader',
    buttonClass: 'modloader',
    accent: '#cccccc',
    descriptionKey: 'loaders.modloader.description',
    subtitleKey: 'loaders.modloader.subtitle',
    image: 'assets/images/modloader-modloader-versioncard.png',
  },
  neoforge: {
    name: 'NeoForge',
    buttonClass: 'neoforge',
    accent: '#b64300',
    descriptionKey: 'loaders.neoforge.description',
    subtitleKey: 'loaders.neoforge.subtitle',
    image: 'assets/images/modloader-neoforge-versioncard.png',
  },
  quilt: {
    name: 'Quilt',
    buttonClass: 'quilt',
    accent: '#8f66db',
    descriptionKey: 'loaders.quilt.description',
    subtitleKey: 'loaders.quilt.subtitle',
    image: 'assets/images/modloader-quilt-versioncard.png',
  },
};

export const getLoaderUi = (loaderType) => LOADER_UI_CONFIG[loaderType] || {
  name: loaderType ? loaderType.charAt(0).toUpperCase() + loaderType.slice(1) : 'Loader',
  buttonClass: 'default',
  accent: '#888',
  descriptionKey: 'loaders.fallback.description',
  subtitleKey: 'loaders.fallback.subtitle',
  image: 'assets/images/version_placeholder.png',
};

export const SHADER_TYPE_ORDER = ['optifine', 'iris'];

export const SHADER_TYPE_CONFIG = {
  optifine: { name: 'OptiFine' },
  iris: { name: 'Iris' },
};

export const normalizeAddonCompatibilityToken = (value) => {
  const compact = String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
  const aliases = {
    fabric: 'fabric',
    legacyfabric: 'legacyfabric',
    babric: 'babric',
    ornithe: 'ornithe',
    forge: 'forge',
    liteloader: 'liteloader',
    modloader: 'modloader',
    neoforge: 'neoforge',
    quilt: 'quilt',
    optifine: 'optifine',
    iris: 'iris',
  };
  if (aliases[compact]) return aliases[compact];
  if (compact.includes('optifine')) return 'optifine';
  if (compact.includes('iris')) return 'iris';
  return '';
};

export const getShaderTypeUi = (shaderType) => {
  const key = normalizeAddonCompatibilityToken(shaderType);
  return SHADER_TYPE_CONFIG[key] || {
    name: key ? key.charAt(0).toUpperCase() + key.slice(1) : '',
    nameKey: key ? '' : 'mods.compatibility.shaderType',
  };
};
