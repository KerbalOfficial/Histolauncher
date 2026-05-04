// ui/modules/appearance.js

export const APPEARANCE_SETTING_KEYS = new Set([
  'launcher_theme',
  'launcher_ui_size',
  'layout_density',
  'compact_sidebar',
]);

const VALID_THEMES = new Set([
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
  'aero-dark',
  'aero-light',
]);

const LIGHT_THEMES = new Set([
  'light',
  'light-contrast',
  'chocolate-light',
  'strawberry-light',
  'blueberry-light',
  'leaf-light',
  'aero-light',
]);

const UNFILLED_ICON_RE = /(^|\/)unfilled_([a-z0-9_-]+\.(?:png|gif|jpg|jpeg|webp|svg))(\?|#|$)/i;
const DARK_UNFILLED_ICON_RE = /(^|\/)dark_unfilled_([a-z0-9_-]+\.(?:png|gif|jpg|jpeg|webp|svg))(\?|#|$)/i;

const DARKABLE_ICON_NAMES = new Set([
  'info.png',
]);
const DARKABLE_ICON_RE = new RegExp(
  `(^|/)(${Array.from(DARKABLE_ICON_NAMES).map((n) => n.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')).join('|')})(\\?|#|$)`,
  'i',
);
const DARKED_ICON_RE = new RegExp(
  `(^|/)dark_(${Array.from(DARKABLE_ICON_NAMES).map((n) => n.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')).join('|')})(\\?|#|$)`,
  'i',
);

let observerStarted = false;

export const isTruthySetting = (value, defaultValue = false) => {
  if (value === undefined || value === null || value === '') return defaultValue;
  return ['1', 'true', 'yes', 'on'].includes(String(value).trim().toLowerCase());
};

const normalizeTheme = (value) => {
  const theme = String(value || 'dark').trim().toLowerCase();
  return VALID_THEMES.has(theme) ? theme : 'dark';
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
  root.dataset.theme = normalizeTheme(settings.launcher_theme);
  const uiSize = normalizeUiSize(settings.launcher_ui_size);
  root.dataset.uiSize = uiSize;
  applyUiSizeZoom(uiSize);
  root.dataset.layoutDensity = normalizeLayoutDensity(settings.layout_density);
  root.dataset.compactSidebar = isTruthySetting(settings.compact_sidebar, false) ? '1' : '0';

  syncSidebarAccessibility();
  applyIconVariantPreference(document);
  window.dispatchEvent(new CustomEvent('histolauncher:appearance-changed'));
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
