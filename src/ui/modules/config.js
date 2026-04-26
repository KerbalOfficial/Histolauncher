// ui/modules/config.js

export const ADD_PROFILE_OPTION = '__add_new_profile__';

export const JAVA_RUNTIME_AUTO = 'auto';
export const JAVA_RUNTIME_PATH = '__java_path_default__';
export const JAVA_RUNTIME_INSTALL_OPTION = '__install_java_runtime__';

export const AVAILABLE_PAGE_SIZE = 30;

export const INSTALL_POLL_MS_ACTIVE = 500;
export const INSTALL_POLL_MS_PAUSED = 1500;
export const INSTALL_POLL_MS_BACKOFF_BASE = 800;
export const INSTALL_POLL_MS_BACKOFF_MAX = 2000;

export const unicodeList = {
  warning: '⚠',
  dropdown_open: '⏷',
  dropdown_close: '⏵',
};

export const LOADER_UI_ORDER = ['fabric', 'babric', 'forge', 'modloader', 'neoforge', 'quilt'];

export const LOADER_UI_CONFIG = {
  fabric: {
    name: 'Fabric',
    buttonClass: 'fabric',
    accent: '#bebb88',
    description: 'Lightweight & fast',
    subtitle: 'Mostly used for game optimization',
    image: 'assets/images/modloader-fabric-versioncard.png',
  },
  babric: {
    name: 'Babric',
    buttonClass: 'babric',
    accent: '#bebb88',
    description: 'Minecraft Beta Fabric fork',
    subtitle: 'A fork of Fabric to support Beta 1.7.3',
    image: 'assets/images/modloader-babric-versioncard.png',
  },
  forge: {
    name: 'Forge',
    buttonClass: 'forge',
    accent: '#646ec9',
    description: 'Full-modifications & popular',
    subtitle: 'Mostly used for game modifications',
    image: 'assets/images/modloader-forge-versioncard.png',
  },
  modloader: {
    name: 'ModLoader',
    buttonClass: 'modloader',
    accent: '#cccccc',
    description: 'Legacy jar-mod runtime',
    subtitle: 'Mostly used for modding old versions of Minecraft',
    image: 'assets/images/modloader-modloader-versioncard.png',
  },
  neoforge: {
    name: 'NeoForge',
    buttonClass: 'neoforge',
    accent: '#b64300',
    description: 'Modern & expansive',
    subtitle: 'A fork of Forge',
    image: 'assets/images/modloader-neoforge-versioncard.png',
  },
  quilt: {
    name: 'Quilt',
    buttonClass: 'quilt',
    accent: '#8f66db',
    description: 'Flexible & modern',
    subtitle: 'Mostly used for lightweight modern modding',
    image: 'assets/images/modloader-quilt-versioncard.png',
  },
};

export const getLoaderUi = (loaderType) => LOADER_UI_CONFIG[loaderType] || {
  name: loaderType ? loaderType.charAt(0).toUpperCase() + loaderType.slice(1) : 'Loader',
  buttonClass: 'default',
  accent: '#888',
  description: 'Custom loader',
  subtitle: 'No description available',
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
    babric: 'babric',
    forge: 'forge',
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
    name: key ? key.charAt(0).toUpperCase() + key.slice(1) : 'Shader Type',
  };
};
