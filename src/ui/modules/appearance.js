// ui/modules/appearance.js

export const CUSTOM_THEME = 'custom';
const OVERRIDE_STYLE_ID = 'histolauncher-theme-overrides';

export const THEME_ALIASES = {
  'lavender-dark': 'amethyst-dark',
  'lavender-light': 'amethyst-light',
  'sunset-dark': 'orange-dark',
  'sunset-light': 'orange-light',
};

export const PRESET_THEMES = [
  'dark',
  'light',
  'dark-contrast',
  'light-contrast',
  'chocolate-dark',
  'chocolate-light',
  'strawberry-dark',
  'strawberry-light',
  'blueberry-dark',
  'blueberry-light',
  'leaf-dark',
  'leaf-light',
  'orange-dark',
  'orange-light',
  'midnight-dark',
  'midnight-light',
  'graphite-dark',
  'graphite-light',
  'ocean-dark',
  'ocean-light',
  'amethyst-dark',
  'amethyst-light',
  'aero-dark',
  'aero-light',
];

export const VALID_THEMES = new Set([...PRESET_THEMES, CUSTOM_THEME]);

export const APPEARANCE_SETTING_KEYS = new Set([
  'launcher_theme',
  'launcher_theme_base',
  'launcher_theme_overrides',
  'launcher_ui_size',
  'layout_density',
  'compact_sidebar',
]);

const LIGHT_THEMES = new Set([
  'light',
  'light-contrast',
  'chocolate-light',
  'strawberry-light',
  'blueberry-light',
  'leaf-light',
  'orange-light',
  'midnight-light',
  'graphite-light',
  'ocean-light',
  'amethyst-light',
  'aero-light',
]);

const UNFILLED_ICON_RE = /(^|\/)unfilled_([a-z0-9_-]+\.(?:png|gif|jpg|jpeg|webp|svg))(\?|#|$)/i;
const DARK_UNFILLED_ICON_RE = /(^|\/)dark_unfilled_([a-z0-9_-]+\.(?:png|gif|jpg|jpeg|webp|svg))(\?|#|$)/i;

const DARKABLE_ICON_NAMES = new Set([
  'info.png',
]);
const DARKABLE_ICON_RE = new RegExp(
  `(^|/)(${Array.from(DARKABLE_ICON_NAMES).map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(\\?|#|$)`,
  'i',
);
const DARKED_ICON_RE = new RegExp(
  `(^|/)dark_(${Array.from(DARKABLE_ICON_NAMES).map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(\\?|#|$)`,
  'i',
);

let observerStarted = false;

export const isTruthySetting = (value, defaultValue = false) => {
  if (value === undefined || value === null || value === '') return defaultValue;
  return ['1', 'true', 'yes', 'on'].includes(String(value).trim().toLowerCase());
};

const normalizePresetTheme = (value) => {
  let theme = String(value || 'dark').trim().toLowerCase();
  theme = THEME_ALIASES[theme] || theme;
  return PRESET_THEMES.includes(theme) ? theme : 'dark';
};

const normalizeTheme = (value) => {
  let theme = String(value || 'dark').trim().toLowerCase();
  theme = THEME_ALIASES[theme] || theme;
  return VALID_THEMES.has(theme) ? theme : 'dark';
};

export const parseThemeOverrides = (value) => {
  if (!value) return {};
  try {
    const parsed = typeof value === 'string' ? JSON.parse(value) : value;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out = {};
    Object.entries(parsed).forEach(([key, rawValue]) => {
      const token = String(key || '').trim();
      const cssValue = String(rawValue || '').trim();
      // Validate the value too: braces/semicolons/comments would let an
      // imported theme break out of its declaration and inject arbitrary CSS.
      const valueIsSafe = cssValue
        && cssValue.length <= 256
        && !/[;{}<>]|\/\*|@/.test(cssValue);
      if (token.startsWith('--color-') && /^--[a-z0-9-]+$/i.test(token) && valueIsSafe) {
        out[token] = cssValue;
      }
    });
    return out;
  } catch {
    return {};
  }
};

export const serializeThemeOverrides = (overrides) => {
  const clean = parseThemeOverrides(overrides);
  return Object.keys(clean).length ? JSON.stringify(clean) : '';
};

const getOverridesStyleEl = () => {
  let styleEl = document.getElementById(OVERRIDE_STYLE_ID);
  if (!styleEl) {
    styleEl = document.createElement('style');
    styleEl.id = OVERRIDE_STYLE_ID;
    document.head.appendChild(styleEl);
  }
  return styleEl;
};

export const applyThemeOverrideStyles = (overrides = {}) => {
  const styleEl = getOverridesStyleEl();
  const entries = Object.entries(overrides || {}).filter(([key, value]) => key.startsWith('--color-') && value);
  if (!entries.length) {
    styleEl.textContent = '';
    return;
  }
  const body = entries.map(([key, value]) => `  ${key}: ${value};`).join('\n');
  styleEl.textContent = `:root[data-custom-theme="1"][data-theme] {\n${body}\n}`;
};

export const clearThemeOverrideStyles = () => {
  const styleEl = document.getElementById(OVERRIDE_STYLE_ID);
  if (styleEl) {
    styleEl.textContent = '';
  }
};

export const resolveEffectiveTheme = (settings = {}) => {
  const selectedTheme = normalizeTheme(settings.launcher_theme);
  const baseTheme = normalizePresetTheme(settings.launcher_theme_base);
  const isCustom = selectedTheme === CUSTOM_THEME;
  return {
    selectedTheme,
    baseTheme,
    isCustom,
    dataTheme: isCustom ? baseTheme : selectedTheme,
    overrides: isCustom ? parseThemeOverrides(settings.launcher_theme_overrides) : {},
  };
};

const normalizeLayoutDensity = (value) => {
  return String(value || '').trim().toLowerCase() === 'compact' ? 'compact' : 'comfortable';
};

const normalizeUiSize = (value) => {
  const uiSize = String(value || 'normal').trim().toLowerCase();
  return ['small', 'normal', 'large', 'extra-large'].includes(uiSize) ? uiSize : 'normal';
};

const UI_SIZE_ZOOM = {
  'small': 0.9,
  'normal': 1.0,
  'large': 1.15,
  'extra-large': 1.3,
};

const applyUiSizeZoom = (uiSize) => {
  const factor = UI_SIZE_ZOOM[uiSize] ?? 1.0;
  const root = document.documentElement;
  if (factor === 1.0) {
    root.style.zoom = '';
  } else {
    root.style.zoom = String(factor);
  }
};

export const isLightThemeActive = () => {
  return LIGHT_THEMES.has(document.documentElement.dataset.theme || '');
};

const shouldUseDarkIconVariant = (img) => {
  if (!isLightThemeActive()) return false;
  return true;
};

const toDarkUnfilledSrc = (src) =>
  String(src || '').replace(UNFILLED_ICON_RE, (_m, prefix, name, suffix) => `${prefix}dark_unfilled_${name}${suffix}`);

const toLightUnfilledSrc = (src) =>
  String(src || '').replace(DARK_UNFILLED_ICON_RE, (_m, prefix, name, suffix) => `${prefix}unfilled_${name}${suffix}`);

const toDarkPlainSrc = (src) =>
  String(src || '').replace(DARKABLE_ICON_RE, (_m, prefix, name, suffix) => `${prefix}dark_${name}${suffix}`);

const toLightPlainSrc = (src) =>
  String(src || '').replace(DARKED_ICON_RE, (_m, prefix, name, suffix) => `${prefix}${name}${suffix}`);

export const applyIconVariantPreference = (root = document) => {
  const images = Array.from(root.querySelectorAll ? root.querySelectorAll('img') : []);
  images.forEach((img) => {
    const useDark = shouldUseDarkIconVariant(img);
    const currentSrc = img.getAttribute('src') || '';
    if (!currentSrc) return;
    if (useDark) {
      if (UNFILLED_ICON_RE.test(currentSrc)) {
        const dark = toDarkUnfilledSrc(currentSrc);
        if (dark !== currentSrc) img.src = dark;
      } else if (DARKABLE_ICON_RE.test(currentSrc) && !DARKED_ICON_RE.test(currentSrc)) {
        const dark = toDarkPlainSrc(currentSrc);
        if (dark !== currentSrc) img.src = dark;
      }
    } else {
      if (DARK_UNFILLED_ICON_RE.test(currentSrc)) {
        const light = toLightUnfilledSrc(currentSrc);
        if (light !== currentSrc) img.src = light;
      } else if (DARKED_ICON_RE.test(currentSrc)) {
        const light = toLightPlainSrc(currentSrc);
        if (light !== currentSrc) img.src = light;
      }
    }
  });
};

const syncSidebarAccessibility = () => {
  document.querySelectorAll('.sidebar-item').forEach((item) => {
    const label = item.querySelector('span')?.textContent?.trim() || '';
    if (!label) return;
    item.setAttribute('aria-label', label);
    item.setAttribute('title', label);
  });
};

export const applyAppearanceSettings = (settings = {}) => {
  const root = document.documentElement;
  const { selectedTheme, dataTheme, isCustom, overrides } = resolveEffectiveTheme(settings);

  root.dataset.theme = dataTheme;
  root.dataset.customTheme = isCustom ? '1' : '0';

  if (isCustom) {
    applyThemeOverrideStyles(overrides);
  } else {
    clearThemeOverrideStyles();
  }

  const uiSize = normalizeUiSize(settings.launcher_ui_size);
  root.dataset.uiSize = uiSize;
  applyUiSizeZoom(uiSize);
  root.dataset.layoutDensity = normalizeLayoutDensity(settings.layout_density);
  root.dataset.compactSidebar = isTruthySetting(settings.compact_sidebar, false) ? '1' : '0';

  syncSidebarAccessibility();
  applyIconVariantPreference(document);
  window.dispatchEvent(new CustomEvent('histolauncher:appearance-changed', {
    detail: { theme: selectedTheme, baseTheme: dataTheme, isCustom },
  }));
};

export const initAppearanceObserver = () => {
  if (observerStarted) return;
  observerStarted = true;

  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.type === 'childList') {
        mutation.addedNodes.forEach((node) => {
          if (node instanceof HTMLImageElement) {
            const wrap = { querySelectorAll: () => [node] };
            applyIconVariantPreference(wrap);
          } else if (node instanceof Element) {
            applyIconVariantPreference(node);
          }
        });
      }
      if (mutation.type === 'attributes' && mutation.target instanceof HTMLImageElement) {
        const wrap = { querySelectorAll: () => [mutation.target] };
        applyIconVariantPreference(wrap);
      }
    });
  });

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['src'],
  });

  syncSidebarAccessibility();
  applyIconVariantPreference(document);
};
