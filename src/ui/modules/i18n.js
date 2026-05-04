// ui/modules/i18n.js

import { getEl } from './dom-utils.js';

const LANGUAGE_MANIFEST_URL = 'i18n/languages.json';
const DEFAULT_LANGUAGE = 'en';
const LANGUAGE_CODE_RE = /^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$/;
const RTL_LANGUAGE_BASES = new Set(['ar', 'fa', 'he', 'ur']);
const TRADITIONAL_CHINESE_CODES = new Set(['zh-hant', 'zh-tw', 'zh-hk', 'zh-mo']);

let manifestPromise = null;
let languageManifest = null;
let fallbackDictionary = {};
let currentDictionary = {};
let requestedLanguage = DEFAULT_LANGUAGE;
let currentLanguage = DEFAULT_LANGUAGE;
let observerStarted = false;

const dictionaryCache = new Map();

const getNestedValue = (source, key) => {
  if (!source || !key) return undefined;
  return String(key).split('.').reduce((value, part) => {
    if (value && Object.prototype.hasOwnProperty.call(value, part)) {
      return value[part];
    }
    return undefined;
  }, source);
};

const interpolate = (value, replacements = {}) => String(value).replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) => {
  if (Object.prototype.hasOwnProperty.call(replacements, name)) {
    return String(replacements[name]);
  }
  return match;
});

export const t = (key, replacements = {}) => {
  const value = getNestedValue(currentDictionary, key) ?? getNestedValue(fallbackDictionary, key);
  if (value === undefined || value === null) return String(key || '');
  return interpolate(value, replacements);
};

const safeLanguageCode = (value) => {
  const code = String(value || DEFAULT_LANGUAGE).trim().toLowerCase();
  if (code === 'system') return code;
  return LANGUAGE_CODE_RE.test(code) ? code : DEFAULT_LANGUAGE;
};

const getLanguageEntries = () => {
  const languages = languageManifest && Array.isArray(languageManifest.languages)
    ? languageManifest.languages
    : [];
  return languages.filter((entry) => LANGUAGE_CODE_RE.test(String(entry && entry.code || '').trim().toLowerCase()));
};

const languageEntryFor = (code) => {
  const normalized = safeLanguageCode(code);
  return getLanguageEntries().find((entry) => String(entry.code || '').trim().toLowerCase() === normalized) || null;
};

const languageFileFor = (code) => {
  const entry = languageEntryFor(code);
  const file = String(entry && entry.file || '').trim();
  if (/^[a-z0-9._-]+\.json$/i.test(file)) return file;
  return `${safeLanguageCode(code)}.json`;
};

const languageDirectionFor = (code) => {
  const entry = languageEntryFor(code);
  const manifestDirection = String(entry && entry.dir || '').trim().toLowerCase();
  if (manifestDirection === 'rtl' || manifestDirection === 'ltr') return manifestDirection;

  const base = safeLanguageCode(code).split('-')[0];
  return RTL_LANGUAGE_BASES.has(base) ? 'rtl' : 'ltr';
};

export const loadLanguageManifest = async () => {
  if (languageManifest) return languageManifest;
  if (!manifestPromise) {
    manifestPromise = fetch(LANGUAGE_MANIFEST_URL)
      .then((response) => (response.ok ? response.json() : { languages: [] }))
      .catch((err) => {
        console.warn('Failed to load language manifest:', err);
        return { languages: [] };
      });
  }
  languageManifest = await manifestPromise;
  return languageManifest;
};

const loadDictionary = async (code) => {
  const normalized = safeLanguageCode(code);
  if (dictionaryCache.has(normalized)) return dictionaryCache.get(normalized);

  await loadLanguageManifest();
  const file = languageFileFor(normalized);
  const dictionaryPromise = fetch(`i18n/${file}`)
    .then((response) => (response.ok ? response.json() : {}))
    .catch((err) => {
      console.warn(`Failed to load ${normalized} language file:`, err);
      return {};
    });
  dictionaryCache.set(normalized, dictionaryPromise);
  return dictionaryPromise;
};

const resolveSystemLanguage = () => {
  const available = getLanguageEntries().map((entry) => String(entry.code || '').trim().toLowerCase());
  const candidates = Array.isArray(navigator.languages) && navigator.languages.length > 0
    ? navigator.languages
    : [navigator.language];

  for (const candidate of candidates) {
    const normalized = safeLanguageCode(candidate);
    if (available.includes(normalized)) return normalized;

    const parts = normalized.split('-');
    const base = parts[0];
    if (base === 'zh') {
      const usesTraditionalChinese = TRADITIONAL_CHINESE_CODES.has(normalized)
        || parts.includes('hant')
        || parts.some((part) => ['tw', 'hk', 'mo'].includes(part));
      if (usesTraditionalChinese && available.includes('zh-tw')) return 'zh-tw';

      const usesSimplifiedChinese = normalized === 'zh-hans'
        || parts.includes('hans')
        || parts.some((part) => ['cn', 'sg'].includes(part));
      if (usesSimplifiedChinese && available.includes('zh-cn')) return 'zh-cn';
    }

    const baseMatch = available.find((code) => code === base || code.split('-')[0] === base);
    if (baseMatch) return baseMatch;
  }

  return DEFAULT_LANGUAGE;
};

const resolveLanguage = (value) => {
  const normalized = safeLanguageCode(value);
  if (normalized === 'system') return resolveSystemLanguage();
  return languageEntryFor(normalized) ? normalized : DEFAULT_LANGUAGE;
};

const applyElementTranslation = (element) => {
  if (!(element instanceof Element)) return;

  const textKey = element.getAttribute('data-i18n');
  if (textKey) element.textContent = t(textKey);

  const htmlKey = element.getAttribute('data-i18n-html');
  if (htmlKey) element.innerHTML = t(htmlKey);

  const attrMap = [
    ['data-i18n-title', 'title'],
    ['data-i18n-aria-label', 'aria-label'],
    ['data-i18n-placeholder', 'placeholder'],
    ['data-i18n-tooltip', 'data-tooltip'],
    ['data-i18n-alt', 'alt'],
  ];

  attrMap.forEach(([dataAttr, targetAttr]) => {
    const key = element.getAttribute(dataAttr);
    if (key) element.setAttribute(targetAttr, t(key));
  });
};

export const applyTranslations = (root = document) => {
  if (root instanceof Element) applyElementTranslation(root);
  const queryRoot = root && root.querySelectorAll ? root : document;
  queryRoot.querySelectorAll('[data-i18n], [data-i18n-html], [data-i18n-title], [data-i18n-aria-label], [data-i18n-placeholder], [data-i18n-tooltip], [data-i18n-alt]')
    .forEach(applyElementTranslation);
};

export const populateLanguageSelect = async () => {
  await loadLanguageManifest();
  const select = getEl('settings-launcher-language');
  if (!select) return;

  const selected = requestedLanguage;
  select.innerHTML = '';
  getLanguageEntries().forEach((entry) => {
    const code = safeLanguageCode(entry.code);
    const option = document.createElement('option');
    option.value = code;
    const nativeName = String(entry.nativeName || '').trim();
    const name = String(entry.name || '').trim();
    option.textContent = nativeName && name && nativeName !== name ? `${nativeName} - ${name}` : (nativeName || name || code);
    option.dir = languageDirectionFor(code);
    select.appendChild(option);
  });

  if (!languageEntryFor(selected)) {
    const fallback = languageEntryFor(DEFAULT_LANGUAGE);
    if (fallback) select.value = DEFAULT_LANGUAGE;
  } else {
    select.value = selected;
  }
};

export const setLauncherLanguage = async (value = DEFAULT_LANGUAGE) => {
  await loadLanguageManifest();
  requestedLanguage = safeLanguageCode(value);
  currentLanguage = resolveLanguage(requestedLanguage);

  fallbackDictionary = await loadDictionary(DEFAULT_LANGUAGE);
  currentDictionary = currentLanguage === DEFAULT_LANGUAGE
    ? fallbackDictionary
    : await loadDictionary(currentLanguage);

  document.documentElement.lang = currentLanguage;
  document.documentElement.dir = languageDirectionFor(currentLanguage);
  document.documentElement.dataset.language = currentLanguage;
  document.documentElement.dataset.textDirection = document.documentElement.dir;
  applyTranslations(document);
  await populateLanguageSelect();
  window.dispatchEvent(new CustomEvent('histolauncher:language-changed', {
    detail: { requestedLanguage, currentLanguage, direction: document.documentElement.dir },
  }));
};

export const initI18n = async () => {
  await setLauncherLanguage(DEFAULT_LANGUAGE);

  if (observerStarted) return;
  observerStarted = true;
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node instanceof Element) applyTranslations(node);
      });
    });
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
};
