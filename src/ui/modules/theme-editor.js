// ui/modules/theme-editor.js

import { getEl } from './dom-utils.js';
import { t } from './i18n.js';
import { state } from './state.js';
import {
  CUSTOM_THEME,
  PRESET_THEMES,
  applyAppearanceSettings,
  applyThemeOverrideStyles,
  clearThemeOverrideStyles,
  parseThemeOverrides,
  resolveEffectiveTheme,
  serializeThemeOverrides,
} from './appearance.js';

export const THEME_EDITOR_GROUPS = [
  {
    id: 'app',
    tokens: ['--color-app-bg'],
  },
  {
    id: 'text',
    tokens: [
      '--color-text-primary',
      '--color-text-secondary',
      '--color-text-secondary-strong',
      '--color-text-muted',
      '--color-text-dim',
      '--color-text-soft',
      '--color-text-soft-alt',
      '--color-text-softer',
      '--color-text-faint',
      '--color-text-title',
      '--color-text-title-strong',
      '--color-text-control',
      '--color-text-inverse',
      '--color-text-paragraph',
      '--color-text-disabled',
      '--color-text-danger-muted',
    ],
  },
  {
    id: 'links',
    tokens: ['--color-link', '--color-link-hover', '--color-focus'],
  },
  {
    id: 'surfaces',
    tokens: [
      '--color-surface-black',
      '--color-surface-panel',
      '--color-surface-card',
      '--color-surface-card-hover',
      '--color-surface-card-strong',
      '--color-surface-control',
      '--color-surface-list',
      '--color-surface-input',
      '--color-surface-interactive',
      '--color-surface-interactive-hover',
      '--color-surface-code',
      '--color-surface-code-inline',
      '--color-surface-code-block',
    ],
  },
  {
    id: 'borders',
    tokens: [
      '--color-border-strong',
      '--color-border-default',
      '--color-border-soft',
      '--color-border-subtle',
      '--color-border-light',
      '--color-border-button',
      '--color-border-input',
      '--color-border-input-strong',
      '--color-border-muted',
      '--color-border-code',
      '--color-border-quiet',
    ],
  },
  {
    id: 'overlays',
    tokens: [
      '--color-overlay-heavy',
      '--color-overlay-soft',
      '--color-overlay-medium',
      '--color-overlay-modal',
      '--color-overlay-subtle',
      '--color-divider-light',
      '--color-tooltip-bg',
    ],
  },
  {
    id: 'buttons',
    tokens: [
      '--color-button-bg',
      '--color-button-success-text',
      '--color-button-warning-text',
      '--color-button-info-text',
      '--color-button-danger-text',
    ],
  },
  {
    id: 'semantic',
    tokens: [
      '--color-success',
      '--color-success-border',
      '--color-success-hover',
      '--color-danger',
      '--color-danger-border',
      '--color-danger-hover',
      '--color-warning',
      '--color-warning-border',
      '--color-warning-hover',
      '--color-info',
      '--color-info-border',
      '--color-info-hover',
      '--color-launch',
      '--color-launch-border',
      '--color-launch-hover',
      '--color-error',
      '--color-error-soft',
      '--color-live',
      '--color-live-bg',
    ],
  },
  {
    id: 'messages',
    tokens: [
      '--color-message-info-bg',
      '--color-message-info-text',
      '--color-message-info-border',
      '--color-message-warning-bg',
      '--color-message-warning-text',
      '--color-message-warning-border',
      '--color-message-danger-bg',
      '--color-message-danger-text',
      '--color-message-danger-border',
    ],
  },
  {
    id: 'states',
    tokens: [
      '--color-selection-bg',
      '--color-selection-border',
      '--color-invalid-bg',
      '--color-progress-paused',
      '--color-favorite-bg',
      '--color-favorite-hover-bg',
      '--color-favorite-border',
      '--color-favorite-border-hover',
      '--color-favorite-border-selected',
      '--color-recent-bg',
      '--color-recent-border',
      '--color-recommended-bg',
      '--color-recommended-hover-bg',
      '--color-mod-card-hover-bg',
      '--color-mod-card-hover-border',
      '--color-control-hover-bg',
    ],
  },
  {
    id: 'scrollbars',
    tokens: [
      '--color-scrollbar-thumb',
      '--color-scrollbar-thumb-border',
      '--color-scrollbar-thumb-hover',
      '--color-scrollbar-info-track',
      '--color-scrollbar-info-track-border',
      '--color-scrollbar-warning-track',
      '--color-scrollbar-warning-track-border',
      '--color-scrollbar-danger-track',
      '--color-scrollbar-danger-track-border',
      '--color-scrollbar-info-thumb',
      '--color-scrollbar-info-thumb-border',
      '--color-scrollbar-warning-thumb',
      '--color-scrollbar-danger-thumb',
      '--color-scrollbar-info-thumb-hover',
      '--color-scrollbar-warning-thumb-hover',
      '--color-scrollbar-danger-thumb-hover',
    ],
  },
  {
    id: 'badges',
    tokens: [
      '--color-badge-installed-bg',
      '--color-badge-installed-border',
      '--color-badge-installed-text',
      '--color-badge-imported-bg',
      '--color-badge-imported-border',
      '--color-badge-imported-text',
      '--color-badge-modpack-bg',
      '--color-badge-modpack-border',
      '--color-badge-modpack-text',
      '--color-badge-available-bg',
      '--color-badge-available-border',
      '--color-badge-available-text',
      '--color-badge-official-bg',
      '--color-badge-official-border',
      '--color-badge-official-text',
      '--color-badge-nonofficial-bg',
      '--color-badge-nonofficial-border',
      '--color-badge-nonofficial-text',
      '--color-badge-paused-bg',
      '--color-badge-paused-border',
      '--color-badge-paused-text',
      '--color-badge-lite-bg',
      '--color-badge-lite-border',
      '--color-badge-lite-text',
      '--color-badge-size-bg',
      '--color-badge-size-border',
      '--color-badge-release-bg',
      '--color-badge-release-border',
      '--color-badge-release-text',
      '--color-badge-beta-bg',
      '--color-badge-beta-border',
      '--color-badge-beta-text',
      '--color-badge-alpha-bg',
      '--color-badge-alpha-border',
      '--color-badge-alpha-text',
    ],
  },
  {
    id: 'loaders',
    tokens: [
      '--color-loader-fabric-button-bg',
      '--color-loader-fabric-button-border',
      '--color-loader-fabric-button-text',
      '--color-loader-fabric-button-hover',
      '--color-loader-forge-button-bg',
      '--color-loader-forge-button-border',
      '--color-loader-forge-button-text',
      '--color-loader-forge-button-hover',
      '--color-loader-liteloader-button-bg',
      '--color-loader-liteloader-button-border',
      '--color-loader-liteloader-button-text',
      '--color-loader-liteloader-button-hover',
      '--color-loader-modloader-button-bg',
      '--color-loader-modloader-button-border',
      '--color-loader-modloader-button-text',
      '--color-loader-modloader-button-hover',
      '--color-loader-neoforge-button-bg',
      '--color-loader-neoforge-button-border',
      '--color-loader-neoforge-button-text',
      '--color-loader-neoforge-button-hover',
      '--color-loader-quilt-button-bg',
      '--color-loader-quilt-button-border',
      '--color-loader-quilt-button-text',
      '--color-loader-quilt-button-hover',
      '--color-loader-fabric-card-bg',
      '--color-loader-fabric-card-border',
      '--color-loader-fabric-card-hover',
      '--color-loader-fabric-card-hover-border',
      '--color-loader-forge-card-bg',
      '--color-loader-forge-card-border',
      '--color-loader-forge-card-hover',
      '--color-loader-forge-card-hover-border',
      '--color-loader-liteloader-card-bg',
      '--color-loader-liteloader-card-border',
      '--color-loader-liteloader-card-hover',
      '--color-loader-liteloader-card-hover-border',
      '--color-loader-modloader-card-bg',
      '--color-loader-modloader-card-border',
      '--color-loader-modloader-card-hover',
      '--color-loader-modloader-card-hover-border',
      '--color-loader-neoforge-card-bg',
      '--color-loader-neoforge-card-border',
      '--color-loader-neoforge-card-hover',
      '--color-loader-neoforge-card-hover-border',
      '--color-loader-quilt-card-bg',
      '--color-loader-quilt-card-border',
      '--color-loader-quilt-card-hover',
      '--color-loader-quilt-card-hover-border',
    ],
  },
];

const toPickerValue = (value) => {
  const raw = String(value || '').trim();
  const hexMatch = raw.match(/^#([0-9a-f]{3,8})$/i);
  if (hexMatch) {
    let hex = hexMatch[1];
    if (hex.length === 3) {
      hex = hex.split('').map((c) => c + c).join('');
    }
    if (hex.length >= 6) {
      return `#${hex.slice(0, 6)}`;
    }
  }
  const rgbaMatch = raw.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
  if (rgbaMatch) {
    const r = Number(rgbaMatch[1]).toString(16).padStart(2, '0');
    const g = Number(rgbaMatch[2]).toString(16).padStart(2, '0');
    const b = Number(rgbaMatch[3]).toString(16).padStart(2, '0');
    return `#${r}${g}${b}`;
  }
  return '#000000';
};

const tokenLabel = (token) => token.replace(/^--color-/, '').replace(/-/g, ' ');

const DOCK_OPEN_KEY = 'histolauncher:theme-editor-dock-open';
const DOCK_COLLAPSED_KEY = 'histolauncher:theme-editor-dock-collapsed';
const DOCK_SIZE_KEY = 'histolauncher:theme-editor-dock-size';
const DOCK_POS_KEY = 'histolauncher:theme-editor-dock-pos';
const DOCK_MARGIN = 8;
const DOCK_MIN_WIDTH = 280;
const DOCK_MIN_HEIGHT = 200;
const DOCK_MAX_WIDTH_CAP = 920;
const DOCK_MAX_HEIGHT_CAP = 720;
const DOCK_DEFAULT_WIDTH = 340;
const DOCK_DEFAULT_HEIGHT = 360;

let editorInitialized = false;
let autoSaveSettingRef = null;
let dockDragState = null;
let dockResizeState = null;

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const dockMaxWidth = () => Math.max(
  DOCK_MIN_WIDTH,
  Math.min(DOCK_MAX_WIDTH_CAP, window.innerWidth - DOCK_MARGIN * 2),
);

const dockMaxHeight = () => Math.max(
  DOCK_MIN_HEIGHT,
  Math.min(DOCK_MAX_HEIGHT_CAP, window.innerHeight - DOCK_MARGIN * 2),
);

const dockDefaultWidth = () => Math.min(DOCK_DEFAULT_WIDTH, dockMaxWidth());

const dockDefaultHeight = () => {
  const viewportCap = Math.max(240, Math.round(window.innerHeight * 0.32));
  return Math.min(DOCK_DEFAULT_HEIGHT, viewportCap, dockMaxHeight());
};

const readDockSize = () => {
  try {
    const raw = sessionStorage.getItem(DOCK_SIZE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.w !== 'number' || typeof parsed.h !== 'number') return null;
    return { w: parsed.w, h: parsed.h };
  } catch {
    return null;
  }
};

const readDockPos = () => {
  try {
    const raw = sessionStorage.getItem(DOCK_POS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.left !== 'number' || typeof parsed.top !== 'number') return null;
    return { left: parsed.left, top: parsed.top };
  } catch {
    return null;
  }
};

const persistDockGeometry = (dock) => {
  if (!dock) return;
  const rect = dock.getBoundingClientRect();
  try {
    const previousSize = readDockSize();
    const nextSize = {
      w: Math.round(rect.width),
      h: dock.classList.contains('is-collapsed')
        ? (previousSize?.h ?? dockDefaultHeight())
        : Math.round(rect.height),
    };
    sessionStorage.setItem(DOCK_SIZE_KEY, JSON.stringify(nextSize));
    sessionStorage.setItem(DOCK_POS_KEY, JSON.stringify({
      left: Math.round(rect.left),
      top: Math.round(rect.top),
    }));
  } catch {
    /* ignore */
  }
};

const applyDockGeometry = (dock, { persist = false } = {}) => {
  if (!dock || dock.classList.contains('is-collapsed')) return;

  const maxW = dockMaxWidth();
  const maxH = dockMaxHeight();
  const savedSize = readDockSize();
  const savedPos = readDockPos();

  let width = clamp(savedSize?.w ?? dockDefaultWidth(), DOCK_MIN_WIDTH, maxW);
  let height = clamp(savedSize?.h ?? dockDefaultHeight(), DOCK_MIN_HEIGHT, maxH);

  let left;
  let top;
  if (savedPos) {
    left = clamp(savedPos.left, DOCK_MARGIN, Math.max(DOCK_MARGIN, window.innerWidth - width - DOCK_MARGIN));
    top = clamp(savedPos.top, DOCK_MARGIN, Math.max(DOCK_MARGIN, window.innerHeight - height - DOCK_MARGIN));
  } else {
    left = Math.max(DOCK_MARGIN, window.innerWidth - width - 16);
    top = Math.max(DOCK_MARGIN, window.innerHeight - height - 16);
  }

  dock.style.width = `${width}px`;
  dock.style.height = `${height}px`;
  dock.style.left = `${left}px`;
  dock.style.top = `${top}px`;
  dock.style.right = 'auto';
  dock.style.bottom = 'auto';

  if (persist) {
    persistDockGeometry(dock);
  }
};

const isCustomThemeActive = () => state.settingsState.launcher_theme === CUSTOM_THEME;

const setDockOpen = (open, { remember = true } = {}) => {
  const dock = getEl('theme-editor-dock');
  if (!dock) return;
  dock.hidden = !open;
  dock.classList.toggle('hidden', !open);
  if (remember) {
    try {
      sessionStorage.setItem(DOCK_OPEN_KEY, open ? '1' : '0');
    } catch {
      /* ignore */
    }
  }
  if (open) {
    populateBaseThemeSelect();
    rebuildEditorGroups();
    applyDockGeometry(dock);
  }
};

const readDockOpenPreference = () => {
  try {
    return sessionStorage.getItem(DOCK_OPEN_KEY) === '1';
  } catch {
    return false;
  }
};

const setDockCollapsed = (collapsed, { remember = true } = {}) => {
  const dock = getEl('theme-editor-dock');
  const collapseBtn = getEl('theme-editor-dock-collapse');
  if (!dock) return;
  dock.classList.toggle('is-collapsed', collapsed);
  if (collapseBtn) {
    collapseBtn.textContent = collapsed ? '+' : '−';
    collapseBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }
  if (remember) {
    try {
      sessionStorage.setItem(DOCK_COLLAPSED_KEY, collapsed ? '1' : '0');
    } catch {
      /* ignore */
    }
  }
  if (!collapsed) {
    applyDockGeometry(dock);
  }
};

const readDockCollapsedPreference = () => {
  try {
    return sessionStorage.getItem(DOCK_COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
};

const initDockDrag = () => {
  const dock = getEl('theme-editor-dock');
  const handle = getEl('theme-editor-dock-handle');
  if (!dock || !handle || handle.dataset.dragBound === '1') return;
  handle.dataset.dragBound = '1';

  handle.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    if (event.target.closest('button')) return;
    const rect = dock.getBoundingClientRect();
    dockDragState = {
      pointerId: event.pointerId,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      width: rect.width,
      height: rect.height,
    };
    dock.style.left = `${rect.left}px`;
    dock.style.top = `${rect.top}px`;
    dock.style.right = 'auto';
    dock.style.bottom = 'auto';
    handle.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  handle.addEventListener('pointermove', (event) => {
    if (!dockDragState || event.pointerId !== dockDragState.pointerId) return;
    const maxLeft = Math.max(8, window.innerWidth - dockDragState.width - 8);
    const maxTop = Math.max(8, window.innerHeight - dockDragState.height - 8);
    const left = Math.min(maxLeft, Math.max(8, event.clientX - dockDragState.offsetX));
    const top = Math.min(maxTop, Math.max(8, event.clientY - dockDragState.offsetY));
    dock.style.left = `${left}px`;
    dock.style.top = `${top}px`;
  });

  const endDrag = (event) => {
    if (!dockDragState || event.pointerId !== dockDragState.pointerId) return;
    dockDragState = null;
    try {
      handle.releasePointerCapture(event.pointerId);
    } catch {
      /* ignore */
    }
    persistDockGeometry(dock);
  };

  handle.addEventListener('pointerup', endDrag);
  handle.addEventListener('pointercancel', endDrag);
};

const initDockResize = () => {
  const dock = getEl('theme-editor-dock');
  if (!dock || dock.dataset.resizeBound === '1') return;
  dock.dataset.resizeBound = '1';

  const onResizeMove = (event) => {
    if (!dockResizeState || event.pointerId !== dockResizeState.pointerId) return;

    const { edge, startX, startY, startRect } = dockResizeState;
    const dx = event.clientX - startX;
    const dy = event.clientY - startY;
    const maxW = dockMaxWidth();
    const maxH = dockMaxHeight();

    let left = startRect.left;
    let top = startRect.top;
    let width = startRect.width;
    let height = startRect.height;

    if (edge.includes('e')) width = startRect.width + dx;
    if (edge.includes('w')) {
      width = startRect.width - dx;
      left = startRect.left + dx;
    }
    if (edge.includes('s')) height = startRect.height + dy;
    if (edge.includes('n')) {
      height = startRect.height - dy;
      top = startRect.top + dy;
    }

    width = clamp(width, DOCK_MIN_WIDTH, maxW);
    height = clamp(height, DOCK_MIN_HEIGHT, maxH);

    if (edge.includes('w')) left = startRect.left + startRect.width - width;
    if (edge.includes('n')) top = startRect.top + startRect.height - height;

    left = clamp(left, DOCK_MARGIN, Math.max(DOCK_MARGIN, window.innerWidth - width - DOCK_MARGIN));
    top = clamp(top, DOCK_MARGIN, Math.max(DOCK_MARGIN, window.innerHeight - height - DOCK_MARGIN));

    dock.style.width = `${width}px`;
    dock.style.height = `${height}px`;
    dock.style.left = `${left}px`;
    dock.style.top = `${top}px`;
    dock.style.right = 'auto';
    dock.style.bottom = 'auto';
  };

  const endResize = (event) => {
    if (!dockResizeState || event.pointerId !== dockResizeState.pointerId) return;
    dockResizeState = null;
    persistDockGeometry(dock);
  };

  dock.querySelectorAll('.theme-editor-dock-resize-handle').forEach((handle) => {
    handle.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      const edge = handle.dataset.resize || '';
      if (dock.classList.contains('is-collapsed') && edge !== 'e' && edge !== 'w') return;

      event.preventDefault();
      event.stopPropagation();

      const rect = dock.getBoundingClientRect();
      dock.style.left = `${rect.left}px`;
      dock.style.top = `${rect.top}px`;
      dock.style.right = 'auto';
      dock.style.bottom = 'auto';

      dockResizeState = {
        pointerId: event.pointerId,
        edge,
        startX: event.clientX,
        startY: event.clientY,
        startRect: {
          left: rect.left,
          top: rect.top,
          width: rect.width,
          height: rect.height,
        },
      };
      handle.setPointerCapture(event.pointerId);
    });

    handle.addEventListener('pointermove', onResizeMove);
    handle.addEventListener('pointerup', endResize);
    handle.addEventListener('pointercancel', endResize);
  });
};

const initDockViewportClamp = () => {
  window.addEventListener('resize', () => {
    const dock = getEl('theme-editor-dock');
    if (!dock || dock.hidden) return;
    applyDockGeometry(dock, { persist: true });
  });
};

const readComputedTokens = (tokens, baseTheme) => {
  const root = document.documentElement;
  const previousTheme = root.dataset.theme;
  const previousCustom = root.dataset.customTheme;
  root.dataset.theme = baseTheme;
  root.dataset.customTheme = '0';
  clearThemeOverrideStyles();
  const computed = getComputedStyle(root);
  const values = {};
  tokens.forEach((token) => {
    values[token] = computed.getPropertyValue(token).trim();
  });
  root.dataset.theme = previousTheme;
  root.dataset.customTheme = previousCustom;
  applyAppearanceSettings(state.settingsState);
  return values;
};

const persistOverrides = (overrides) => {
  const serialized = serializeThemeOverrides(overrides);
  state.settingsState.launcher_theme_overrides = serialized;
  if (autoSaveSettingRef) {
    autoSaveSettingRef('launcher_theme_overrides', serialized);
  }
};

const setOverrideToken = (token, value, overrides) => {
  const next = { ...overrides };
  if (value) {
    next[token] = value;
  } else {
    delete next[token];
  }
  persistOverrides(next);
  applyThemeOverrideStyles(next);
};

const buildTokenRow = (token, overrides, baseValues) => {
  const row = document.createElement('div');
  row.className = 'theme-token-row';
  row.dataset.token = token;

  const label = document.createElement('label');
  label.className = 'theme-token-label';
  label.textContent = tokenLabel(token);
  label.title = token;

  const picker = document.createElement('input');
  picker.type = 'color';
  picker.className = 'theme-token-picker';

  const text = document.createElement('input');
  text.type = 'text';
  text.className = 'theme-token-value';
  text.spellcheck = false;

  const resetBtn = document.createElement('button');
  resetBtn.type = 'button';
  resetBtn.className = 'theme-token-reset';
  resetBtn.textContent = t('settings.appearance.themeEditor.resetToken');
  resetBtn.title = t('settings.appearance.themeEditor.resetTokenTooltip');

  const syncFromOverrides = () => {
    const currentOverrides = parseThemeOverrides(state.settingsState.launcher_theme_overrides);
    const overrideValue = currentOverrides[token];
    const displayValue = overrideValue || baseValues[token] || '';
    text.value = displayValue;
    picker.value = toPickerValue(displayValue);
    row.classList.toggle('is-customized', Boolean(overrideValue));
  };

  picker.addEventListener('input', () => {
    text.value = picker.value;
    setOverrideToken(token, picker.value, parseThemeOverrides(state.settingsState.launcher_theme_overrides));
    row.classList.add('is-customized');
  });

  text.addEventListener('change', () => {
    const value = text.value.trim();
    if (!value) {
      setOverrideToken(token, '', parseThemeOverrides(state.settingsState.launcher_theme_overrides));
      syncFromOverrides();
      return;
    }
    picker.value = toPickerValue(value);
    setOverrideToken(token, value, parseThemeOverrides(state.settingsState.launcher_theme_overrides));
    row.classList.add('is-customized');
  });

  resetBtn.addEventListener('click', () => {
    setOverrideToken(token, '', parseThemeOverrides(state.settingsState.launcher_theme_overrides));
    syncFromOverrides();
  });

  row.append(label, picker, text, resetBtn);
  syncFromOverrides();
  return row;
};

const rebuildEditorGroups = () => {
  const host = getEl('theme-editor-groups');
  if (!host) return;

  const { baseTheme } = resolveEffectiveTheme(state.settingsState);
  const overrides = parseThemeOverrides(state.settingsState.launcher_theme_overrides);
  host.innerHTML = '';

  const allTokens = THEME_EDITOR_GROUPS.flatMap((group) => group.tokens);
  const baseValues = readComputedTokens(allTokens, baseTheme);

  THEME_EDITOR_GROUPS.forEach((group) => {
    const section = document.createElement('details');
    section.className = 'theme-editor-group';
    section.open = group.id === 'app' || group.id === 'text' || group.id === 'surfaces';

    const summary = document.createElement('summary');
    summary.textContent = t(`settings.appearance.themeEditor.groups.${group.id}`);
    section.appendChild(summary);

    const list = document.createElement('div');
    list.className = 'theme-editor-token-list';
    group.tokens.forEach((token) => {
      list.appendChild(buildTokenRow(token, overrides, baseValues));
    });
    section.appendChild(list);
    host.appendChild(section);
  });
};

const populateBaseThemeSelect = () => {
  const select = getEl('settings-launcher-theme-base');
  if (!select) return;
  if (!select.options.length) {
    PRESET_THEMES.forEach((themeId) => {
      const option = document.createElement('option');
      option.value = themeId;
      option.textContent = t(`settings.appearance.themes.${themeIdToI18nKey(themeId)}`);
      select.appendChild(option);
    });
  }
  const baseTheme = state.settingsState.launcher_theme_base || 'dark';
  select.value = PRESET_THEMES.includes(baseTheme) ? baseTheme : 'dark';
};

export const themeIdToI18nKey = (themeId) => {
  return themeId.replace(/-([a-z])/g, (_m, c) => c.toUpperCase());
};

const syncCustomSettingsRow = () => {
  const row = getEl('theme-editor-open-dock');
  if (!row) return;
  row.hidden = !isCustomThemeActive();
};

const syncThemeEditorDock = () => {
  syncCustomSettingsRow();
  if (!isCustomThemeActive()) {
    setDockOpen(false, { remember: false });
    return;
  }
  if (readDockOpenPreference()) {
    setDockOpen(true);
    setDockCollapsed(readDockCollapsedPreference(), { remember: false });
  } else {
    setDockOpen(false, { remember: false });
  }
};

export const syncThemeEditor = () => {
  populateBaseThemeSelect();
  syncThemeEditorDock();
};

export const openThemeEditorDock = () => {
  if (!isCustomThemeActive()) return;
  setDockOpen(true);
  setDockCollapsed(false);
};

export const initThemeEditor = (autoSaveSetting) => {
  if (editorInitialized) return;
  editorInitialized = true;
  autoSaveSettingRef = autoSaveSetting;

  initDockDrag();
  initDockResize();
  initDockViewportClamp();

  const themeSelect = getEl('settings-launcher-theme');
  if (themeSelect) {
    themeSelect.addEventListener('change', () => {
      syncThemeEditorDock();
    });
  }

  const openDockBtn = getEl('theme-editor-open-dock');
  if (openDockBtn) {
    openDockBtn.addEventListener('click', () => {
      openThemeEditorDock();
    });
  }

  const closeDockBtn = getEl('theme-editor-dock-close');
  if (closeDockBtn) {
    closeDockBtn.addEventListener('click', () => {
      setDockOpen(false);
    });
  }

  const collapseDockBtn = getEl('theme-editor-dock-collapse');
  if (collapseDockBtn) {
    collapseDockBtn.addEventListener('click', () => {
      const dock = getEl('theme-editor-dock');
      setDockCollapsed(!dock?.classList.contains('is-collapsed'));
    });
  }

  const baseSelect = getEl('settings-launcher-theme-base');
  if (baseSelect) {
    baseSelect.addEventListener('change', (e) => {
      autoSaveSetting('launcher_theme_base', e.target.value || 'dark');
      rebuildEditorGroups();
    });
  }

  const resetAllBtn = getEl('theme-editor-reset-all');
  if (resetAllBtn) {
    resetAllBtn.addEventListener('click', () => {
      persistOverrides({});
      clearThemeOverrideStyles();
      applyAppearanceSettings(state.settingsState);
      rebuildEditorGroups();
    });
  }

  const exportBtn = getEl('theme-editor-export');
  if (exportBtn) {
    exportBtn.addEventListener('click', async () => {
      const payload = {
        base: state.settingsState.launcher_theme_base || 'dark',
        overrides: parseThemeOverrides(state.settingsState.launcher_theme_overrides),
      };
      const text = JSON.stringify(payload, null, 2);
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const area = document.createElement('textarea');
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        area.remove();
      }
    });
  }

  const importBtn = getEl('theme-editor-import');
  const importInput = getEl('theme-editor-import-input');
  if (importBtn && importInput) {
    importBtn.addEventListener('click', () => importInput.click());
    importInput.addEventListener('change', async () => {
      const file = importInput.files?.[0];
      importInput.value = '';
      if (!file) return;
      try {
        const parsed = JSON.parse(await file.text());
        const base = PRESET_THEMES.includes(parsed?.base) ? parsed.base : 'dark';
        const overrides = typeof parsed?.overrides === 'object' && parsed.overrides ? parsed.overrides : {};
        state.settingsState.launcher_theme = CUSTOM_THEME;
        state.settingsState.launcher_theme_base = base;
        if (themeSelect) themeSelect.value = CUSTOM_THEME;
        autoSaveSetting('launcher_theme', CUSTOM_THEME);
        autoSaveSetting('launcher_theme_base', base);
        persistOverrides(overrides);
        applyAppearanceSettings(state.settingsState);
        openThemeEditorDock();
      } catch (err) {
        console.warn('Failed to import theme:', err);
      }
    });
  }

  syncThemeEditorDock();
};
