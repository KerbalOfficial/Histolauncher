// ui/modules/mods.js

import { state } from './state.js';
import {
  $,
  $$,
  getEl,
  bindKeyboardActivation,
  wireCardActionArrowNavigation,
  imageAttachErrorPlaceholder,
  isShiftDelete,
} from './dom-utils.js';
import {
  LOADER_UI_ORDER,
  LOADER_UI_CONFIG,
  SHADER_TYPE_ORDER,
  ADD_PROFILE_OPTION,
  getLoaderUi,
  getShaderTypeUi,
  normalizeAddonCompatibilityToken,
  unicodeList,
} from './config.js';
import { api, createOperationId, requestOperationCancel } from './api.js';
import { showMessageBox } from './modal.js';
import {
  showLoadingOverlay,
  hideLoadingOverlay,
  setLoadingOverlayText,
} from './modal.js';
import { refreshActionOverflowMenus } from './action-overflow.js';
import { renderCommonPagination } from './pagination.js';
import { formatBytes } from './string-utils.js';
import { createEmptyState, createInlineLoadingState } from './ui-states.js';
import { t } from './i18n.js';

const _deps = {};
for (const k of ['autoSaveSetting', 'isTruthySetting', 'renderScopeProfilesSelect', 'showCreateScopeProfileModal', 'showDeleteScopeProfileModal', 'showRenameScopeProfileModal', 'switchScopeProfile', 'updateScopeProfileDeleteButtonState', 'updateScopeProfileEditButtonState']) {
  Object.defineProperty(_deps, k, {
    configurable: true,
    enumerable: true,
    get() { throw new Error(`mods.js: dep "${k}" was not configured. Call setModsDeps() first.`); },
  });
}

export const setModsDeps = (deps) => {
  for (const k of Object.keys(deps)) {
    Object.defineProperty(_deps, k, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: deps[k],
    });
  }
};

// ---------------- Mods Page ----------------

const MODS_PAGE_SIZE = 20;

let modsState = {
  addonType: 'mods',
  provider: 'modrinth',
  modLoader: '',
  gameVersion: '',
  category: '',
  sortBy: 'relevance',
  searchQuery: '',
  currentPage: 1,
  totalPages: 1,
  categoryOptions: [],
  availableModsRaw: [],
  availableMods: [],
  installedMods: [],
  installedModpacks: [],
  searchRequestId: 0,
  lastError: null,
  installedGroupsCollapsed: {
    modpacks: false,
    fabric: false,
    forge: false,
    neoforge: false,
    quilt: false,
    other: false,
  },
};

let modsLanguageListenerBound = false;

const ADDON_TYPE_CONFIG = {
  mods: {
    label: 'Mods',
    labelKey: 'mods.addonTypes.mods.label',
    singular: 'mod',
    singularKey: 'mods.addonTypes.mods.singular',
    singularTitle: 'Mod',
    singularTitleKey: 'mods.addonTypes.mods.singularTitle',
    plural: 'mods',
    pluralKey: 'mods.addonTypes.mods.plural',
    pluralTitle: 'Mods',
    pluralTitleKey: 'mods.addonTypes.mods.pluralTitle',
    defaultIcon: 'assets/images/java_icon.png',
    importAccept: '.jar,.zip',
    supportsLoader: true,
    supportsCategory: true,
    supportsMove: true,
    supportsModpacks: false,
    importTitle: 'Import Mod',
    importTitleKey: 'mods.addonTypes.mods.importTitle',
    importDescription: 'Select the mod loader for',
    importDescriptionKey: 'mods.addonTypes.mods.importDescription',
    emptyInstalled: 'No mods installed',
    emptyInstalledKey: 'mods.addonTypes.mods.emptyInstalled',
    emptyAvailable: 'No mods found',
    emptyAvailableKey: 'mods.addonTypes.mods.emptyAvailable',
  },
  modpacks: {
    label: 'Modpacks',
    labelKey: 'mods.addonTypes.modpacks.label',
    singular: 'modpack',
    singularKey: 'mods.addonTypes.modpacks.singular',
    singularTitle: 'Modpack',
    singularTitleKey: 'mods.addonTypes.modpacks.singularTitle',
    plural: 'modpacks',
    pluralKey: 'mods.addonTypes.modpacks.plural',
    pluralTitle: 'Modpacks',
    pluralTitleKey: 'mods.addonTypes.modpacks.pluralTitle',
    defaultIcon: 'assets/images/java_icon.png',
    importAccept: '.hlmp,.mrpack,.zip',
    supportsLoader: true,
    supportsCategory: true,
    supportsMove: false,
    supportsModpacks: true,
    importTitle: 'Import Modpack',
    importTitleKey: 'mods.addonTypes.modpacks.importTitle',
    emptyInstalled: 'No modpacks installed',
    emptyInstalledKey: 'mods.addonTypes.modpacks.emptyInstalled',
    emptyAvailable: 'No modpacks found',
    emptyAvailableKey: 'mods.addonTypes.modpacks.emptyAvailable',
  },
  resourcepacks: {
    label: 'Resource Packs',
    labelKey: 'mods.addonTypes.resourcepacks.label',
    singular: 'resource pack',
    singularKey: 'mods.addonTypes.resourcepacks.singular',
    singularTitle: 'Resource Pack',
    singularTitleKey: 'mods.addonTypes.resourcepacks.singularTitle',
    plural: 'resource packs',
    pluralKey: 'mods.addonTypes.resourcepacks.plural',
    pluralTitle: 'Resource Packs',
    pluralTitleKey: 'mods.addonTypes.resourcepacks.pluralTitle',
    defaultIcon: 'assets/images/placeholder_pack.png',
    importAccept: '.zip',
    supportsLoader: false,
    supportsCategory: true,
    supportsMove: false,
    supportsModpacks: false,
    importTitle: 'Import Resource Pack',
    importTitleKey: 'mods.addonTypes.resourcepacks.importTitle',
    emptyInstalled: 'No resource packs installed',
    emptyInstalledKey: 'mods.addonTypes.resourcepacks.emptyInstalled',
    emptyAvailable: 'No resource packs found',
    emptyAvailableKey: 'mods.addonTypes.resourcepacks.emptyAvailable',
  },
  shaderpacks: {
    label: 'Shader Packs',
    labelKey: 'mods.addonTypes.shaderpacks.label',
    singular: 'shader pack',
    singularKey: 'mods.addonTypes.shaderpacks.singular',
    singularTitle: 'Shader Pack',
    singularTitleKey: 'mods.addonTypes.shaderpacks.singularTitle',
    plural: 'shader packs',
    pluralKey: 'mods.addonTypes.shaderpacks.plural',
    pluralTitle: 'Shader Packs',
    pluralTitleKey: 'mods.addonTypes.shaderpacks.pluralTitle',
    defaultIcon: 'assets/images/placeholder_pack.png',
    importAccept: '.zip',
    supportsLoader: false,
    supportsCategory: true,
    supportsMove: false,
    supportsModpacks: false,
    importTitle: 'Import Shader Pack',
    importTitleKey: 'mods.addonTypes.shaderpacks.importTitle',
    emptyInstalled: 'No shader packs installed',
    emptyInstalledKey: 'mods.addonTypes.shaderpacks.emptyInstalled',
    emptyAvailable: 'No shader packs found',
    emptyAvailableKey: 'mods.addonTypes.shaderpacks.emptyAvailable',
  },
};

const getAddonConfig = (addonType = modsState.addonType) => {
  const key = String(addonType || 'mods').toLowerCase();
  return ADDON_TYPE_CONFIG[key] || ADDON_TYPE_CONFIG.mods;
};

const textOrFallback = (key, replacements = {}, fallback = '') => {
  const value = t(key, replacements);
  return value && value !== key ? value : fallback;
};

const getAddonConfigText = (field, addonType = modsState.addonType, replacements = {}) => {
  const config = getAddonConfig(addonType);
  const fallback = config[field] || '';
  const key = config[`${field}Key`];
  return key ? textOrFallback(key, replacements, fallback) : fallback;
};

const getProviderDisplayName = () => modsState.provider === 'modrinth'
  ? t('mods.providerModrinth')
  : t('mods.providerCurseforge');

const appendOption = (select, value, label) => {
  const option = document.createElement('option');
  option.value = value;
  option.textContent = label;
  select.appendChild(option);
  return option;
};

const isModsAddonType = (addonType = modsState.addonType) => String(addonType || 'mods').toLowerCase() === 'mods';
const isModpacksAddonType = (addonType = modsState.addonType) => String(addonType || 'mods').toLowerCase() === 'modpacks';
const isShaderpacksAddonType = (addonType = modsState.addonType) => String(addonType || 'mods').toLowerCase() === 'shaderpacks';
const getShaderTypeLabel = (shaderType) => {
  const shaderTypeUi = getShaderTypeUi(shaderType);
  return shaderTypeUi.nameKey ? t(shaderTypeUi.nameKey) : shaderTypeUi.name;
};
const getAddonCompatibilityFilterConfig = (addonType = modsState.addonType) => {
  const normalizedType = String(addonType || 'mods').toLowerCase();
  if (normalizedType === 'mods' || normalizedType === 'modpacks') {
    return {
      label: t('mods.compatibility.modLoader'),
      detailAllLabel: t('mods.compatibility.allLoaders'),
      options: LOADER_UI_ORDER.map((loaderType) => ({
        value: loaderType,
        label: getLoaderUi(loaderType).name,
      })),
    };
  }
  if (normalizedType === 'shaderpacks') {
    return {
      label: t('mods.compatibility.shaderType'),
      detailAllLabel: t('mods.compatibility.allShaderTypes'),
      options: SHADER_TYPE_ORDER.map((shaderType) => ({
        value: shaderType,
        label: getShaderTypeLabel(shaderType),
      })),
    };
  }
  return null;
};
const addonTypeSupportsCompatibilityFilter = (addonType = modsState.addonType) => !!getAddonCompatibilityFilterConfig(addonType);
const normalizeAddonCompatibilityValue = (addonType, value) => {
  const config = getAddonCompatibilityFilterConfig(addonType);
  if (!config) return '';
  const normalized = normalizeAddonCompatibilityToken(value);
  return config.options.some((option) => option.value === normalized) ? normalized : '';
};
const extractAddonCompatibilityValues = (values, addonType = modsState.addonType) => {
  const normalizedType = String(addonType || 'mods').toLowerCase();
  const config = getAddonCompatibilityFilterConfig(normalizedType);
  if (!config) return [];
  const rawValues = Array.isArray(values) ? values : [values];
  const seen = new Set();
  const normalizedValues = [];
  rawValues.forEach((value) => {
    const normalized = normalizeAddonCompatibilityToken(value);
    if (!normalized || seen.has(normalized)) return;
    if (!config.options.some((option) => option.value === normalized)) return;
    seen.add(normalized);
    normalizedValues.push(normalized);
  });
  return normalizedValues;
};
const getAddonCompatibilityValues = (entry, addonType = modsState.addonType) => {
  if (!entry) return [];
  if (isModsAddonType(addonType) || isModpacksAddonType(addonType)) {
    return extractAddonCompatibilityValues(
      entry.mod_loader || entry.compatibility_types || entry.loaders,
      addonType
    );
  }
  if (isShaderpacksAddonType(addonType)) {
    const explicit = extractAddonCompatibilityValues(entry.compatibility_types, addonType);
    if (explicit.length > 0) return explicit;
    const fallback = extractAddonCompatibilityValues(entry.mod_loader || entry.loaders, addonType);
    if (fallback.length > 0) return fallback;
  }
  return [];
};
const addonMatchesCompatibilityFilter = (
  entry,
  selectedValue = modsState.modLoader,
  addonType = modsState.addonType
) => {
  const normalizedSelected = normalizeAddonCompatibilityValue(addonType, selectedValue);
  if (!normalizedSelected) return true;
  return getAddonCompatibilityValues(entry, addonType).includes(normalizedSelected);
};
const versionMatchesCompatibilityFilter = (
  version,
  selectedValue = modsState.modLoader,
  addonType = modsState.addonType
) => {
  const normalizedSelected = normalizeAddonCompatibilityValue(addonType, selectedValue);
  if (!normalizedSelected) return true;
  return extractAddonCompatibilityValues(version && version.loaders, addonType).includes(normalizedSelected);
};
const getPreferredCompatibilityValue = (entry, addonType = modsState.addonType) => {
  const values = getAddonCompatibilityValues(entry, addonType);
  return values.length > 0 ? values[0] : '';
};
const getCompatibilityLabel = (addonType, value) => {
  const normalizedType = String(addonType || 'mods').toLowerCase();
  const normalizedValue = normalizeAddonCompatibilityToken(value);
  if (!normalizedValue) return '';
  if (normalizedType === 'mods' || normalizedType === 'modpacks') {
    return getLoaderUi(normalizedValue).name;
  }
  if (normalizedType === 'shaderpacks') {
    return getShaderTypeLabel(normalizedValue);
  }
  return normalizedValue.charAt(0).toUpperCase() + normalizedValue.slice(1);
};
const formatCompatibilityTag = (entry, addonType = modsState.addonType) => {
  const labels = getAddonCompatibilityValues(entry, addonType)
    .map((value) => getCompatibilityLabel(addonType, value))
    .filter(Boolean);
  return labels.length > 0 ? ` [${labels.join(', ')}]` : '';
};
const refreshModsCompatibilityOptions = () => {
  const loaderFilterItem = getEl('mods-loader-filter-item');
  const loaderSelect = getEl('mods-loader-select');
  const loaderLabel = document.querySelector('#mods-loader-filter-item label[for="mods-loader-select"]');
  const filterConfig = getAddonCompatibilityFilterConfig();

  if (loaderFilterItem) loaderFilterItem.classList.toggle('hidden', !filterConfig);
  if (loaderLabel) loaderLabel.textContent = `${filterConfig ? filterConfig.label : t('mods.compatibility.modLoader')}:`;
  if (!loaderSelect) return;

  const previousValue = normalizeAddonCompatibilityValue(
    modsState.addonType,
    modsState.modLoader || loaderSelect.value || ''
  );
  loaderSelect.innerHTML = '';

  appendOption(loaderSelect, '', t('common.all'));

  if (filterConfig) {
    filterConfig.options.forEach((optionData) => {
      const opt = document.createElement('option');
      opt.value = optionData.value;
      opt.textContent = optionData.label;
      loaderSelect.appendChild(opt);
    });
  }

  loaderSelect.value = previousValue;
  modsState.modLoader = previousValue;
};

const getModBulkKey = (mod) => {
  const addonType = String(mod.addon_type || modsState.addonType || 'mods').toLowerCase();
  const modSlug = String(mod.mod_slug || mod.slug || mod.id || mod.name || '').toLowerCase();
  if (addonType === 'mods') {
    return `${addonType}::${String(mod.mod_loader || '').toLowerCase()}::${modSlug}`;
  }
  return `${addonType}::${modSlug}`;
};

const parseModBulkKey = (key) => {
  const parts = String(key || '').split('::');
  if (parts.length === 3) {
    return {
      addon_type: parts[0],
      mod_loader: parts[1],
      mod_slug: parts[2],
    };
  }
  if (parts.length === 2) {
    return {
      addon_type: parts[0],
      mod_loader: '',
      mod_slug: parts[1],
    };
  }
  return null;
};

const pruneModsBulkSelection = () => {
  if (!state.modsBulkState.enabled) return;
  const source = isModpacksAddonType() ? (modsState.installedModpacks || []) : (modsState.installedMods || []);
  const installed = new Set(source.map((mod) => getModBulkKey(mod)));
  const next = new Set();
  state.modsBulkState.selected.forEach((key) => {
    if (installed.has(key)) next.add(key);
  });
  state.modsBulkState.selected = next;
};

const updateModsBulkActionsUI = () => {
  const config = getAddonConfig();
  const toggleBtn = getEl('mods-bulk-toggle-btn');
  const deleteBtn = getEl('mods-bulk-delete-btn');
  const moveBtn = getEl('mods-bulk-move-btn');
  const count = state.modsBulkState.selected.size;

  if (toggleBtn) {
    toggleBtn.textContent = state.modsBulkState.enabled ? t('common.cancelBulk') : t('common.bulkSelect');
    toggleBtn.className = state.modsBulkState.enabled ? 'primary' : 'mild';
  }

  if (deleteBtn) {
    deleteBtn.classList.toggle('hidden', !state.modsBulkState.enabled);
    deleteBtn.textContent = t('mods.deleteSelectedCount', { count });
    deleteBtn.disabled = count === 0;
  }

  if (moveBtn) {
    moveBtn.classList.toggle('hidden', !state.modsBulkState.enabled || !config.supportsMove);
    moveBtn.textContent = t('mods.moveSelectedCount', { count });
    moveBtn.disabled = count === 0;
  }

  refreshActionOverflowMenus();
};

const setModsBulkMode = (enabled) => {
  const shouldEnable = !!enabled;
  state.modsBulkState.enabled = shouldEnable;
  if (!shouldEnable) {
    state.modsBulkState.selected = new Set();
  }
  updateModsBulkActionsUI();
  renderInstalledMods();
};

const toggleModBulkSelection = (mod) => {
  if (!state.modsBulkState.enabled || !mod) return;
  const key = getModBulkKey(mod);
  const parsed = parseModBulkKey(key);
  if (!parsed || !parsed.mod_slug) return;
  if (state.modsBulkState.selected.has(key)) {
    state.modsBulkState.selected.delete(key);
  } else {
    state.modsBulkState.selected.add(key);
  }
  updateModsBulkActionsUI();
  renderInstalledMods();
};

const bulkDeleteSelectedMods = async ({ skipConfirm = false } = {}) => {
  const config = getAddonConfig();
  const keys = Array.from(state.modsBulkState.selected);
  if (!keys.length) {
    showMessageBox({
      title: t('mods.bulkDelete.title', { addon: config.pluralTitle }),
      message: t('mods.bulkDelete.noSelected', { addon: config.plural }),
      buttons: [{ label: t('common.ok') }],
    });
    return;
  }

  const runDelete = async () => {
    let cancelRequested = false;
    let processed = 0;
    showLoadingOverlay(t('mods.bulkDelete.deletingProgress', { addon: config.plural, current: 0, total: keys.length }), {
      buttons: [
        {
          label: t('common.cancel'),
          classList: ['danger'],
          closeOnClick: false,
          onClick: (_values, controls) => {
            if (cancelRequested) return;
            cancelRequested = true;
            controls.update({
              message: t('mods.bulkDelete.cancelling', { addon: config.singular }),
              buttons: [],
            });
          },
        },
      ],
    });
    let deleted = 0;
    const failures = [];

    for (const key of keys) {
      if (cancelRequested) break;
      const parsed = parseModBulkKey(key);
      if (!parsed || !parsed.mod_slug || (parsed.addon_type === 'mods' && !parsed.mod_loader)) {
        failures.push(`${key} (${t('mods.bulkDelete.invalidKey')})`);
        processed += 1;
        setLoadingOverlayText(t('mods.bulkDelete.deletingProgress', { addon: config.plural, current: processed, total: keys.length }));
        continue;
      }

      try {
        const isModpackDelete = (parsed.addon_type || '').toLowerCase() === 'modpacks';
        const res = isModpackDelete
          ? await api('/api/modpacks/delete', 'POST', { slug: parsed.mod_slug })
          : await api('/api/mods/delete', 'POST', {
            addon_type: parsed.addon_type || modsState.addonType,
            mod_slug: parsed.mod_slug,
            mod_loader: parsed.mod_loader,
          });
        if (res && res.ok) {
          deleted += 1;
        } else {
          const failurePrefix = parsed.mod_loader ? `${parsed.mod_loader}/${parsed.mod_slug}` : parsed.mod_slug;
          failures.push(`${failurePrefix}: ${(res && res.error) || t('common.unknownError')}`);
        }
      } catch (err) {
        const failurePrefix = parsed.mod_loader ? `${parsed.mod_loader}/${parsed.mod_slug}` : parsed.mod_slug;
        failures.push(`${failurePrefix}: ${(err && err.message) || t('versions.bulkDelete.requestFailed')}`);
      }
      processed += 1;
      setLoadingOverlayText(t('mods.bulkDelete.deletingProgress', { addon: config.plural, current: processed, total: keys.length }));
    }

    hideLoadingOverlay();
    setModsBulkMode(false);
    await loadInstalledMods();

    if (cancelRequested) {
      showMessageBox({
        title: t('mods.bulkDelete.cancelledTitle'),
        message: t(failures.length ? 'mods.bulkDelete.cancelledWithFailures' : 'mods.bulkDelete.cancelledMessage', { count: deleted, addon: config.singular, failures: failures.length }),
        buttons: [{ label: t('common.ok') }],
      });
      return;
    }

    if (!failures.length) {
      showMessageBox({
        title: t('mods.bulkDelete.completeTitle'),
        message: t('mods.bulkDelete.completeMessage', { count: deleted, addon: config.singular }),
        buttons: [{ label: t('common.ok') }],
      });
      return;
    }

    const preview = failures.slice(0, 8).join('<br>');
    const more = failures.length > 8 ? `<br>${t('versions.bulkDelete.andMore', { count: failures.length - 8 })}` : '';
    showMessageBox({
      title: t('mods.bulkDelete.finishedWithErrorsTitle'),
      message: t('mods.bulkDelete.finishedWithErrorsMessage', { count: deleted, addon: config.singular, failures: `${preview}${more}` }),
      buttons: [{ label: t('common.ok') }],
    });
  };

  if (skipConfirm || state.isShiftDown) {
    await runDelete();
    return;
  }

  showMessageBox({
    title: t('mods.bulkDelete.title', { addon: config.pluralTitle }),
    message: t('mods.bulkDelete.confirmMessage', { count: keys.length, addon: config.singular }),
    buttons: [
      {
        label: t('common.delete'),
        classList: ['danger'],
        onClick: runDelete,
      },
      { label: t('common.cancel') },
    ],
  });
};

const clampInstallPercent = (value) => Math.max(0, Math.min(100, Number(value) || 0));

const formatInstallProgressText = (progress, fallback = t('mods.install.installing')) => {
  const pct = Math.round(clampInstallPercent(progress && progress.overall_percent));
  const message = String((progress && progress.message) || '').trim();
  const bytesDone = Number((progress && progress.bytes_done) || 0);
  const bytesTotal = Number((progress && progress.bytes_total) || 0);
  const base = bytesTotal > 0
    ? `${pct}% (${formatBytes(bytesDone)} / ${formatBytes(bytesTotal)})`
    : `${pct}%`;
  if (message && message !== fallback) return `${base} - ${message}`;
  return message || base || fallback;
};

const ensureInstallProgressElements = (card) => {
  if (!card) return null;
  if (card._installProgressFill && card._installProgressTextEl) {
    return { fill: card._installProgressFill, text: card._installProgressTextEl };
  }

  const progressBar = document.createElement('div');
  progressBar.className = 'version-progress mod-install-progress';

  const fill = document.createElement('div');
  fill.className = 'version-progress-fill';
  progressBar.appendChild(fill);

  const progressText = document.createElement('div');
  progressText.className = 'version-progress-text mod-install-progress-text';
  progressText.textContent = t('mods.install.starting');

  card.appendChild(progressBar);
  card.appendChild(progressText);
  card._installProgressFill = fill;
  card._installProgressTextEl = progressText;
  return { fill, text: progressText };
};

const updateInlineInstallProgress = ({ card, button }, pct, text, buttonText = '') => {
  const progressEls = ensureInstallProgressElements(card);
  if (progressEls) {
    progressEls.fill.style.width = `${clampInstallPercent(pct)}%`;
    progressEls.text.textContent = text;
  }
  if (button && buttonText) {
    button.textContent = buttonText;
  }
};

const startInlineInstallProgress = ({ installKey, button, card, activeLabel = t('mods.install.installing'), doneLabel = t('mods.install.installed'), idleLabel = t('common.install') }) => {
  if (!installKey) {
    return {
      complete: () => {},
      fail: () => {},
      close: () => {},
    };
  }

  let eventSource = null;
  let closed = false;
  const target = { card, button };
  updateInlineInstallProgress(target, 0, t('mods.install.starting'), t('mods.install.activeEllipsis', { label: activeLabel }));

  const close = () => {
    if (closed) return;
    closed = true;
    if (eventSource) eventSource.close();
  };

  const complete = (message = doneLabel) => {
    updateInlineInstallProgress(target, 100, message, doneLabel);
    close();
  };

  const fail = (message = t('mods.install.failed')) => {
    updateInlineInstallProgress(target, 0, message, idleLabel);
    if (button) button.disabled = false;
    close();
  };

  try {
    eventSource = new EventSource(`/api/stream/install/${encodeURIComponent(installKey)}`);
    eventSource.onmessage = (event) => {
      if (closed) return;
      let progress = null;
      try {
        progress = JSON.parse(event.data);
      } catch (_err) {
        return;
      }
      if (!progress) return;

      const status = String(progress.status || '').toLowerCase();
      const pct = clampInstallPercent(progress.overall_percent);
      if (status === 'installed') {
        complete(progress.message || doneLabel);
        return;
      }
      if (status === 'failed' || status === 'cancelled') {
        fail(progress.message || (status === 'cancelled' ? t('mods.install.cancelled') : t('mods.install.failed')));
        return;
      }

      const text = formatInstallProgressText(progress, activeLabel);
      updateInlineInstallProgress(target, pct, text, `${activeLabel} ${Math.round(pct)}%`);
    };
  } catch (_err) {
    updateInlineInstallProgress(target, 0, t('mods.install.starting'), t('mods.install.activeEllipsis', { label: activeLabel }));
  }

  return { complete, fail, close };
};

const bulkMoveSelectedMods = () => {
  if (!isModsAddonType()) return;
  const selectedMods = (modsState.installedMods || []).filter((mod) =>
    state.modsBulkState.selected.has(getModBulkKey(mod))
  );

  if (!selectedMods.length) {
    showMessageBox({
      title: 'Bulk Move Mods',
      message: 'No installed mods selected.',
      buttons: [{ label: 'OK' }],
    });
    return;
  }

  const sourceLoaders = new Set(
    selectedMods
      .map((mod) => String(mod.mod_loader || '').toLowerCase())
      .filter((loaderType) => LOADER_UI_CONFIG[loaderType])
  );

  const content = document.createElement('div');
  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.textContent = `Move ${selectedMods.length} selected mod${selectedMods.length !== 1 ? 's' : ''} to:`;

  const select = document.createElement('select');
  select.className = 'mod-version-select';
  select.style.cssText = 'width:100%;margin-top:4px;max-width:100%;';

  LOADER_UI_ORDER.forEach((loaderType) => {
    const opt = document.createElement('option');
    opt.value = loaderType;
    opt.textContent = getLoaderUi(loaderType).name;
    select.appendChild(opt);
  });

  const defaultTarget = LOADER_UI_ORDER.find((loaderType) => !sourceLoaders.has(loaderType)) || LOADER_UI_ORDER[0];
  if (defaultTarget) select.value = defaultTarget;

  content.appendChild(label);
  content.appendChild(select);

  showMessageBox({
    title: 'Bulk Move Mods',
    customContent: content,
    buttons: [
      {
        label: 'Move',
        classList: ['important'],
        onClick: async () => {
          const targetLoader = String(select.value || '').toLowerCase();
          let cancelRequested = false;
          let processed = 0;
          showLoadingOverlay(`Moving selected mods... (0/${selectedMods.length})`, {
            buttons: [
              {
                label: 'Cancel',
                classList: ['danger'],
                closeOnClick: false,
                onClick: (_values, controls) => {
                  if (cancelRequested) return;
                  cancelRequested = true;
                  controls.update({
                    message: 'Cancelling bulk move after the current mod finishes...',
                    buttons: [],
                  });
                },
              },
            ],
          });

          let moved = 0;
          let skipped = 0;
          const failures = [];

          for (const mod of selectedMods) {
            if (cancelRequested) break;
            const sourceLoader = String(mod.mod_loader || '').toLowerCase();
            if (!sourceLoader || sourceLoader === targetLoader) {
              skipped += 1;
              processed += 1;
              setLoadingOverlayText(`Moving selected mods... (${processed}/${selectedMods.length})`);
              continue;
            }

            try {
              const res = await api('/api/mods/move', 'POST', {
                mod_slug: mod.mod_slug,
                mod_loader: sourceLoader,
                target_loader: targetLoader,
              });

              if (res && res.ok) {
                moved += 1;
              } else {
                failures.push(`${mod.mod_slug}: ${(res && res.error) || 'move failed'}`);
              }
            } catch (err) {
              failures.push(`${mod.mod_slug}: ${(err && err.message) || 'request failed'}`);
            }
            processed += 1;
            setLoadingOverlayText(`Moving selected mods... (${processed}/${selectedMods.length})`);
          }

          hideLoadingOverlay();
          setModsBulkMode(false);
          await loadInstalledMods();

          if (cancelRequested) {
            showMessageBox({
              title: 'Bulk Move Cancelled',
              message: `Moved ${moved} mod${moved !== 1 ? 's' : ''}${skipped ? `, skipped ${skipped}` : ''} before cancellation.${failures.length ? `<br><br>Failures: ${failures.length}` : ''}`,
              buttons: [{ label: 'OK' }],
            });
            return;
          }

          if (!failures.length) {
            showMessageBox({
              title: 'Bulk Move Complete',
              message: `Moved ${moved} mod${moved !== 1 ? 's' : ''}${skipped ? `, skipped ${skipped}` : ''}.`,
              buttons: [{ label: 'OK' }],
            });
            return;
          }

          const preview = failures.slice(0, 8).join('<br>');
          const more = failures.length > 8 ? `<br>...and ${failures.length - 8} more.` : '';
          showMessageBox({
            title: 'Bulk Move Finished With Errors',
            message: `Moved ${moved} mod${moved !== 1 ? 's' : ''}${skipped ? `, skipped ${skipped}` : ''}.<br><br>Failures:<br>${preview}${more}`,
            buttons: [{ label: 'OK' }],
          });
        },
      },
      { label: 'Cancel' },
    ],
  });
};

const resetModsSearch = () => {
  modsState.currentPage = 1;
  modsState.totalPages = 1;
  modsState.availableModsRaw = [];
  modsState.availableMods = [];
};

const applyModsClientFilters = () => {
  modsState.availableMods = (modsState.availableModsRaw || []).slice();
};

const refreshModsCategoryOptions = () => {
  const categorySelect = getEl('mods-category-select');
  if (!categorySelect) return;

  if (!getAddonConfig().supportsCategory) {
    categorySelect.innerHTML = '';
    appendOption(categorySelect, '', t('common.all'));
    categorySelect.value = '';
    modsState.category = '';
    return;
  }

  const previousValue = modsState.category || categorySelect.value || '';
  const set = new Set(
    (modsState.categoryOptions || [])
      .map((cat) => String(cat || '').trim())
      .filter(Boolean)
  );
  if (previousValue) set.add(previousValue);
  const sortedCategories = Array.from(set).sort((a, b) => a.localeCompare(b));

  categorySelect.innerHTML = '';
  appendOption(categorySelect, '', t('common.all'));

  sortedCategories.forEach((cat) => {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = cat;
    categorySelect.appendChild(opt);
  });

  if (previousValue && sortedCategories.includes(previousValue)) {
    categorySelect.value = previousValue;
  } else {
    categorySelect.value = '';
    modsState.category = '';
  }
};

const updateModsTypeUI = () => {
  const config = getAddonConfig();
  const titleEl = document.querySelector('#page-mods .section-title-text');
  if (titleEl) titleEl.textContent = t('nav.addons');

  const sidebarLabel = document.querySelector('.sidebar-item[data-page="mods"] span');
  if (sidebarLabel) sidebarLabel.textContent = t('nav.addons');

  const typeSelect = getEl('mods-type-select');
  if (typeSelect) typeSelect.value = modsState.addonType || 'mods';

  refreshModsCompatibilityOptions();

  const categoryFilterItem = getEl('mods-category-filter-item');
  if (categoryFilterItem) categoryFilterItem.classList.toggle('hidden', !config.supportsCategory);

  const bulkMoveBtn = getEl('mods-bulk-move-btn');
  if (bulkMoveBtn) bulkMoveBtn.classList.toggle('hidden', !state.modsBulkState.enabled || !config.supportsMove);

  const modpackButtons = [
    getEl('export-modpack-btn'),
    getEl('import-modpack-btn'),
    getEl('mods-overflow-export-modpack-btn'),
    getEl('mods-overflow-import-modpack-btn'),
    getEl('installed-modpacks-list'),
  ];
  modpackButtons.forEach((el) => {
    if (el) el.classList.toggle('hidden', !config.supportsModpacks);
  });

  const importBtn = getEl('import-mod-btn');
  if (importBtn) {
    importBtn.classList.toggle('hidden', isModpacksAddonType());
    const importTitle = getAddonConfigText('importTitle');
    importBtn.title = importTitle;
    importBtn.setAttribute('aria-label', importTitle);
  }

  const importOverflowBtn = getEl('mods-overflow-import-mod-btn');
  if (importOverflowBtn) {
    importOverflowBtn.classList.toggle('hidden', isModpacksAddonType());
    const importTitle = getAddonConfigText('importTitle');
    importOverflowBtn.title = importTitle;
    importOverflowBtn.setAttribute('aria-label', importTitle);
  }

  const overflowTrigger = getEl('mods-actions-overflow-btn');
  if (overflowTrigger) {
    const title = t('mods.moreActionsForType', { addon: getAddonConfigText('singular') });
    overflowTrigger.title = title;
    overflowTrigger.setAttribute('aria-label', title);
  }

  const overflowMenu = getEl('mods-actions-overflow-menu');
  if (overflowMenu) overflowMenu.setAttribute('aria-label', t('mods.actionsForType', { addon: getAddonConfigText('singularTitle') }));

  const importInput = getEl('import-mod-file-input');
  if (importInput) importInput.accept = config.importAccept;

  const refreshBtn = getEl('mods-refresh-btn');
  if (refreshBtn) refreshBtn.title = t('mods.refreshTypeListTooltip', { addon: getAddonConfigText('singular') });

  updateModsProviderDisplay();
  refreshActionOverflowMenus();
};

const setAddonType = (addonType) => {
  const normalizedType = String(addonType || 'mods').toLowerCase();
  if (!ADDON_TYPE_CONFIG[normalizedType] || normalizedType === modsState.addonType) {
    updateModsTypeUI();
    return;
  }

  modsState.addonType = normalizedType;
  modsState.currentPage = 1;
  modsState.totalPages = 1;
  modsState.categoryOptions = [];
  modsState.availableModsRaw = [];
  modsState.availableMods = [];
  modsState.installedMods = [];
  modsState.installedModpacks = [];
  modsState.lastError = null;

  const config = getAddonConfig();
  modsState.modLoader = normalizeAddonCompatibilityValue(normalizedType, modsState.modLoader);
  if (!config.supportsCategory) modsState.category = '';

  setModsBulkMode(false);
  updateModsTypeUI();
  refreshModsPageState();
};

// --- Mods View Toggle ---
export const applyModsViewMode = () => {
  const mode = state.settingsState.addons_view || 'list';
  const containers = [
    getEl('installed-modpacks-list'),
    getEl('installed-mods-list'),
    getEl('available-mods-list'),
    ...$$('.installed-mods-group-body'),
  ];
  containers.forEach((c) => {
    if (c) c.classList.toggle('list-view', mode === 'list');
  });

  const gridBtn = getEl('mods-view-grid-btn');
  const listBtn = getEl('mods-view-list-btn');
  if (gridBtn) gridBtn.classList.toggle('active', mode === 'grid');
  if (listBtn) listBtn.classList.toggle('active', mode === 'list');
};

const initModsViewToggle = () => {
  const gridBtn = getEl('mods-view-grid-btn');
  const listBtn = getEl('mods-view-list-btn');

  if (gridBtn) {
    gridBtn.addEventListener('click', () => {
      if (state.settingsState.addons_view !== 'grid') {
        _deps.autoSaveSetting('addons_view', 'grid');
        applyModsViewMode();
      }
    });
  }
  if (listBtn) {
    listBtn.addEventListener('click', () => {
      if (state.settingsState.addons_view !== 'list') {
        _deps.autoSaveSetting('addons_view', 'list');
        applyModsViewMode();
      }
    });
  }
  applyModsViewMode();
};

export const initModsPage = () => {
  if (!modsLanguageListenerBound) {
    modsLanguageListenerBound = true;
    window.addEventListener('histolauncher:language-changed', () => {
      updateModsTypeUI();
      refreshModsCategoryOptions();
      updateModsBulkActionsUI();
      renderInstalledMods();
      renderAvailableMods();
    });
  }

  const modsTypeSelect = getEl('mods-type-select');
  if (modsTypeSelect) {
    modsTypeSelect.value = modsState.addonType || 'mods';
    modsTypeSelect.addEventListener('change', () => {
      setAddonType(modsTypeSelect.value);
    });
  }

  const modsProfileSelect = getEl('mods-profile-select');
  if (modsProfileSelect) {
    _deps.renderScopeProfilesSelect('mods');
    modsProfileSelect.onchange = async (e) => {
      const selected = String((e && e.target && e.target.value) || '').trim();
      if (!selected) {
        _deps.renderScopeProfilesSelect('mods');
        return;
      }

      if (selected === ADD_PROFILE_OPTION) {
        modsProfileSelect.value = state.modsProfilesState.activeProfile;
        _deps.showCreateScopeProfileModal('mods');
        return;
      }

      if (selected === state.modsProfilesState.activeProfile) {
        return;
      }

      await _deps.switchScopeProfile('mods', selected);
    };
  }

  const modsProfileDeleteBtn = getEl('mods-profile-delete-btn');
  const modsProfileDeleteIcon = getEl('mods-profile-delete-icon');
  const modsProfileEditBtn = getEl('mods-profile-edit-btn');
  const modsProfileEditIcon = getEl('mods-profile-edit-icon');
  if (modsProfileEditBtn) {
    if (modsProfileEditIcon) {
      modsProfileEditBtn.onmouseenter = () => {
        if (!modsProfileEditBtn.disabled) modsProfileEditIcon.src = 'assets/images/filled_pencil.png';
      };
      modsProfileEditBtn.onmouseleave = () => {
        modsProfileEditIcon.src = 'assets/images/unfilled_pencil.png';
      };
    }
    modsProfileEditBtn.onclick = (e) => {
      e.preventDefault();
      if (modsProfileEditBtn.disabled) return;
      _deps.showRenameScopeProfileModal('mods');
    };
    _deps.updateScopeProfileEditButtonState('mods');
  }

  if (modsProfileDeleteBtn) {
    if (modsProfileDeleteIcon) {
      modsProfileDeleteBtn.onmouseenter = () => {
        if (!modsProfileDeleteBtn.disabled) modsProfileDeleteIcon.src = 'assets/images/filled_delete.png';
      };
      modsProfileDeleteBtn.onmouseleave = () => {
        modsProfileDeleteIcon.src = 'assets/images/unfilled_delete.png';
      };
    }
    modsProfileDeleteBtn.onclick = (e) => {
      e.preventDefault();
      if (modsProfileDeleteBtn.disabled) return;
      _deps.showDeleteScopeProfileModal('mods');
    };
    _deps.updateScopeProfileDeleteButtonState('mods');
  }

  let filterTimeout;

  const providerSelect = getEl('mods-provider-select');
  if (providerSelect) {
    providerSelect.addEventListener('change', () => {
      modsState.provider = providerSelect.value;
      resetModsSearch();
      updateModsProviderDisplay();
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => searchMods(), 400);
    });
  }

  const loaderSelect = getEl('mods-loader-select');
  if (loaderSelect) {
    loaderSelect.addEventListener('change', () => {
      modsState.modLoader = loaderSelect.value;
      renderInstalledMods();
      resetModsSearch();
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => searchMods(), 400);
    });
  }

  const versionSelect = getEl('mods-version-select');
  if (versionSelect) {
    versionSelect.addEventListener('change', () => {
      modsState.gameVersion = versionSelect.value;
      resetModsSearch();
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => searchMods(), 400);
    });
  }

  const categorySelect = getEl('mods-category-select');
  if (categorySelect) {
    categorySelect.addEventListener('change', () => {
      modsState.category = categorySelect.value;
      modsState.currentPage = 1;
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => searchMods(), 150);
    });
  }

  const sortSelect = getEl('mods-sort-select');
  if (sortSelect) {
    sortSelect.addEventListener('change', () => {
      modsState.sortBy = sortSelect.value;
      modsState.currentPage = 1;
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(() => searchMods(), 150);
    });
  }

  const searchInput = getEl('mods-search');
  if (searchInput) {
    let searchTimeout;
    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        modsState.searchQuery = searchInput.value.trim();
        renderInstalledMods();
        resetModsSearch();
        searchMods();
      }, 500);
    });
  }

  const modsRefreshBtn = getEl('mods-refresh-btn');
  if (modsRefreshBtn) {
    modsRefreshBtn.addEventListener('click', () => {
      resetModsSearch();
      refreshModsPageState();
    });
  }

  // --- Import mod archive ---
  const importModBtn = getEl('import-mod-btn');
  const importModFileInput = getEl('import-mod-file-input');
  if (importModBtn && importModFileInput) {
    importModBtn.addEventListener('click', () => {
      importModFileInput.value = '';
      importModFileInput.click();
    });
    importModFileInput.addEventListener('change', () => {
      const file = importModFileInput.files[0];
      if (!file) return;
      handleImportMod(file);
    });
  }

  // --- Export modpack ---
  const exportModpackBtn = getEl('export-modpack-btn');
  if (exportModpackBtn) {
    exportModpackBtn.addEventListener('click', () => showExportModpackWizard());
  }

  // --- Import modpack ---
  const importModpackBtn = getEl('import-modpack-btn');
  const importModpackFileInput = getEl('import-modpack-file-input');
  if (importModpackBtn && importModpackFileInput) {
    importModpackBtn.addEventListener('click', () => {
      importModpackFileInput.value = '';
      importModpackFileInput.click();
    });
    importModpackFileInput.addEventListener('change', () => {
      const file = importModpackFileInput.files[0];
      if (!file) return;
      handleImportModpack(file);
    });
  }

  const modsBulkToggleBtn = getEl('mods-bulk-toggle-btn');
  if (modsBulkToggleBtn) {
    modsBulkToggleBtn.addEventListener('click', () => {
      setModsBulkMode(!state.modsBulkState.enabled);
    });
  }

  const modsBulkDeleteBtn = getEl('mods-bulk-delete-btn');
  if (modsBulkDeleteBtn) {
    modsBulkDeleteBtn.addEventListener('click', (e) => {
      bulkDeleteSelectedMods({ skipConfirm: isShiftDelete(e) });
    });
  }

  const modsBulkMoveBtn = getEl('mods-bulk-move-btn');
  if (modsBulkMoveBtn) {
    modsBulkMoveBtn.addEventListener('click', () => {
      bulkMoveSelectedMods();
    });
  }

  updateModsBulkActionsUI();

  initModsViewToggle();
  updateModsTypeUI();
};

const updateModsProviderDisplay = () => {
  const display = getEl('mods-provider-display');
  if (display) {
    display.textContent = getProviderDisplayName();
  }

  const subtitle = getEl('mods-available-subtitle');
  if (subtitle) {
    subtitle.textContent = t('mods.availableSubtitle', {
      addonType: getAddonConfigText('label'),
      provider: getProviderDisplayName(),
    });
  }
};

const populateModsVersionDropdown = () => {
  const select = getEl('mods-version-select');
  if (!select) return;

  const previousValue = modsState.gameVersion || select.value || '';
  select.innerHTML = '';
  appendOption(select, '', t('common.all'));

  api('/api/addons/version-options', 'POST', {
    addon_type: modsState.addonType,
  })
    .then((res) => {
      if (!res || !res.ok) return;
      const versions = Array.isArray(res.versions) ? res.versions : [];
      versions.slice(0, 100).forEach((entry) => {
        const ver = entry.version || entry.folder;
        if (!ver) return;
        const opt = document.createElement('option');
        opt.value = ver;
        opt.textContent = ver;
        select.appendChild(opt);
      });

      if (previousValue && Array.from(select.options).some((opt) => opt.value === previousValue)) {
        select.value = previousValue;
        modsState.gameVersion = previousValue;
      } else {
        select.value = '';
        if (previousValue) modsState.gameVersion = '';
      }
    })
    .catch((err) => console.error('Failed to load mod version options:', err));
};

export const refreshModsPageState = async () => {
  updateModsTypeUI();
  const providerSelect = getEl('mods-provider-select');
  const loaderSelect = getEl('mods-loader-select');
  const versionSelect = getEl('mods-version-select');
  const categorySelect = getEl('mods-category-select');
  const sortSelect = getEl('mods-sort-select');
  const searchInput = getEl('mods-search');
  const typeSelect = getEl('mods-type-select');

  if (typeSelect) typeSelect.value = modsState.addonType || 'mods';
  if (providerSelect) providerSelect.value = modsState.provider || 'modrinth';
  if (loaderSelect) loaderSelect.value = modsState.modLoader || '';
  if (versionSelect) versionSelect.value = modsState.gameVersion || '';
  if (categorySelect) categorySelect.value = modsState.category || '';
  if (sortSelect) sortSelect.value = modsState.sortBy || 'relevance';
  if (searchInput) searchInput.value = modsState.searchQuery || '';

  updateModsProviderDisplay();
  populateModsVersionDropdown();
  const [installedResult, searchResult] = await Promise.allSettled([
    loadInstalledMods(),
    searchMods(),
  ]);
  return installedResult.status === 'fulfilled'
    && installedResult.value !== false
    && searchResult.status === 'fulfilled'
    && searchResult.value !== false;
};

export const loadInstalledMods = async () => {
  try {
    const loadAddonList = !isModpacksAddonType();
    const loadModpackList = isModpacksAddonType();
    const requests = [
      loadAddonList
        ? api('/api/addons/installed', 'POST', { addon_type: modsState.addonType })
        : Promise.resolve({ ok: true, addons: [] }),
      loadModpackList
        ? api('/api/modpacks/installed', 'GET')
        : Promise.resolve({ ok: true, modpacks: [] }),
    ];

    const [modsResult, packsResult] = await Promise.allSettled(requests);
    const modsRes = modsResult.status === 'fulfilled' ? modsResult.value : null;
    const packsRes = packsResult && packsResult.status === 'fulfilled' ? packsResult.value : null;

    if (modsRes && modsRes.ok) {
      modsState.installedMods = modsRes.addons || modsRes.mods || [];
    } else {
      modsState.installedMods = [];
    }

    if (packsRes && packsRes.ok && loadModpackList) {
      modsState.installedModpacks = packsRes.modpacks || [];
    } else {
      modsState.installedModpacks = [];
    }
    renderInstalledMods();
    return !!(modsRes && modsRes.ok) && (!loadModpackList || !!(packsRes && packsRes.ok));
  } catch (err) {
    console.error('Failed to load installed mods:', err);
    modsState.installedMods = [];
    modsState.installedModpacks = [];
    renderInstalledMods();
    return false;
  }
};

const searchMods = async () => {
  const requestId = ++modsState.searchRequestId;
  try {
    modsState.lastError = null;
    const warn = getEl('mods-section-warning');
    if (warn) warn.classList.add('hidden');

    // Show loading indicator, clear current list
    const modsLoading = getEl('mods-loading');
    const availableList = getEl('available-mods-list');
    if (modsLoading) modsLoading.classList.remove('hidden');
    if (availableList) availableList.innerHTML = '';

    const pageIndex = modsState.currentPage - 1;
    const res = await api('/api/mods/search', 'POST', {
      addon_type: modsState.addonType,
      provider: modsState.provider,
      search_query: modsState.searchQuery,
      game_version: modsState.gameVersion,
      mod_loader: addonTypeSupportsCompatibilityFilter() ? modsState.modLoader : '',
      category: getAddonConfig().supportsCategory ? modsState.category : '',
      sort_by: modsState.sortBy || 'relevance',
      page_size: MODS_PAGE_SIZE,
      page_index: pageIndex,
    });

    if (requestId !== modsState.searchRequestId) return true;

    if (res && res.ok) {
      const incoming = Array.isArray(res.mods) ? res.mods : [];

      modsState.availableModsRaw = incoming;
      modsState.categoryOptions = Array.isArray(res.categories) ? res.categories : [];

      // Calculate total pages from total_count if available
      const totalCount = res.total_count || incoming.length;
      modsState.totalPages = Math.max(1, Math.ceil(totalCount / MODS_PAGE_SIZE));

      refreshModsCategoryOptions();
      applyModsClientFilters();

      if (warn) {
        if (res.error) {
          warn.textContent = res.requires_api_key
            ? 'CurseForge requires an API key. Add a key to use CurseForge provider, or switch to Modrinth.'
            : `Provider error: ${res.error}`;
          warn.classList.remove('hidden');
        }
      }

      if (modsLoading) modsLoading.classList.add('hidden');
      renderAvailableMods();
      renderModsPagination();
      return true;
    } else {
      if (modsLoading) modsLoading.classList.add('hidden');
      modsState.availableModsRaw = [];
      modsState.availableMods = [];
      modsState.lastError = (res && res.error)
        ? t('mods.search.failedWithError', { error: res.error })
        : t('mods.search.failedUnknown');
      if (warn) {
        warn.textContent = modsState.lastError;
        warn.classList.remove('hidden');
      }
      renderAvailableMods();
      renderModsPagination();
      return false;
    }
  } catch (err) {
    if (requestId !== modsState.searchRequestId) return true;
    console.error('Failed to search mods:', err);
    const modsLoading = getEl('mods-loading');
    if (modsLoading) modsLoading.classList.add('hidden');
    modsState.availableModsRaw = [];
    modsState.availableMods = [];
    modsState.lastError = t('mods.search.failedNetwork');
    const warn = getEl('mods-section-warning');
    if (warn) {
      warn.textContent = modsState.lastError;
      warn.classList.remove('hidden');
    }
    renderAvailableMods();
    renderModsPagination();
    return false;
  }
};

const getInstalledGroupLabel = (groupKey) => {
  if (groupKey === 'modpacks') return getAddonConfigText('label', 'modpacks');
  if (groupKey === 'other') return t('mods.groups.other');
  if (LOADER_UI_CONFIG[groupKey]) return LOADER_UI_CONFIG[groupKey].name;
  const label = String(groupKey || 'Other');
  return label.charAt(0).toUpperCase() + label.slice(1);
};

const appendInstalledGroup = (container, groupKey, items, renderItem) => {
  if (!container || !Array.isArray(items) || items.length === 0) return;

  const group = document.createElement('section');
  group.className = 'installed-mods-group';
  group.dataset.groupKey = groupKey;

  const header = document.createElement('button');
  header.type = 'button';
  header.className = 'installed-mods-loader-header installed-mods-group-toggle';

  const title = document.createElement('span');
  title.className = 'installed-mods-group-title';
  title.textContent = getInstalledGroupLabel(groupKey);

  const count = document.createElement('span');
  count.className = 'installed-mods-group-count';
  count.textContent = `${items.length}`;

  const indicator = document.createElement('span');
  indicator.className = 'installed-mods-group-indicator';

  const body = document.createElement('div');
  body.className = 'versions-list installed-mods-group-body';
  body.classList.toggle('list-view', (state.settingsState.addons_view || 'list') === 'list');

  const applyCollapsedState = () => {
    const collapsed = !!modsState.installedGroupsCollapsed[groupKey];
    header.setAttribute('aria-expanded', String(!collapsed));
    indicator.textContent = collapsed ? unicodeList.dropdown_close : unicodeList.dropdown_open;
    body.classList.toggle('hidden', collapsed);
  };

  items.forEach((item) => body.appendChild(renderItem(item)));

  header.appendChild(title);
  header.appendChild(count);
  header.appendChild(indicator);

  header.addEventListener('click', () => {
    modsState.installedGroupsCollapsed[groupKey] = !modsState.installedGroupsCollapsed[groupKey];
    applyCollapsedState();
  });

  applyCollapsedState();

  group.appendChild(header);
  group.appendChild(body);
  container.appendChild(group);
};

// --- Pagination ---
const renderModsPagination = () => {
  const container = getEl('mods-pagination');
  if (!container) return;

  const total = modsState.totalPages;
  const current = modsState.currentPage;
  renderCommonPagination(container, total, current, (page) => {
    modsState.currentPage = page;
    searchMods();
  });
};

// --- Installed Mods (Fabric / Forge sections) ---
const renderInstalledMods = () => {
  const config = getAddonConfig();
  const list = getEl('installed-mods-list');
  const packsList = getEl('installed-modpacks-list');
  if (!list) return;

  const subtitle = getEl('installed-mods-subtitle');
  const installedCount = modsState.installedMods.length;
  const disabledCount = modsState.installedMods.filter((mod) => mod && mod.disabled).length;
  const packCount = modsState.installedModpacks.length;
  if (subtitle) {
    let text = isModpacksAddonType()
      ? t('mods.installedModpacksSubtitle', { count: packCount })
      : t('mods.installedSubtitleCount', {
        plural: getAddonConfigText('plural'),
        installed: installedCount,
        disabled: disabledCount,
      });
    if (!isModpacksAddonType() && config.supportsModpacks && packCount > 0) {
      text += t('mods.installedSubtitleModpacksSuffix', {
        count: packCount,
        label: packCount === 1
          ? getAddonConfigText('singular', 'modpacks')
          : getAddonConfigText('plural', 'modpacks'),
      });
    }
    subtitle.textContent = text;
  }

  pruneModsBulkSelection();
  updateModsBulkActionsUI();

  const normalizeSearchText = (value) => {
    let text = String(value || '').toLowerCase();
    try {
      text = decodeURIComponent(text);
    } catch (_) {
      // Keep original text if it is not valid URI-encoded content.
    }
    // Treat URL-encoded and separator variants the same for matching.
    return text
      .replace(/\+/g, ' ')
      .replace(/[%_\-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  };

  // Render modpacks
  if (packsList) {
    packsList.innerHTML = '';
    packsList.classList.toggle('hidden', !config.supportsModpacks);
    if (config.supportsModpacks) {
      const loaderFilter = normalizeAddonCompatibilityValue('modpacks', modsState.modLoader);
      let packs = modsState.installedModpacks;
      if (loaderFilter) {
        packs = packs.filter((pack) => addonMatchesCompatibilityFilter(pack, loaderFilter, 'modpacks'));
      }
      const installSearchQ = normalizeSearchText(modsState.searchQuery || '');
      if (installSearchQ) {
        packs = packs.filter((pack) => {
          const name = normalizeSearchText(pack.name || pack.slug || '');
          const slug = normalizeSearchText(pack.slug || '');
          return name.includes(installSearchQ) || slug.includes(installSearchQ);
        });
      }
      appendInstalledGroup(packsList, 'modpacks', packs, (pack) => createModpackCard(pack));
    }
  }

  list.innerHTML = '';

  if (isModpacksAddonType()) {
    if (packCount === 0) list.appendChild(createEmptyState(getAddonConfigText('emptyInstalled')));
    applyModsViewMode();
    return;
  }

  // Apply current filters (provider only affects Available, not Installed)
  let filtered = modsState.installedMods;
  const loaderFilter = normalizeAddonCompatibilityValue(modsState.addonType, modsState.modLoader);
  if (loaderFilter) {
    filtered = filtered.filter((m) => addonMatchesCompatibilityFilter(m, loaderFilter));
  }
  const installSearchQ = normalizeSearchText(modsState.searchQuery || '');
  if (installSearchQ) {
    filtered = filtered.filter((m) => {
      const name = normalizeSearchText(m.mod_name || m.display_name || m.mod_slug || m.name || '');
      const slug = normalizeSearchText(m.mod_slug || '');
      return name.includes(installSearchQ) || slug.includes(installSearchQ);
    });
  }

  if (filtered.length === 0) {
    list.appendChild(createEmptyState(getAddonConfigText('emptyInstalled')));
    applyModsViewMode();
    return;
  }

  if (!config.supportsLoader) {
    filtered.forEach((addon) => {
      list.appendChild(createModCard(addon, true));
    });
    applyModsViewMode();
    return;
  }

  const groups = {
    fabric: [],
    babric: [],
    forge: [],
    modloader: [],
    neoforge: [],
    quilt: [],
    other: [],
  };

  filtered.forEach((mod) => {
    const loader = (mod.mod_loader || '').toLowerCase();
    if (loader === 'fabric') {
      groups.fabric.push(mod);
    } else if (loader === 'babric') {
      groups.babric.push(mod);
    } else if (loader === 'forge') {
      groups.forge.push(mod);
    } else if (loader === 'modloader') {
      groups.modloader.push(mod);
    } else if (loader === 'neoforge') {
      groups.neoforge.push(mod);
    } else if (loader === 'quilt') {
      groups.quilt.push(mod);
    } else {
      groups.other.push(mod);
    }
  });

  appendInstalledGroup(list, 'fabric', groups.fabric, (mod) => createModCard(mod, true));
  appendInstalledGroup(list, 'babric', groups.babric, (mod) => createModCard(mod, true));
  appendInstalledGroup(list, 'forge', groups.forge, (mod) => createModCard(mod, true));
  appendInstalledGroup(list, 'modloader', groups.modloader, (mod) => createModCard(mod, true));
  appendInstalledGroup(list, 'neoforge', groups.neoforge, (mod) => createModCard(mod, true));
  appendInstalledGroup(list, 'quilt', groups.quilt, (mod) => createModCard(mod, true));
  appendInstalledGroup(list, 'other', groups.other, (mod) => createModCard(mod, true));

  applyModsViewMode();
};

// --- Available Mods ---
const renderAvailableMods = () => {
  const config = getAddonConfig();
  const container = getEl('available-mods-list');
  if (!container) return;

  container.innerHTML = '';

  if (modsState.availableMods.length === 0) {
    if (modsState.lastError) {
      container.appendChild(createEmptyState(modsState.lastError, { isError: true }));
    } else {
      container.appendChild(createEmptyState(getAddonConfigText('emptyAvailable')));
    }
  } else {
    modsState.availableMods.forEach((mod) => {
      const card = createModCard(mod, false);
      container.appendChild(card);
    });
  }

  applyModsViewMode();
};

// --- Import Mod Handler ---
const handleImportMod = (file) => {
  if (isModpacksAddonType()) {
    handleImportModpack(file);
    return;
  }

  const fileName = file.name;
  const config = getAddonConfig();

  const runImport = async (modLoader = '') => {
    const formData = new FormData();
    formData.append('addon_type', modsState.addonType);
    if (modLoader) formData.append('mod_loader', modLoader);
    formData.append('file_name', fileName);
    formData.append('mod_file', file);

    try {
      const response = await fetch('/api/mods/import', {
        method: 'POST',
        body: formData,
      });
      const result = await response.json();

      if (result && result.ok) {
        let successMsg = result.message || `Successfully imported <b>${fileName}</b>.`;
        if (result.warning) {
          successMsg += `<br><br><i>${result.warning}</i>`;
        }
        showMessageBox({
          title: 'Import Successful',
          message: successMsg,
          buttons: [{ label: 'OK' }],
        });
        loadInstalledMods();
      } else {
        showMessageBox({
          title: 'Import Error',
          message: result.error || `Failed to import ${config.singular}.`,
          buttons: [{ label: 'OK' }],
        });
      }
    } catch (err) {
      console.error('Failed to import addon:', err);
    }
  };

  if (!config.supportsLoader) {
    runImport('');
    return;
  }

  // Build loader selection UI
  const content = document.createElement('div');
  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.textContent = t('mods.import.selectLoaderForFile', { file: fileName });

  const select = document.createElement('select');
  select.className = 'mod-version-select';
  select.style.cssText = 'width:100%;margin-top:4px;max-width:100%;';
  LOADER_UI_ORDER.forEach((loaderType) => {
    const loaderName = getLoaderUi(loaderType).name;
    const opt = document.createElement('option');
    opt.value = loaderType;
    opt.textContent = loaderName;
    select.appendChild(opt);
  });

  content.appendChild(label);
  content.appendChild(select);

  showMessageBox({
    title: config.importTitle,
    customContent: content,
    buttons: [
      {
        label: 'Import',
        classList: ['primary'],
        onClick: async () => {
          runImport(select.value);
        },
      },
      { label: 'Cancel' },
    ],
  });
};

// --- Mod Card ---
const createModCard = (mod, isInstalled) => {
  const config = getAddonConfig();
  const card = document.createElement('div');
  card.className = 'version-card mod-card mod-entry-card';
  card.classList.add('unselectable', isInstalled ? 'section-installed' : 'section-available');

  const modBulkKey = getModBulkKey(mod);
  const isModBulkSelected = isInstalled && state.modsBulkState.enabled && state.modsBulkState.selected.has(modBulkKey);

  if (isInstalled && state.modsBulkState.enabled) {
    card.classList.add('bulk-select-active');
    if (isModBulkSelected) card.classList.add('bulk-selected');
  }

  if (isInstalled) {
    card.classList.add('mod-card-installed');
    const loaderKey = String(mod.mod_loader || '').toLowerCase();
    if (isModsAddonType() && LOADER_UI_CONFIG[loaderKey]) {
      card.classList.add(`mod-card-loader-${loaderKey}`);
    }
  }

  if (isInstalled && mod.disabled) {
    card.classList.add('mod-card-disabled');
  }

  const icon = document.createElement('img');
  icon.className = 'version-image mod-image mod-card-image';
  icon.src = mod.icon_url || config.defaultIcon;
  icon.onerror = () => { icon.src = config.defaultIcon; };

  const info = document.createElement('div');
  info.className = 'version-info mod-card-info';

  const headerRow = document.createElement('div');
  headerRow.className = 'version-header-row';

  const name = document.createElement('div');
  name.className = 'version-display';
  name.textContent = mod.mod_name || mod.name || 'Unknown Mod';

  const desc = document.createElement('div');
  desc.className = 'version-folder mod-card-description';
  desc.textContent = mod.description || mod.summary || '';

  headerRow.appendChild(name);
  info.appendChild(headerRow);
  info.appendChild(desc);

  let versionSelect = null;
  const getSelectedVersionMeta = () => {
    if (!Array.isArray(mod.versions) || !versionSelect) return null;
    const selected = String(versionSelect.value || '').trim();
    return mod.versions.find((v) => String(v.version_label || '') === selected) || null;
  };

  // Version dropdown for installed mods
  if (isInstalled && Array.isArray(mod.versions) && mod.versions.length > 0) {
    const versionRow = document.createElement('div');
    versionRow.className = 'mod-version-row mod-card-control-row';

    const versionLabel = document.createElement('span');
    versionLabel.className = 'mod-version-label';
    versionLabel.textContent = `${t('home.info.version')}:`;

    versionSelect = document.createElement('select');
    versionSelect.className = 'mod-version-select mod-card-select';
    versionSelect.style.cssText = 'font-size:10px';
    mod.versions.forEach((v) => {
      const opt = document.createElement('option');
      opt.value = v.version_label;
      const loaderTag = formatCompatibilityTag(v, modsState.addonType);
      opt.textContent = v.version_label + loaderTag;
      if (v.version_label === mod.active_version) opt.selected = true;
      versionSelect.appendChild(opt);
    });
    versionSelect.addEventListener('change', async (e) => {
      e.stopPropagation();
      try {
        const res = await api('/api/mods/set-active-version', 'POST', {
          addon_type: modsState.addonType,
          mod_slug: mod.mod_slug,
          mod_loader: mod.mod_loader,
          version_label: versionSelect.value,
        });
        if (res && res.ok) {
          loadInstalledMods();
        }
      } catch (err) {
        console.error('Failed to set active version:', err);
      }
    });

    versionRow.appendChild(versionLabel);
    versionRow.appendChild(versionSelect);
    info.appendChild(versionRow);
  }

  const selectedModLoader = String(mod.mod_loader || '').toLowerCase();
  const allowAllModloaderOverwrite = _deps.isTruthySetting(state.settingsState.allow_override_classpath_all_modloaders);
  const canShowOverwriteControls = selectedModLoader === 'modloader' || allowAllModloaderOverwrite;

  if (isInstalled && versionSelect && isModsAddonType() && canShowOverwriteControls) {
    const overwriteRow = document.createElement('div');
    overwriteRow.className = 'mod-overwrite-row mod-card-control-row';

    const overwriteLabel = document.createElement('span');
    overwriteLabel.className = 'mod-overwrite-label';
    overwriteLabel.textContent = t('mods.exportModpack.overwriteClassesLabel');

    const overwriteCheckbox = document.createElement('input');
    overwriteCheckbox.type = 'checkbox';
    overwriteCheckbox.className = 'mod-overwrite-checkbox mod-card-checkbox';

    const sourceRow = document.createElement('div');
    sourceRow.className = 'mod-source-row mod-card-control-row';

    const sourceLabel = document.createElement('span');
    sourceLabel.className = 'mod-source-label';
    sourceLabel.textContent = t('mods.exportModpack.sourceFolderLabel');

    const sourceSelect = document.createElement('select');
    sourceSelect.className = 'mod-version-select mod-source-select mod-card-select';
    sourceSelect.style.cssText = 'font-size:10px';

    const setSourceOptions = (incomingOptions, preferredValue) => {
      const options = [{ value: '', label: t('mods.exportModpack.defaultSource') }];
      const seen = new Set(['']);

      const list = Array.isArray(incomingOptions) ? incomingOptions : [];
      list.forEach((item) => {
        const rawValue = typeof item === 'string'
          ? item
          : (item && item.value !== undefined ? item.value : (item && item.path !== undefined ? item.path : ''));
        const rawLabel = typeof item === 'string'
          ? item
          : (item && item.label !== undefined ? item.label : (item && item.name !== undefined ? item.name : rawValue));

        const value = String(rawValue || '').trim();
        const label = String(rawLabel || value).trim();
        if (seen.has(value)) return;
        seen.add(value);
        options.push({ value, label: label || value });
      });

      sourceSelect.innerHTML = '';
      options.forEach((optData) => {
        const opt = document.createElement('option');
        opt.value = optData.value;
        opt.textContent = optData.label;
        sourceSelect.appendChild(opt);
      });

      const desired = String(preferredValue || '').trim();
      sourceSelect.value = seen.has(desired) ? desired : '';
    };

    const setSourceVisibility = (enabled) => {
      const isEnabled = !!enabled;
      sourceRow.style.display = isEnabled ? 'flex' : 'none';
      sourceSelect.disabled = !isEnabled;
    };

    const loadSourceFolders = async () => {
      const selectedMeta = getSelectedVersionMeta();
      const preferred = selectedMeta ? String(selectedMeta.source_subfolder || '') : '';

      try {
        const res = await api('/api/mods/archive-subfolders', 'POST', {
          mod_slug: mod.mod_slug,
          mod_loader: mod.mod_loader,
          version_label: versionSelect.value,
        });

        if (!res || !res.ok) {
          throw new Error((res && res.error) || t('mods.exportModpack.failedSourceFolders'));
        }

        setSourceOptions(res.subfolders, preferred);
        return true;
      } catch (err) {
        console.error('Failed to load source folders:', err);
        setSourceOptions([], preferred);
        showMessageBox({
          title: t('mods.exportModpack.sourceFolderError'),
          message: (err && err.message) ? err.message : t('mods.exportModpack.failedSourceFoldersFromArchive'),
          buttons: [{ label: t('common.ok') }],
        });
        return false;
      }
    };

    const selectedMeta = getSelectedVersionMeta();
    overwriteCheckbox.checked = !!(selectedMeta && selectedMeta.overwrite_classes);
    setSourceOptions([], selectedMeta ? selectedMeta.source_subfolder : '');
    setSourceVisibility(overwriteCheckbox.checked);
    if (overwriteCheckbox.checked) {
      loadSourceFolders();
    }

    overwriteCheckbox.addEventListener('change', async (e) => {
      e.stopPropagation();
      const enabled = !!overwriteCheckbox.checked;
      const previousState = !enabled;
      const previousValue = sourceSelect.value;

      setSourceVisibility(enabled);
      if (enabled) {
        const loaded = await loadSourceFolders();
        if (!loaded) {
          overwriteCheckbox.checked = false;
          setSourceVisibility(false);
          return;
        }
      } else {
        sourceSelect.value = '';
      }

      try {
        const res = await api('/api/mods/update-version-settings', 'POST', {
          mod_slug: mod.mod_slug,
          mod_loader: mod.mod_loader,
          version_label: versionSelect.value,
          overwrite_classes: enabled,
          source_subfolder: enabled ? (sourceSelect.value || '') : '',
        });

        if (!res || !res.ok) {
          throw new Error((res && res.error) || t('mods.exportModpack.failedUpdateOverwrite'));
        }

        const currentMeta = getSelectedVersionMeta();
        if (currentMeta) {
          currentMeta.overwrite_classes = !!res.overwrite_classes;
          currentMeta.source_subfolder = String(res.source_subfolder || '');
        }

        if (enabled) {
          sourceSelect.value = String(res.source_subfolder || sourceSelect.value || '');
        }
      } catch (err) {
        console.error('Failed to update overwrite settings:', err);
        overwriteCheckbox.checked = previousState;
        setSourceVisibility(previousState);
        sourceSelect.value = previousValue || '';
        showMessageBox({
          title: t('mods.exportModpack.saveError'),
          message: (err && err.message) ? err.message : t('mods.exportModpack.failedSaveOverwrite'),
          buttons: [{ label: t('common.ok') }],
        });
      }
    });

    sourceSelect.addEventListener('change', async (e) => {
      e.stopPropagation();
      if (!overwriteCheckbox.checked) return;

      const selectedValue = sourceSelect.value || '';
      try {
        const res = await api('/api/mods/update-version-settings', 'POST', {
          mod_slug: mod.mod_slug,
          mod_loader: mod.mod_loader,
          version_label: versionSelect.value,
          overwrite_classes: true,
          source_subfolder: selectedValue,
        });

        if (!res || !res.ok) {
          throw new Error((res && res.error) || t('mods.exportModpack.failedUpdateSourceFolder'));
        }

        const currentMeta = getSelectedVersionMeta();
        if (currentMeta) {
          currentMeta.overwrite_classes = true;
          currentMeta.source_subfolder = String(res.source_subfolder || selectedValue);
        }
        sourceSelect.value = String(res.source_subfolder || selectedValue);
      } catch (err) {
        console.error('Failed to update source folder:', err);
        showMessageBox({
          title: t('mods.exportModpack.saveError'),
          message: (err && err.message) ? err.message : t('mods.exportModpack.failedSaveSourceFolder'),
          buttons: [{ label: t('common.ok') }],
        });
      }
    });

    overwriteRow.appendChild(overwriteLabel);
    overwriteRow.appendChild(overwriteCheckbox);

    sourceRow.appendChild(sourceLabel);
    sourceRow.appendChild(sourceSelect);

    info.appendChild(overwriteRow);
    info.appendChild(sourceRow);
  }

  const badgeRow = document.createElement('div');
  badgeRow.className = 'version-badge-row';

  if (isInstalled) {
    const stateBadge = document.createElement('span');
    if (mod.disabled) {
      stateBadge.className = 'version-badge paused';
      stateBadge.textContent = t('mods.status.disabled').toUpperCase();
    } else if (mod.is_imported) {
      stateBadge.className = 'version-badge imported';
      stateBadge.textContent = t('mods.status.imported').toUpperCase();
    } else {
      stateBadge.className = 'version-badge installed';
      stateBadge.textContent = t('mods.status.installed').toUpperCase();
    }
    badgeRow.appendChild(stateBadge);
  }

  // Show active version compatibility badges
  if (isInstalled && addonTypeSupportsCompatibilityFilter() && mod.versions) {
    const activeVer = mod.versions.find(v => v.version_label === mod.active_version);
    const compatibilityValues = getAddonCompatibilityValues(activeVer || mod, modsState.addonType);
    compatibilityValues.slice(0, 2).forEach((value) => {
      const loaderBadge = document.createElement('span');
      loaderBadge.className = 'version-badge lite';
      loaderBadge.textContent = getCompatibilityLabel(modsState.addonType, value).toUpperCase();
      badgeRow.appendChild(loaderBadge);
    });
  }

  if (!isInstalled) {
    const providerBadge = document.createElement('span');
    providerBadge.className = 'version-badge nonofficial';
    providerBadge.textContent = (mod.provider || modsState.provider || 'unknown').toUpperCase();
    badgeRow.appendChild(providerBadge);
  }

  const categories = Array.isArray(mod.categories) ? mod.categories : [];
  if (config.supportsCategory && categories.length > 0) {
    const catBadge = document.createElement('span');
    catBadge.className = 'version-badge size';
    catBadge.textContent = String(categories[0] || '').toUpperCase();
    badgeRow.appendChild(catBadge);
  }

  const deleteIconContainer = document.createElement('div');
  deleteIconContainer.className = 'mod-card-delete-icon';
  if (isInstalled) {
    const delBtn = document.createElement('div');
    delBtn.className = 'icon-button';
    bindKeyboardActivation(delBtn, {
      ariaLabel: state.modsBulkState.enabled
        ? `Toggle selection for ${config.singular} ${String(name.textContent || '').trim() || `this ${config.singular}`}`
        : `Delete ${config.singular} ${String(name.textContent || '').trim() || `this ${config.singular}`}`,
    });
    const delImg = document.createElement('img');
    delImg.alt = t('common.delete');
    delImg.src = 'assets/images/unfilled_delete.png';
    imageAttachErrorPlaceholder(delImg, 'assets/images/placeholder.png');
    delBtn.appendChild(delImg);
    delBtn.addEventListener('mouseenter', () => { delImg.src = 'assets/images/filled_delete.png'; });
    delBtn.addEventListener('mouseleave', () => { delImg.src = 'assets/images/unfilled_delete.png'; });
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.modsBulkState.enabled) {
        toggleModBulkSelection(mod);
        return;
      }
      deleteMod(mod, { skipConfirm: isShiftDelete(e) });
    });
    deleteIconContainer.appendChild(delBtn);
  }

  const actions = document.createElement('div');
  actions.className = 'version-actions';

  if (isInstalled) {
    const toggleBtn = document.createElement('button');
    toggleBtn.className = mod.disabled ? 'primary' : 'mild';
    toggleBtn.textContent = mod.disabled ? t('mods.actions.enable') : t('mods.actions.disable');
    toggleBtn.onclick = (e) => {
      e.stopPropagation();
      if (state.modsBulkState.enabled) {
        toggleModBulkSelection(mod);
        return;
      }
      toggleModDisabled(mod);
    };
    actions.appendChild(toggleBtn);

    if (config.supportsMove) {
      const moveBtn = document.createElement('button');
      moveBtn.className = 'important';
      moveBtn.textContent = t('mods.move.button');
      moveBtn.onclick = (e) => {
        e.stopPropagation();
        if (state.modsBulkState.enabled) {
          toggleModBulkSelection(mod);
          return;
        }
        moveMod(mod);
      };
      actions.appendChild(moveBtn);
    }
  }

  if (!isInstalled) {
    // Quick install button for available mod cards
    const quickInstallWrap = document.createElement('div');
    quickInstallWrap.className = 'quick-install-wrap';

    const quickInstallBtn = document.createElement('button');
    quickInstallBtn.className = 'primary';
    quickInstallBtn.textContent = t('common.install');

    const quickInstallVersion = document.createElement('div');
    quickInstallVersion.className = 'quick-install-version';
    quickInstallVersion.textContent = t('mods.detail.latest');

    let resolvedQuickVersion = null;

    quickInstallBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (quickInstallBtn.disabled) return;
      quickInstallBtn.disabled = true;
      quickInstallBtn.textContent = t('mods.detail.fetching');
      try {
        const versRes = await api('/api/mods/versions', 'POST', {
          addon_type: modsState.addonType,
          provider: mod.provider || modsState.provider,
          mod_id: mod.mod_id,
          game_version: modsState.gameVersion || '',
          mod_loader: addonTypeSupportsCompatibilityFilter() ? (modsState.modLoader || '') : '',
        });
        if (!versRes || !versRes.ok) {
          quickInstallBtn.disabled = false;
          quickInstallBtn.textContent = t('common.install');
          quickInstallVersion.textContent = t('mods.detail.lookupFailed');
          showMessageBox({
            title: t('mods.detail.versionLookupFailedTitle'),
            message: (versRes && versRes.error) || t('mods.detail.versionLookupFailedMessage'),
            buttons: [{ label: t('common.ok') }],
          });
          return;
        }
        const allVers = (versRes && versRes.ok && Array.isArray(versRes.versions)) ? versRes.versions : [];
        if (allVers.length === 0) {
          quickInstallBtn.disabled = false;
          quickInstallBtn.textContent = t('common.install');
          quickInstallVersion.textContent = t('mods.detail.noVersionsFound');
          return;
        }
        // Apply same filter logic as detail modal
        const selLoader = addonTypeSupportsCompatibilityFilter()
          ? normalizeAddonCompatibilityValue(modsState.addonType, modsState.modLoader)
          : '';
        const selGV = modsState.gameVersion || '';
        let filtered = allVers;
        if (selLoader) filtered = filtered.filter((v) => versionMatchesCompatibilityFilter(v, selLoader));
        if (selGV) filtered = filtered.filter((v) => (v.game_versions || []).includes(selGV));
        if (filtered.length === 0) filtered = allVers; // fall back if no match
        const recIdx = (() => {
          let idx = filtered.findIndex((v) => (v.version_type || '').toLowerCase() === 'release');
          if (idx === -1) idx = filtered.findIndex((v) => (v.version_type || '').toLowerCase() === 'beta');
          if (idx === -1) idx = 0;
          return idx;
        })();
        resolvedQuickVersion = filtered[recIdx];
        const verLabel = resolvedQuickVersion.version_number || resolvedQuickVersion.display_name || t('mods.detail.latest');
        quickInstallVersion.textContent = verLabel;
        const modLoader = addonTypeSupportsCompatibilityFilter()
          ? (selLoader
            || getPreferredCompatibilityValue({ compatibility_types: resolvedQuickVersion.loaders }, modsState.addonType)
            || (isModsAddonType() ? 'fabric' : ''))
          : '';
        quickInstallBtn.textContent = t('common.install');
        installMod(mod, resolvedQuickVersion, modLoader, quickInstallBtn);
      } catch (err) {
        console.error('Quick install failed to fetch versions:', err);
        quickInstallBtn.disabled = false;
        quickInstallBtn.textContent = t('common.install');
      }
    });

    quickInstallWrap.addEventListener('click', (e) => e.stopPropagation());
    quickInstallWrap.appendChild(quickInstallBtn);
    quickInstallWrap.appendChild(quickInstallVersion);
    actions.appendChild(quickInstallWrap);
  }

  card.appendChild(icon);
  card.appendChild(info);
  if (isInstalled) card.appendChild(deleteIconContainer);
  card.appendChild(badgeRow);
  card.appendChild(actions);

  if (isInstalled && state.modsBulkState.enabled) {
    const checkbox = document.createElement('div');
    checkbox.className = 'bulk-select-checkbox';
    checkbox.textContent = isModBulkSelected ? '✔' : '';
    card.appendChild(checkbox);
  }

  if (!isInstalled) {
    card.style.cursor = 'pointer';
    bindKeyboardActivation(card, {
      ariaLabel: `View details for ${config.singular} ${String(name.textContent || '').trim() || `this ${config.singular}`}`,
    });
    card.addEventListener('click', () => {
      showModDetailModal(mod);
    });
  } else if (state.modsBulkState.enabled) {
    card.style.cursor = 'pointer';
    bindKeyboardActivation(card, {
      ariaLabel: `Toggle selection for ${config.singular} ${String(name.textContent || '').trim() || `this ${config.singular}`}`,
    });
    card.setAttribute('aria-pressed', isModBulkSelected ? 'true' : 'false');
    card.addEventListener('click', (e) => {
      if (e.target.closest('button, select, input, .icon-button')) return;
      toggleModBulkSelection(mod);
    });
  }

  if (!isInstalled || (isInstalled && state.modsBulkState.enabled)) {
    wireCardActionArrowNavigation(card);
  }

  return card;
};

// --- Mod Detail Modal (replaces Install button) ---
export const showModDetailModal = async (mod) => {
  const requestedAddonType = String((mod && mod.addon_type) || modsState.addonType || 'mods').toLowerCase();
  const detailAddonType = ADDON_TYPE_CONFIG[requestedAddonType] ? requestedAddonType : 'mods';
  const config = getAddonConfig(detailAddonType);
  const modName = mod.name || mod.mod_name || 'Unknown Mod';
  const detailProvider = (mod.provider || modsState.provider || '').toLowerCase();
  const installedMods = detailAddonType === modsState.addonType
    ? modsState.installedMods
    : [];

  const resolveDetailLink = (rawHref) => {
    if (!rawHref) return '';
    const href = String(rawHref).trim();
    if (!href) return '';
    if (href.startsWith('http://') || href.startsWith('https://')) return href;
    if (href.startsWith('//')) return `https:${href}`;
    if (href.startsWith('www.')) return `https://${href}`;
    if (href.startsWith('/')) {
      if (detailProvider === 'curseforge') return `https://www.curseforge.com${href}`;
      if (detailProvider === 'modrinth') return `https://modrinth.com${href}`;
    }
    return '';
  };

  const escapeHtml = (txt) => String(txt || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

  const preserveInlineHtml = (txt) => {
    const placeholders = [];
    const placeholderText = String(txt || '').replace(
      /<!--(?:.|\r|\n)*?-->|<\/?[a-zA-Z][^>]*>/g,
      (match) => {
        const key = `HLRAWHTMLTOKEN${placeholders.length}TOKEN`;
        placeholders.push({
          key,
          html: match,
        });
        return key;
      }
    );

    return {
      text: placeholderText,
      restore(value) {
        let restored = String(value || '');
        placeholders.forEach(({ key, html }) => {
          restored = restored.split(key).join(html);
        });
        return restored;
      },
    };
  };

  const markdownInlineToHtml = (line) => {
    const preserved = preserveInlineHtml(line);
    let out = escapeHtml(preserved.text);

    // Linked image: [![alt](img)](url)
    out = out.replace(/\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)/g,
      '<a href="$3"><img src="$2" alt="$1"></a>');
    // Image: ![alt](img)
    out = out.replace(/!\[([^\]]*)\]\(([^)]+)\)/g,
      '<img src="$2" alt="$1">');
    // Link: [text](url)
    out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2">$1</a>');

    // Strong / emphasis
    out = out.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
    out = out.replace(/__([^_]+)__/g, '<b>$1</b>');
    out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    out = out.replace(/_([^_]+)_/g, '<em>$1</em>');

    // Inline code
    out = out.replace(/`([^`]+)`/g, '<code>$1</code>');

    return preserved.restore(out);
  };

  const sanitizeRemoteHtml = (html) => {
    const template = document.createElement('template');
    template.innerHTML = String(html || '');

    template.content
      .querySelectorAll('script, iframe, object, embed, link, meta, base, form, input, button, textarea, select')
      .forEach((el) => el.remove());

    template.content.querySelectorAll('*').forEach((el) => {
      Array.from(el.attributes).forEach((attr) => {
        const name = String(attr.name || '').toLowerCase();
        const value = String(attr.value || '');

        if (name.startsWith('on')) {
          el.removeAttribute(attr.name);
          return;
        }

        if ((name === 'href' || name === 'src' || name === 'xlink:href') && /^\s*javascript:/i.test(value)) {
          el.removeAttribute(attr.name);
        }
      });
    });

    return template.innerHTML;
  };

  const renderModrinthMarkdown = (md) => {
    const lines = String(md || '').replace(/\r\n/g, '\n').split('\n');
    const chunks = [];
    let listItems = [];
    let inCodeFence = false;
    let codeFenceLang = '';
    let codeFenceLines = [];

    const flushList = () => {
      if (!listItems.length) return;
      chunks.push(`<ul>${listItems.join('')}</ul>`);
      listItems = [];
    };

    const flushCodeFence = () => {
      if (!inCodeFence) return;
      const langClass = codeFenceLang ? ` class="language-${escapeHtml(codeFenceLang)}"` : '';
      chunks.push(`<pre class="mod-detail-codeblock"><code${langClass}>${escapeHtml(codeFenceLines.join('\n'))}</code></pre>`);
      inCodeFence = false;
      codeFenceLang = '';
      codeFenceLines = [];
    };

    for (const rawLine of lines) {
      const line = rawLine.trim();

      if (inCodeFence) {
        if (/^```/.test(line)) {
          flushCodeFence();
        } else {
          codeFenceLines.push(rawLine);
        }
        continue;
      }

      const fenceStart = line.match(/^```\s*([a-zA-Z0-9_+-]*)\s*$/);
      if (fenceStart) {
        flushList();
        inCodeFence = true;
        codeFenceLang = (fenceStart[1] || '').trim().toLowerCase();
        codeFenceLines = [];
        continue;
      }

      if (!line) {
        flushList();
        continue;
      }

      if (/^\\+$/.test(line)) {
        flushList();
        chunks.push('<br>');
        continue;
      }

      // Preserve trusted raw HTML block tags from Modrinth bodies so they
      // render correctly instead of being escaped inside <p>...</p>.
      if (/^<!--(?:.|\r|\n)*?-->$|^<\/?[a-zA-Z][\w:-]*\b/i.test(line)) {
        flushList();
        chunks.push(line);
        continue;
      }

      if (/^[-*_]{3,}$/.test(line)) {
        flushList();
        chunks.push('<hr>');
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        flushList();
        const level = heading[1].length;
        chunks.push(`<h${level}>${markdownInlineToHtml(heading[2])}</h${level}>`);
        continue;
      }

      const li = line.match(/^[-*]\s+(.+)$/);
      if (li) {
        listItems.push(`<li>${markdownInlineToHtml(li[1])}</li>`);
        continue;
      }

      flushList();
      chunks.push(`<p>${markdownInlineToHtml(line)}</p>`);
    }

    flushList();
    flushCodeFence();
    return sanitizeRemoteHtml(chunks.join(''));
  };

  // Build the modal content container
  const content = document.createElement('div');
  content.className = 'mod-detail-content';

  const loadingEl = createInlineLoadingState(t('mods.detail.loadingDetails', { addon: getAddonConfigText('singular', detailAddonType) }), { centered: true });
  content.appendChild(loadingEl);

  showMessageBox({
    title: modName,
    customContent: content,
    buttons: [{ label: t('common.close') }],
  });

  // Fetch detail + versions in parallel
  try {
    const [detailResult, versionsResult] = await Promise.allSettled([
      api('/api/mods/detail', 'POST', {
        addon_type: detailAddonType,
        provider: mod.provider || modsState.provider,
        mod_id: mod.mod_id,
      }),
      api('/api/mods/versions', 'POST', {
        addon_type: detailAddonType,
        provider: mod.provider || modsState.provider,
        mod_id: mod.mod_id,
        game_version: '',
        mod_loader: '',
      }),
    ]);
    const detailRes = detailResult.status === 'fulfilled' ? detailResult.value : null;
    const versionsRes = versionsResult.status === 'fulfilled' ? versionsResult.value : null;
    const detailError = detailResult.status === 'rejected'
      ? ((detailResult.reason && detailResult.reason.message) || `Failed to fetch ${config.singular} details.`)
      : ((!detailRes || !detailRes.ok) ? ((detailRes && detailRes.error) || `Failed to fetch ${config.singular} details.`) : '');
    const versionsError = versionsResult.status === 'rejected'
      ? ((versionsResult.reason && versionsResult.reason.message) || `Failed to fetch ${config.singular} versions.`)
      : ((!versionsRes || !versionsRes.ok) ? ((versionsRes && versionsRes.error) || `Failed to fetch ${config.singular} versions.`) : '');

    content.innerHTML = '';

    // --- Description ---
    const description = (detailRes && detailRes.ok && detailRes.body) ? detailRes.body : (mod.description || mod.summary || '');
    if (description) {
      const descSection = document.createElement('div');
      descSection.className = 'mod-detail-description';
      if (detailProvider === 'modrinth') {
        descSection.innerHTML = renderModrinthMarkdown(description);
      } else if (description.includes('<') && description.includes('>')) {
        descSection.innerHTML = sanitizeRemoteHtml(description);
      } else {
        descSection.textContent = description;
      }

      descSection.querySelectorAll('a[href]').forEach((a) => {
        a.setAttribute('target', '_blank');
        const resolvedHref = resolveDetailLink(a.getAttribute('href'));
        if (resolvedHref) a.setAttribute('data-external-url', resolvedHref);
        a.addEventListener('click', (ev) => {
          ev.preventDefault();
          const href = a.getAttribute('data-external-url') || resolveDetailLink(a.getAttribute('href'));
          if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
            window.open(href, '_blank');
          }
        });
      });

      content.appendChild(descSection);
    }

    if (detailError) {
      const detailErrorEl = document.createElement('p');
      detailErrorEl.style.cssText = 'color:var(--color-warning);margin-top:8px;';
      detailErrorEl.textContent = detailError;
      content.appendChild(detailErrorEl);
    }

    // --- Gallery/Screenshots ---
    const gallery = (detailRes && detailRes.ok && Array.isArray(detailRes.gallery)) ? detailRes.gallery : [];
    const screenshots = (detailRes && detailRes.ok && Array.isArray(detailRes.screenshots)) ? detailRes.screenshots : [];
    const images = gallery.length > 0 ? gallery : screenshots;

    if (images.length > 0) {
      const galSection = document.createElement('div');
      galSection.className = 'mod-detail-gallery';

      const galTitle = document.createElement('h4');
      galTitle.textContent = t('mods.detail.screenshots');
      galTitle.style.marginBottom = '8px';
      galSection.appendChild(galTitle);

      const galRow = document.createElement('div');
      galRow.className = 'mod-detail-gallery-row';

      images.slice(0, 6).forEach((img) => {
        const imgUrl = typeof img === 'string' ? img : (img.url || img.thumbnailUrl || '');
        if (!imgUrl) return;
        const imgEl = document.createElement('img');
        imgEl.src = imgUrl;
        imgEl.className = 'mod-detail-screenshot';
        imgEl.onerror = () => { imgEl.style.display = 'none'; };
        imgEl.title = t('mods.detail.clickToEnlarge');
        imgEl.addEventListener('click', () => {
          let lightbox = document.getElementById('screenshot-lightbox');
          if (!lightbox) {
            lightbox = document.createElement('div');
            lightbox.id = 'screenshot-lightbox';
            lightbox.className = 'screenshot-lightbox';
            const lbImg = document.createElement('img');
            lbImg.className = 'screenshot-lightbox-img';
            lightbox.appendChild(lbImg);
            lightbox.addEventListener('click', () => { lightbox.classList.remove('active'); });
            document.body.appendChild(lightbox);
          }
          lightbox.querySelector('img').src = imgUrl;
          lightbox.classList.add('active');
        });
        galRow.appendChild(imgEl);
      });

      galSection.appendChild(galRow);
      content.appendChild(galSection);
    }

    // --- Stats ---
    if (detailRes && detailRes.ok) {
      const statsRow = document.createElement('div');
      statsRow.className = 'mod-detail-stats';
      const downloads = detailRes.downloads || mod.download_count || 0;
      const cats = Array.isArray(detailRes.categories) ? detailRes.categories : (mod.categories || []);
      statsRow.innerHTML = `<span>${t('mods.detail.downloads', { count: Number(downloads).toLocaleString() })}</span>`;
      if (cats.length > 0) {
        statsRow.innerHTML += ` <span>${t('mods.detail.categories', { categories: cats.join(', ') })}</span>`;
      }
      content.appendChild(statsRow);
    }

    // --- Versions list with filters ---
    const allVersions = (versionsRes && versionsRes.ok && Array.isArray(versionsRes.versions)) ? versionsRes.versions : [];

    if (versionsError) {
      const versionsErrorEl = document.createElement('p');
      versionsErrorEl.textContent = versionsError;
      versionsErrorEl.style.color = 'var(--color-error)';
      content.appendChild(versionsErrorEl);
    } else if (allVersions.length > 0) {
      const verSection = document.createElement('div');
      verSection.className = 'mod-detail-versions';

      const verTitle = document.createElement('h4');
      verTitle.textContent = t('mods.detail.versionsTitle', { count: allVersions.length });
      verTitle.style.marginBottom = '8px';
      verSection.appendChild(verTitle);

      // Filters row
      const filterRow = document.createElement('div');
      filterRow.className = 'mod-detail-version-filters';

      let loaderFilter = null;
      const compatibilityConfig = getAddonCompatibilityFilterConfig(detailAddonType);
      if (compatibilityConfig) {
        const loaderSet = new Set();
        allVersions.forEach((v) => {
          extractAddonCompatibilityValues(v.loaders, detailAddonType).forEach((value) => loaderSet.add(value));
        });
        loaderFilter = document.createElement('select');
        loaderFilter.innerHTML = `<option value="">${compatibilityConfig.detailAllLabel}</option>`;
        compatibilityConfig.options
          .filter((option) => loaderSet.size === 0 || loaderSet.has(option.value))
          .forEach((optionData) => {
            const o = document.createElement('option');
            o.value = optionData.value;
            o.textContent = optionData.label;
            loaderFilter.appendChild(o);
          });
      }

      // Game version filter
      const gvSet = new Set();
      allVersions.forEach((v) => {
        (v.game_versions || []).forEach((g) => gvSet.add(g));
      });
      const gvFilter = document.createElement('select');
      gvFilter.innerHTML = `<option value="">${t('mods.detail.allMcVersions')}</option>`;
      Array.from(gvSet).sort((a, b) => b.localeCompare(a, undefined, { numeric: true })).forEach((g) => {
        const o = document.createElement('option');
        o.value = g;
        o.textContent = g;
        gvFilter.appendChild(o);
      });

      if (loaderFilter) filterRow.appendChild(loaderFilter);
      filterRow.appendChild(gvFilter);

      // Pre-select dropdowns to match the active search filters
      const activeLoader = addonTypeSupportsCompatibilityFilter(detailAddonType)
        ? normalizeAddonCompatibilityValue(detailAddonType, modsState.modLoader)
        : '';
      const activeGV = modsState.gameVersion || '';
      if (loaderFilter && activeLoader && loaderFilter.querySelector(`option[value="${activeLoader}"]`)) {
        loaderFilter.value = activeLoader;
      }
      if (activeGV && gvFilter.querySelector(`option[value="${activeGV}"]`)) {
        gvFilter.value = activeGV;
      }

      verSection.appendChild(filterRow);

      // Scrollable versions list
      const verList = document.createElement('div');
      verList.className = 'mod-detail-version-list';

      const renderVersionList = () => {
        verList.innerHTML = '';
        const selLoader = loaderFilter ? loaderFilter.value : '';
        const selGV = gvFilter.value;

        let filtered = allVersions;
        if (selLoader) {
          filtered = filtered.filter((v) => versionMatchesCompatibilityFilter(v, selLoader, detailAddonType));
        }
        if (selGV) {
          filtered = filtered.filter((v) => (v.game_versions || []).includes(selGV));
        }

        if (filtered.length === 0) {
          verList.innerHTML = `<p style="text-align:center;color:var(--color-text-muted);padding:8px;">${t('mods.detail.noVersionsMatch')}</p>`;
          return;
        }

        const recommendedIdx = (() => {
          let idx = filtered.findIndex((v) => (v.version_type || '').toLowerCase() === 'release');
          if (idx === -1) idx = filtered.findIndex((v) => (v.version_type || '').toLowerCase() === 'beta');
          if (idx === -1) idx = filtered.findIndex((v) => (v.version_type || '').toLowerCase() === 'alpha');
          return idx;
        })();

        filtered.forEach((ver, idx) => {
          const isRecommended = idx === recommendedIdx && recommendedIdx !== -1;
          const row = document.createElement('div');
          row.className = 'mod-detail-version-row' + (isRecommended ? ' recommended' : '');

          const verName = document.createElement('span');
          verName.className = 'mod-detail-version-name';
          verName.textContent = ver.version_number || ver.display_name || ver.file_name || '?';

          const verMeta = document.createElement('span');
          verMeta.className = 'mod-detail-version-meta';
          const gvText = (ver.game_versions || []).slice(0, 3).join(', ');
          const loaderText = extractAddonCompatibilityValues(ver.loaders, detailAddonType)
            .map((value) => getCompatibilityLabel(detailAddonType, value))
            .join(', ');
          verMeta.textContent = [gvText, loaderText].filter(Boolean).join(' | ');

          const vtype = (ver.version_type || 'release').toLowerCase();
          const vtypeBadge = document.createElement('span');
          vtypeBadge.className = 'mod-version-type-badge mod-version-type-' + vtype;
          vtypeBadge.textContent = vtype === 'release' ? 'R' : vtype === 'beta' ? 'B' : 'A';
          vtypeBadge.title = vtype.charAt(0).toUpperCase() + vtype.slice(1);

          const installBtn = document.createElement('button');
          // Check if this version is already installed
          const versionStr = ver.version_number || ver.display_name || 'unknown';
          const isVersionInstalled = installedMods.some((m) =>
            m.mod_slug === mod.mod_slug &&
            m.versions && m.versions.some((iv) => iv.version_label === versionStr)
          );

          if (isVersionInstalled) {
            installBtn.className = 'important';
            installBtn.textContent = t('common.reinstall');
          } else {
            installBtn.className = 'primary';
            installBtn.textContent = t('common.install');
          }
          installBtn.style.fontSize = '11px';
          installBtn.style.padding = '3px 8px';
          installBtn.addEventListener('click', () => {
            const modLoader = addonTypeSupportsCompatibilityFilter(detailAddonType)
              ? (selLoader
                || getPreferredCompatibilityValue({ compatibility_types: ver.loaders }, detailAddonType)
                || normalizeAddonCompatibilityValue(detailAddonType, modsState.modLoader)
                || (isModsAddonType(detailAddonType) ? 'fabric' : ''))
              : '';
            installMod({ ...mod, addon_type: detailAddonType }, ver, modLoader, installBtn, detailAddonType);
          });

          row.appendChild(vtypeBadge);
          row.appendChild(verName);
          row.appendChild(verMeta);
          if (isRecommended) {
            const starImg = document.createElement('img');
            starImg.src = 'assets/images/filled_favorite.png';
            starImg.title = t('mods.detail.recommendedLatest');
            starImg.style.cssText = 'width:14px;height:14px;object-fit:contain;flex-shrink:0;';
            row.appendChild(starImg);
          }
          row.appendChild(installBtn);
          verList.appendChild(row);
        });
      };

      if (loaderFilter) loaderFilter.addEventListener('change', renderVersionList);
      gvFilter.addEventListener('change', renderVersionList);
      renderVersionList();

      verSection.appendChild(verList);
      content.appendChild(verSection);
    } else {
      const noVer = document.createElement('p');
      noVer.textContent = t('mods.detail.noVersionsAvailable', { addon: getAddonConfigText('singular', detailAddonType) });
      noVer.style.color = 'var(--color-text-muted)';
      content.appendChild(noVer);
    }
  } catch (err) {
    console.error('Failed to load addon details:', err);
    content.innerHTML = `<p style="color:var(--color-error);">${t('mods.detail.renderFailed', { addon: getAddonConfigText('singular', detailAddonType) })}</p>`;
  }
};

const installMod = async (mod, version, modLoader, installBtn, addonType = modsState.addonType) => {
  let progress = null;
  const requestedAddonType = String(addonType || 'mods').toLowerCase();
  const normalizedAddonType = ADDON_TYPE_CONFIG[requestedAddonType] ? requestedAddonType : 'mods';
  const config = getAddonConfig(normalizedAddonType);
  try {
    const idleLabel = installBtn ? (installBtn.textContent || t('common.install')) : t('common.install');
    const installKey = `addons/${normalizedAddonType}/${createOperationId('install')}`;
    if (installBtn) {
      installBtn.disabled = true;
      installBtn.textContent = t('mods.install.installingEllipsis');
    }
    progress = startInlineInstallProgress({
      installKey,
      button: installBtn,
      card: installBtn ? installBtn.closest('.mod-entry-card') : null,
      activeLabel: t('mods.install.installing'),
      doneLabel: t('mods.install.installed'),
      idleLabel,
    });

    const res = await api('/api/mods/install', 'POST', {
      addon_type: normalizedAddonType,
      install_key: installKey,
      provider: mod.provider || modsState.provider,
      mod_id: mod.mod_id,
      mod_slug: mod.mod_slug,
      mod_name: mod.name || mod.mod_name,
      mod_loader: addonTypeSupportsCompatibilityFilter(normalizedAddonType)
        ? (modLoader || normalizeAddonCompatibilityValue(normalizedAddonType, modsState.modLoader) || (isModsAddonType(normalizedAddonType) ? 'fabric' : ''))
        : '',
      compatibility_types: extractAddonCompatibilityValues(version && version.loaders, normalizedAddonType),
      download_url: version.download_url,
      file_name: version.file_name,
      file_id: version.file_id || version.version_id || '',
      game_versions: Array.isArray(version.game_versions) ? version.game_versions : [],
      loaders: Array.isArray(version.loaders) ? version.loaders : [],
      description: mod.summary || mod.description || '',
      icon_url: mod.icon_url || '',
      version: version.version_number || version.display_name || 'unknown',
    });

    if (res && res.ok) {
      if (progress) progress.complete(res.message || t('mods.install.installed'));
      if (installBtn) {
        installBtn.disabled = false;
        installBtn.textContent = t('mods.install.installed');
        installBtn.className = '';
        installBtn.style.color = 'var(--color-success)';
        installBtn.style.fontWeight = 'bold';
        installBtn.style.border = 'none';
        installBtn.style.background = 'transparent';
        installBtn.style.cursor = 'default';
      }
      if (normalizedAddonType === modsState.addonType) {
        await loadInstalledMods();
      }
    } else {
      if (progress) progress.fail((res && res.error) ? res.error : t('mods.install.failedForAddon', { addon: getAddonConfigText('singular', normalizedAddonType) }));
      if (installBtn) {
        installBtn.disabled = false;
        installBtn.textContent = idleLabel;
        installBtn.className = 'primary';
      }
      showMessageBox({
        title: t('mods.install.failedTitle'),
        message: (res && res.error) ? res.error : t('mods.install.failedForAddon', { addon: getAddonConfigText('singular', normalizedAddonType) }),
        buttons: [{ label: t('common.ok') }],
      });
    }
  } catch (err) {
    console.error('Failed to install mod:', err);
    if (progress) progress.fail(t('mods.install.unexpectedError'));
    if (installBtn) {
      installBtn.disabled = false;
      installBtn.textContent = t('common.install');
      installBtn.className = 'primary';
    }
    showMessageBox({
      title: t('mods.install.failedTitle'),
      message: t('mods.install.unexpectedForAddon', { addon: getAddonConfigText('singular', normalizedAddonType) }),
      buttons: [{ label: t('common.ok') }],
    });
  }
};

const toggleModDisabled = async (mod) => {
  const config = getAddonConfig();
  const newState = !mod.disabled;

  if (isModsAddonType() && !newState) {
    const blockingPack = modsState.installedModpacks.find((p) =>
      !p.disabled && (p.mods || []).some((pm) => pm.mod_slug === mod.mod_slug)
    );
    if (blockingPack) {
      showMessageBox({
        title: 'Cannot Enable',
        message: `This mod is managed by the modpack <b>${blockingPack.name || blockingPack.slug}</b>. Disable or delete that modpack first.`,
        buttons: [{ label: 'OK' }],
      });
      return;
    }
  }

  const doToggle = async () => {
    try {
      const res = await api('/api/mods/toggle', 'POST', {
        addon_type: modsState.addonType,
        mod_slug: mod.mod_slug,
        mod_loader: mod.mod_loader,
        disabled: newState,
      });
      if (res && res.ok) {
        loadInstalledMods();
      } else {
        showMessageBox({
          title: t('common.error'),
          message: res.error || t('mods.actions.toggleFailed', { addon: getAddonConfigText('singular') }),
          buttons: [{ label: t('common.ok') }],
        });
      }
    } catch (err) {
      console.error('Failed to toggle mod:', err);
    }
  };

  doToggle();
};

const deleteMod = (mod, options = {}) => {
  const config = getAddonConfig();
  const versions = Array.isArray(mod.versions) ? mod.versions : [];
  const skipConfirm = !!options.skipConfirm || state.isShiftDown;

  const doDelete = async (versionLabel) => {
    try {
      const payload = { addon_type: modsState.addonType, mod_slug: mod.mod_slug, mod_loader: mod.mod_loader };
      if (versionLabel) payload.version_label = versionLabel;

      const res = await api('/api/mods/delete', 'POST', payload);
      if (res && res.ok) {
        loadInstalledMods();
      } else {
        showMessageBox({
          title: t('common.error'),
          message: res.error || `Failed to delete ${config.singular}.`,
          buttons: [{ label: t('common.ok') }],
        });
      }
    } catch (err) {
      console.error('Failed to delete mod:', err);
    }
  };

  if (skipConfirm) {
    doDelete(null);
    return;
  }

  if (versions.length > 1) {
    // Build a select dropdown so the user can pick which version (or all) to delete
    const content = document.createElement('div');

    const label = document.createElement('p');
    label.style.marginBottom = '8px';
    label.textContent = `${mod.mod_name} has ${versions.length} installed versions. Choose what to delete:`;

    const select = document.createElement('select');
    select.className = 'mod-version-select';
    select.style.cssText = 'width:100%;margin-top:4px;max-width:100%;';

    const allOpt = document.createElement('option');
    allOpt.value = '';
    allOpt.textContent = t('mods.delete.title', { addon: config.singularTitle });
    select.appendChild(allOpt);

    versions.forEach((v) => {
      const opt = document.createElement('option');
      opt.value = v.version_label;
      const loaderTag = formatCompatibilityTag(v, modsState.addonType);
      opt.textContent = t('mods.delete.versionOption', { version: v.version_label, loader: loaderTag });
      select.appendChild(opt);
    });

    content.appendChild(label);
    content.appendChild(select);

    showMessageBox({
      title: t('mods.delete.title', { addon: config.singularTitle }),
      customContent: content,
      buttons: [
        {
          label: t('common.delete'),
          classList: ['danger'],
          onClick: () => doDelete(select.value || null),
        },
        { label: t('common.cancel') },
      ],
    });
  } else {
    showMessageBox({
      title: t('mods.delete.title', { addon: config.singularTitle }),
      message: t('mods.delete.confirm', { addon: mod.mod_name }),
      buttons: [
        { label: t('common.delete'), classList: ['danger'], onClick: () => doDelete(null) },
        { label: t('common.cancel') },
      ],
    });
  }
};


const moveMod = (mod) => {
  const sourceLoader = String(mod.mod_loader || '').toLowerCase();
  if (!LOADER_UI_CONFIG[sourceLoader]) {
    showMessageBox({
      title: t('mods.move.title'),
      message: t('mods.move.unknownLoader'),
      buttons: [{ label: t('common.ok') }],
    });
    return;
  }

  const targets = LOADER_UI_ORDER.filter((loaderType) => loaderType !== sourceLoader);
  if (!targets.length) {
    showMessageBox({
      title: t('mods.move.title'),
      message: t('mods.move.noTargets'),
      buttons: [{ label: t('common.ok') }],
    });
    return;
  }

  const sourceLoaderUi = getLoaderUi(sourceLoader);

  const content = document.createElement('div');

  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.innerHTML = t('mods.move.prompt', { addon: mod.mod_name || mod.mod_slug || t('mods.move.thisMod'), loader: sourceLoaderUi.name });

  const select = document.createElement('select');
  select.className = 'mod-version-select';
  select.style.cssText = 'width:100%;margin-top:4px;max-width:100%;';
  targets.forEach((loaderType) => {
    const opt = document.createElement('option');
    opt.value = loaderType;
    opt.textContent = getLoaderUi(loaderType).name;
    select.appendChild(opt);
  });

  content.appendChild(label);
  content.appendChild(select);

  showMessageBox({
    title: t('mods.move.title'),
    customContent: content,
    buttons: [
      {
        label: t('mods.move.button'),
        classList: ['important'],
        onClick: async () => {
          try {
            const targetLoader = String(select.value || '').toLowerCase();
            const res = await api('/api/mods/move', 'POST', {
              mod_slug: mod.mod_slug,
              mod_loader: sourceLoader,
              target_loader: targetLoader,
            });

            if (res && res.ok) {
              await loadInstalledMods();
              showMessageBox({
                title: t('mods.move.completeTitle'),
                message: res.message || t('mods.move.success'),
                buttons: [{ label: t('common.ok') }],
              });
            } else {
              showMessageBox({
                title: t('mods.move.failedTitle'),
                message: (res && res.error) || t('mods.move.failed'),
                buttons: [{ label: t('common.ok') }],
              });
            }
          } catch (err) {
            console.error('Failed to move mod:', err);
            showMessageBox({
              title: t('mods.move.failedTitle'),
              message: t('mods.move.unexpectedError'),
              buttons: [{ label: t('common.ok') }],
            });
          }
        },
      },
      { label: t('common.cancel') },
    ],
  });
};

// ---------------- Modpack Functions ----------------

const createModpackCard = (pack) => {
  const card = document.createElement('div');
  card.className = 'version-card mod-card modpack-card section-installed unselectable';
  const packForBulk = { ...pack, addon_type: 'modpacks' };
  const packBulkKey = getModBulkKey(packForBulk);
  const isPackBulkSelected = state.modsBulkState.enabled && state.modsBulkState.selected.has(packBulkKey);

  if (state.modsBulkState.enabled) {
    card.classList.add('bulk-select-active');
    if (isPackBulkSelected) card.classList.add('bulk-selected');
  }

  if (pack.disabled) card.classList.add('mod-card-disabled');

  const icon = document.createElement('img');
  icon.className = 'version-image mod-image mod-card-image';
  const fallbackIcon = getAddonConfig('modpacks').defaultIcon;
  icon.src = pack.icon_url || pack.source_icon_url || fallbackIcon;
  imageAttachErrorPlaceholder(icon, fallbackIcon);

  const info = document.createElement('div');
  info.className = 'version-info mod-card-info';

  const headerRow = document.createElement('div');
  headerRow.className = 'version-header-row';

  const name = document.createElement('div');
  name.className = 'version-display';
  name.textContent = pack.name || pack.slug || 'Unknown Modpack';

  const desc = document.createElement('div');
  desc.className = 'version-folder mod-card-description';
  desc.textContent = pack.description || '';

  headerRow.appendChild(name);
  info.appendChild(headerRow);
  info.appendChild(desc);

  const badgeRow = document.createElement('div');
  badgeRow.className = 'version-badge-row';

  const stateBadge = document.createElement('span');
  const isImported = pack.is_imported !== false && String(pack.install_source || '').toLowerCase() !== 'installed';
  if (pack.disabled) {
    stateBadge.className = 'version-badge paused';
    stateBadge.textContent = t('mods.status.disabled').toUpperCase();
  } else if (isImported) {
    stateBadge.className = 'version-badge imported';
    stateBadge.textContent = t('mods.status.imported').toUpperCase();
  } else {
    stateBadge.className = 'version-badge installed';
    stateBadge.textContent = t('mods.status.installed').toUpperCase();
  }
  badgeRow.appendChild(stateBadge);

  if (pack.mod_loader) {
    const loaderBadge = document.createElement('span');
    loaderBadge.className = 'version-badge lite';
    loaderBadge.textContent = String(pack.mod_loader).toUpperCase();
    badgeRow.appendChild(loaderBadge);
  }

  // Delete icon
  const deleteIconContainer = document.createElement('div');
  deleteIconContainer.className = 'mod-card-delete-icon';
  const delBtn = document.createElement('div');
  delBtn.className = 'icon-button';
  bindKeyboardActivation(delBtn, {
    ariaLabel: state.modsBulkState.enabled
      ? `Toggle selection for modpack ${String(name.textContent || '').trim() || 'this modpack'}`
      : `Delete modpack ${String(name.textContent || '').trim() || 'this modpack'}`,
  });
  const delImg = document.createElement('img');
  delImg.alt = t('common.delete');
  delImg.src = 'assets/images/unfilled_delete.png';
  imageAttachErrorPlaceholder(delImg, 'assets/images/placeholder.png');
  delBtn.appendChild(delImg);
  delBtn.addEventListener('mouseenter', () => { delImg.src = 'assets/images/filled_delete.png'; });
  delBtn.addEventListener('mouseleave', () => { delImg.src = 'assets/images/unfilled_delete.png'; });
  delBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (state.modsBulkState.enabled) {
      toggleModBulkSelection(packForBulk);
      return;
    }
    deleteModpack(pack, { skipConfirm: isShiftDelete(e) });
  });
  deleteIconContainer.appendChild(delBtn);

  // Actions
  const actions = document.createElement('div');
  actions.className = 'version-actions';
  const toggleBtn = document.createElement('button');
  toggleBtn.className = pack.disabled ? 'primary' : 'mild';
  toggleBtn.textContent = pack.disabled ? t('mods.actions.enable') : t('mods.actions.disable');
  toggleBtn.onclick = (e) => {
    e.stopPropagation();
    if (state.modsBulkState.enabled) {
      toggleModBulkSelection(packForBulk);
      return;
    }
    toggleModpackDisabled(pack);
  };
  actions.appendChild(toggleBtn);

  card.appendChild(icon);
  card.appendChild(info);
  card.appendChild(deleteIconContainer);
  card.appendChild(badgeRow);
  card.appendChild(actions);

  if (state.modsBulkState.enabled) {
    const checkbox = document.createElement('div');
    checkbox.className = 'bulk-select-checkbox';
    checkbox.textContent = isPackBulkSelected ? '✔' : '';
    card.appendChild(checkbox);
  }

  card.style.cursor = 'pointer';
  bindKeyboardActivation(card, {
    ariaLabel: state.modsBulkState.enabled
      ? `Toggle selection for modpack ${String(name.textContent || '').trim() || 'this modpack'}`
      : `View details for modpack ${String(name.textContent || '').trim() || 'this modpack'}`,
  });
  if (state.modsBulkState.enabled) {
    card.setAttribute('aria-pressed', isPackBulkSelected ? 'true' : 'false');
  }
  card.addEventListener('click', (e) => {
    if (e.target.closest('button, select, input, .icon-button')) return;
    if (state.modsBulkState.enabled) {
      toggleModBulkSelection(packForBulk);
      return;
    }
    showModpackDetailModal(pack);
  });

  wireCardActionArrowNavigation(card);

  return card;
};

const showModpackDetailModal = (pack) => {
  const content = document.createElement('div');
  content.className = 'mod-detail-content modpack-detail-content';

  if (pack.description) {
    const descEl = document.createElement('p');
    descEl.textContent = pack.description;
    descEl.style.color = 'var(--color-text-soft-alt)';
    descEl.style.marginBottom = '12px';
    content.appendChild(descEl);
  }

  const statsRow = document.createElement('div');
  statsRow.className = 'mod-detail-stats';
  const packResourcepacks = Array.isArray(pack.resourcepacks) ? pack.resourcepacks : [];
  const packShaderpacks = Array.isArray(pack.shaderpacks) ? pack.shaderpacks : [];
  const detailStats = [
    `Loader: ${(pack.mod_loader || '').toUpperCase()}`,
    `Version: ${pack.version || 'N/A'}`,
  ];
  const packAuthor = String(pack.author || '').trim();
  if (packAuthor) detailStats.push(`Author: ${packAuthor}`);
  detailStats.push(
    `Mods: ${(pack.mods || []).length}`,
    `Resource Packs: ${packResourcepacks.length}`,
    `Shader Packs: ${packShaderpacks.length}`,
  );
  detailStats.forEach((text) => {
    const stat = document.createElement('span');
    stat.textContent = text;
    statsRow.appendChild(stat);
  });
  content.appendChild(statsRow);

  const allowAllModloaderOverwrite = _deps.isTruthySetting(state.settingsState.allow_override_classpath_all_modloaders);
  const packLoader = String(pack.mod_loader || '').toLowerCase();
  const canShowOverwriteControls = packLoader === 'modloader' || allowAllModloaderOverwrite;
  const detailMenuSections = [];
  const addDetailMenuSection = (key, title, count, sectionEl) => {
    if (!sectionEl) return;
    detailMenuSections.push({ key, title, count, sectionEl });
  };

  const modsList = pack.mods || [];
  if (modsList.length > 0) {
    const modsSection = document.createElement('div');
    modsSection.style.marginTop = '12px';

    const modsTitle = document.createElement('h4');
    modsTitle.textContent = `Mods (${modsList.length})`;
    modsTitle.style.marginBottom = '8px';
    modsSection.appendChild(modsTitle);

    const viewMode = state.settingsState.addons_view || 'list';
    const modsListEl = document.createElement('div');
    modsListEl.className = 'modpack-detail-mod-list versions-list';
    modsListEl.classList.toggle('list-view', viewMode === 'list');

    modsList.forEach((m) => {
      const card = document.createElement('div');
      card.className = 'version-card mod-card mod-entry-card modpack-detail-mod-entry mod-card-installed';
      card.classList.add('unselectable');
      if (packLoader) card.classList.add(`mod-card-loader-${packLoader}`);
      if (m.disabled) card.classList.add('mod-card-disabled');

      const iconEl = document.createElement('img');
      iconEl.className = 'version-image mod-image mod-card-image';
      iconEl.src = m.icon_url || 'assets/images/java_icon.png';
      iconEl.onerror = () => { iconEl.src = 'assets/images/java_icon.png'; };

      const info = document.createElement('div');
      info.className = 'version-info mod-card-info';

      const headerRow = document.createElement('div');
      headerRow.className = 'version-header-row';

      const nameEl = document.createElement('div');
      nameEl.className = 'version-display';
      nameEl.textContent = m.mod_name || m.mod_slug || 'Unknown';
      headerRow.appendChild(nameEl);
      info.appendChild(headerRow);

      const metaEl = document.createElement('div');
      metaEl.className = 'version-folder mod-card-description';
      const buildMetaText = () => {
        const description = String(m.description || m.summary || '').trim();
        if (description) return description;

        const parts = [];
        const versionLabel = String(m.version_label || '').trim();
        if (versionLabel) parts.push(versionLabel);
        parts.push(m.is_imported === false ? t('mods.status.includedInModpack') : t('mods.status.imported'));
        return parts.join(' | ');
      };
      metaEl.textContent = buildMetaText();
      info.appendChild(metaEl);

      const badgeRow = document.createElement('div');
      badgeRow.className = 'version-badge-row';
      const syncBadgeRow = () => {
        badgeRow.innerHTML = '';

        const stateBadge = document.createElement('span');
        stateBadge.className = m.disabled ? 'version-badge paused' : 'version-badge imported';
        stateBadge.textContent = m.disabled ? t('mods.status.disabled').toUpperCase() : t('mods.status.imported').toUpperCase();
        badgeRow.appendChild(stateBadge);

        const loaderBadge = document.createElement('span');
        loaderBadge.className = 'version-badge size';
        loaderBadge.textContent = String(packLoader || 'mod').toUpperCase();
        badgeRow.appendChild(loaderBadge);
      };
      syncBadgeRow();

      const actions = document.createElement('div');
      actions.className = 'version-actions';

      let overwriteCheckbox = null;
      let sourceRow = null;
      let sourceSelect = null;

      if (canShowOverwriteControls) {
        const overwriteRow = document.createElement('div');
        overwriteRow.className = 'mod-overwrite-row mod-card-control-row';

        const overwriteLabel = document.createElement('span');
        overwriteLabel.className = 'mod-overwrite-label';
        overwriteLabel.textContent = t('mods.exportModpack.overwriteClassesLabel');

        overwriteCheckbox = document.createElement('input');
        overwriteCheckbox.type = 'checkbox';
        overwriteCheckbox.className = 'mod-overwrite-checkbox mod-card-checkbox';
        overwriteCheckbox.checked = !!m.overwrite_classes;
        overwriteCheckbox.title = t('mods.exportModpack.overwriteClassesTitle');

        sourceRow = document.createElement('div');
        sourceRow.className = 'mod-source-row mod-card-control-row';

        const sourceLabel = document.createElement('span');
        sourceLabel.className = 'mod-source-label';
        sourceLabel.textContent = t('mods.exportModpack.sourceFolderLabel');

        sourceSelect = document.createElement('select');
        sourceSelect.className = 'mod-version-select mod-source-select mod-card-select';
        sourceSelect.disabled = !m.overwrite_classes;

        const setSourceOptions = (incomingOptions, preferredValue) => {
          const options = [{ value: '', label: t('mods.exportModpack.defaultSource') }];
          const seen = new Set(['']);

          const list = Array.isArray(incomingOptions) ? incomingOptions : [];
          list.forEach((item) => {
            const rawValue = typeof item === 'string'
              ? item
              : (item && item.value !== undefined ? item.value : (item && item.path !== undefined ? item.path : ''));
            const rawLabel = typeof item === 'string'
              ? item
              : (item && item.label !== undefined ? item.label : (item && item.name !== undefined ? item.name : rawValue));

            const value = String(rawValue || '').trim();
            const label = String(rawLabel || value).trim();
            if (seen.has(value)) return;
            seen.add(value);
            options.push({ value, label: label || value });
          });

          sourceSelect.innerHTML = '';
          options.forEach((optionData) => {
            const option = document.createElement('option');
            option.value = optionData.value;
            option.textContent = optionData.label;
            sourceSelect.appendChild(option);
          });

          const desired = String(preferredValue || '').trim();
          sourceSelect.value = seen.has(desired) ? desired : '';
        };

        const setSourceVisibility = (enabled) => {
          const isEnabled = !!enabled;
          sourceRow.style.display = isEnabled ? 'flex' : 'none';
          sourceSelect.disabled = !isEnabled;
        };

        let sourceLoaded = false;
        const loadSourceOptions = async () => {
          if (sourceLoaded) return true;
          sourceLoaded = true;
          try {
            const res = await api('/api/mods/archive-subfolders', 'POST', {
              mod_slug: m.mod_slug,
              mod_loader: pack.mod_loader,
              version_label: m.version_label,
            });
            if (!res || !res.ok) throw new Error((res && res.error) || t('mods.exportModpack.failedSourceFolders'));
            setSourceOptions(res.subfolders, m.source_subfolder);
            return true;
          } catch (err) {
            console.warn('Failed to load source folders:', err);
            sourceLoaded = false;
            showMessageBox({
              title: t('mods.exportModpack.sourceFolderError'),
              message: (err && err.message) ? err.message : t('mods.exportModpack.failedSourceFoldersFromArchive'),
              buttons: [{ label: t('common.ok') }],
            });
            return false;
          }
        };

        const persistOverwrite = async (nextOverwrite, nextSource) => {
          const res = await api('/api/modpacks/set-mod-overwrite', 'POST', {
            pack_slug: pack.slug,
            mod_slug: m.mod_slug,
            overwrite_classes: nextOverwrite,
            source_subfolder: String(nextSource || ''),
          });
          if (res && res.ok) {
            m.overwrite_classes = !!res.overwrite_classes;
            m.source_subfolder = String(res.source_subfolder || '');
            overwriteCheckbox.checked = m.overwrite_classes;
            setSourceVisibility(m.overwrite_classes);
            sourceSelect.value = m.overwrite_classes ? String(m.source_subfolder || '') : '';
            syncBadgeRow();
            return true;
          }
          showMessageBox({
            title: t('common.error'),
            message: (res && res.error) || t('mods.exportModpack.failedUpdateOverwrite'),
            buttons: [{ label: t('common.ok') }],
          });
          return false;
        };

        overwriteCheckbox.addEventListener('change', async (e) => {
          e.stopPropagation();
          const nextOverwrite = !!overwriteCheckbox.checked;
          const previousValue = String(m.source_subfolder || sourceSelect.value || '');

          overwriteCheckbox.disabled = true;
          setSourceVisibility(nextOverwrite);

          if (nextOverwrite) {
            const loaded = await loadSourceOptions();
            if (!loaded) {
              overwriteCheckbox.checked = false;
              setSourceVisibility(false);
              overwriteCheckbox.disabled = false;
              return;
            }
          } else {
            sourceSelect.value = '';
          }

          const saved = await persistOverwrite(nextOverwrite, nextOverwrite ? String(sourceSelect.value || '') : '');
          if (!saved) {
            overwriteCheckbox.checked = !nextOverwrite;
            setSourceVisibility(!nextOverwrite);
            sourceSelect.value = previousValue;
          }

          overwriteCheckbox.disabled = false;
        });

        setSourceOptions([], m.source_subfolder);
        setSourceVisibility(overwriteCheckbox.checked);
        if (overwriteCheckbox.checked) loadSourceOptions();

        sourceSelect.addEventListener('focus', () => {
          if (overwriteCheckbox.checked) loadSourceOptions();
        });
        sourceSelect.addEventListener('change', async (e) => {
          e.stopPropagation();
          if (!m.overwrite_classes) return;
          const previousValue = String(m.source_subfolder || '');
          sourceSelect.disabled = true;
          const saved = await persistOverwrite(true, sourceSelect.value);
          if (!saved) sourceSelect.value = previousValue;
          sourceSelect.disabled = false;
        });

        overwriteRow.appendChild(overwriteLabel);
        overwriteRow.appendChild(overwriteCheckbox);

        sourceRow.appendChild(sourceLabel);
        sourceRow.appendChild(sourceSelect);

        info.appendChild(overwriteRow);
        info.appendChild(sourceRow);
      }

      const toggleModBtn = document.createElement('button');
      toggleModBtn.className = m.disabled ? 'primary' : 'mild';
      toggleModBtn.textContent = m.disabled ? t('mods.actions.enable') : t('mods.actions.disable');
      toggleModBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        toggleModBtn.disabled = true;
        const newDisabled = !m.disabled;
        const res = await api('/api/modpacks/toggle-mod', 'POST', {
          pack_slug: pack.slug,
          mod_slug: m.mod_slug,
          disabled: newDisabled,
        });
        if (res && res.ok) {
          m.disabled = newDisabled;
          toggleModBtn.className = m.disabled ? 'primary' : 'mild';
          toggleModBtn.textContent = m.disabled ? t('mods.actions.enable') : t('mods.actions.disable');
          card.classList.toggle('mod-card-disabled', m.disabled);
          syncBadgeRow();
        }
        toggleModBtn.disabled = false;
      });

      actions.appendChild(toggleModBtn);

      card.appendChild(iconEl);
      card.appendChild(info);
      card.appendChild(badgeRow);
      card.appendChild(actions);

      modsListEl.appendChild(card);
    });

    modsSection.appendChild(modsListEl);
    addDetailMenuSection('mods', 'Mods', modsList.length, modsSection);
  }

  const appendPackAddonSection = (addonType, entries) => {
    if (!Array.isArray(entries) || entries.length === 0) return;
    const config = getAddonConfig(addonType);
    const section = document.createElement('div');
    section.style.marginTop = '12px';

    const title = document.createElement('h4');
    title.textContent = `${config.pluralTitle} (${entries.length})`;
    title.style.marginBottom = '8px';
    section.appendChild(title);

    const viewMode = state.settingsState.addons_view || 'list';
    const listEl = document.createElement('div');
    listEl.className = 'modpack-detail-mod-list versions-list';
    listEl.classList.toggle('list-view', viewMode === 'list');

    entries.forEach((entry) => {
      const card = document.createElement('div');
      card.className = 'version-card mod-card mod-entry-card modpack-detail-mod-entry mod-card-installed unselectable';
      if (entry.disabled) card.classList.add('mod-card-disabled');

      const iconEl = document.createElement('img');
      iconEl.className = 'version-image mod-image mod-card-image';
      iconEl.src = entry.icon_url || config.defaultIcon;
      imageAttachErrorPlaceholder(iconEl, config.defaultIcon);

      const info = document.createElement('div');
      info.className = 'version-info mod-card-info';

      const headerRow = document.createElement('div');
      headerRow.className = 'version-header-row';
      const nameEl = document.createElement('div');
      nameEl.className = 'version-display';
      nameEl.textContent = entry.mod_name || entry.mod_slug || config.singularTitle;
      headerRow.appendChild(nameEl);
      info.appendChild(headerRow);

      const metaEl = document.createElement('div');
      metaEl.className = 'version-folder mod-card-description';
      const versionLabel = String(entry.version_label || '').trim();
      metaEl.textContent = versionLabel ? `${versionLabel} | Included in this modpack` : 'Included in this modpack';
      info.appendChild(metaEl);

      const badgeRow = document.createElement('div');
      badgeRow.className = 'version-badge-row';
      const syncBadgeRow = () => {
        badgeRow.innerHTML = '';

        const stateBadge = document.createElement('span');
        stateBadge.className = entry.disabled ? 'version-badge paused' : 'version-badge imported';
        stateBadge.textContent = entry.disabled ? t('mods.status.disabled').toUpperCase() : t('mods.status.bundled').toUpperCase();
        badgeRow.appendChild(stateBadge);

        const typeBadge = document.createElement('span');
        typeBadge.className = 'version-badge size';
        typeBadge.textContent = config.singularTitle.toUpperCase();
        badgeRow.appendChild(typeBadge);
      };
      syncBadgeRow();

      const actions = document.createElement('div');
      actions.className = 'version-actions';
      const addonSlug = String(entry.mod_slug || entry.addon_slug || '').trim();
      if (addonSlug) {
        const toggleAddonBtn = document.createElement('button');
        toggleAddonBtn.className = entry.disabled ? 'primary' : 'mild';
        toggleAddonBtn.textContent = entry.disabled ? t('mods.actions.enable') : t('mods.actions.disable');
        toggleAddonBtn.addEventListener('click', async (event) => {
          event.stopPropagation();
          toggleAddonBtn.disabled = true;
          const newDisabled = !entry.disabled;
          try {
            const res = await api('/api/modpacks/toggle-mod', 'POST', {
              pack_slug: pack.slug,
              addon_type: addonType,
              mod_slug: addonSlug,
              disabled: newDisabled,
            });
            if (res && res.ok) {
              entry.disabled = newDisabled;
              toggleAddonBtn.className = entry.disabled ? 'primary' : 'mild';
              toggleAddonBtn.textContent = entry.disabled ? t('mods.actions.enable') : t('mods.actions.disable');
              card.classList.toggle('mod-card-disabled', entry.disabled);
              syncBadgeRow();
            } else {
              showMessageBox({
                title: t('common.error'),
                message: (res && res.error) || t('mods.actions.toggleFailed', { addon: getAddonConfigText('singular') }),
                buttons: [{ label: t('common.ok') }],
              });
            }
          } catch (err) {
            console.error(`Failed to toggle modpack ${addonType} entry:`, err);
            showMessageBox({
              title: t('common.error'),
              message: t('mods.actions.toggleFailed', { addon: getAddonConfigText('singular') }),
              buttons: [{ label: t('common.ok') }],
            });
          }
          toggleAddonBtn.disabled = false;
        });
        actions.appendChild(toggleAddonBtn);
      }

      card.appendChild(iconEl);
      card.appendChild(info);
      card.appendChild(badgeRow);
      card.appendChild(actions);
      listEl.appendChild(card);
    });

    section.appendChild(listEl);
    addDetailMenuSection(addonType, config.pluralTitle, entries.length, section);
  };

  appendPackAddonSection('resourcepacks', packResourcepacks);
  appendPackAddonSection('shaderpacks', packShaderpacks);

  if (detailMenuSections.length > 0) {
    const menuTabs = document.createElement('div');
    menuTabs.className = 'world-nbt-tabs';
    menuTabs.style.marginTop = '12px';

    const menuPanel = document.createElement('div');
    menuPanel.className = 'world-nbt-tab-panel';

    const activateMenu = (key) => {
      detailMenuSections.forEach((section) => {
        const active = section.key === key;
        section.button.classList.toggle('active', active);
        section.sectionEl.classList.toggle('hidden', !active);
      });
    };

    detailMenuSections.forEach((section, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'world-nbt-tab';
      button.textContent = `${section.title} (${section.count})`;
      button.addEventListener('click', () => activateMenu(section.key));
      section.button = button;
      menuTabs.appendChild(button);
      section.sectionEl.classList.toggle('hidden', index !== 0);
      menuPanel.appendChild(section.sectionEl);
    });

    content.appendChild(menuTabs);
    content.appendChild(menuPanel);
    activateMenu(detailMenuSections[0].key);
  }

  showMessageBox({
    title: pack.name || pack.slug || 'Modpack',
    customContent: content,
    boxClassList: ['modpack-detail-dialog'],
    buttons: [{ label: 'Close' }],
  });
};

const toggleModpackDisabled = async (pack) => {
  const newState = !pack.disabled;
  try {
    const res = await api('/api/modpacks/toggle', 'POST', {
      slug: pack.slug,
      disabled: newState,
    });
    if (res && res.ok) {
      loadInstalledMods();
    } else {
      showMessageBox({
        title: t('common.error'),
        message: res.error || t('mods.actions.toggleFailed', { addon: getAddonConfigText('singular') }),
        buttons: [{ label: t('common.ok') }],
      });
    }
  } catch (err) {
    console.error('Failed to toggle modpack:', err);
  }
};

const deleteModpack = (pack, options = {}) => {
  const skipConfirm = !!options.skipConfirm || state.isShiftDown;

  const runDelete = async () => {
    try {
      const res = await api('/api/modpacks/delete', 'POST', { slug: pack.slug });
      if (res && res.ok) {
        loadInstalledMods();
      } else {
        showMessageBox({
          title: t('common.error'),
          message: res.error || 'Failed to delete modpack.',
          buttons: [{ label: t('common.ok') }],
        });
      }
    } catch (err) {
      console.error('Failed to delete modpack:', err);
    }
  };

  if (skipConfirm) {
    runDelete();
    return;
  }

  showMessageBox({
    title: t('mods.delete.title', { addon: t('mods.addonTypes.modpacks.singularTitle') }),
    message: t('mods.delete.confirm', { addon: pack.name || pack.slug }),
    buttons: [
      {
        label: t('common.delete'),
        classList: ['danger'],
        onClick: runDelete,
      },
      { label: t('common.cancel') },
    ],
  });
};

// --- Import Modpack Handler ---
const handleImportModpack = (file) => {
  const fileName = String((file && file.name) || '');
  const ext = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';
  const sourceFormat = ext === 'mrpack' ? 'mrpack' : (ext === 'hlmp' ? 'hlmp' : 'zip');

  const importId = createOperationId('modpack_import');
  let cancelRequested = false;
  const formData = new FormData();
  formData.append('modpack_file', file);
  formData.append('file_name', fileName);
  formData.append('source_format', sourceFormat);
  formData.append('import_id', importId);
  formData.append('operation_id', importId);

  showLoadingOverlay('Importing modpack...', {
    buttons: [
      {
        label: 'Cancel',
        classList: ['danger'],
        closeOnClick: false,
        onClick: async (_values, controls) => {
          if (cancelRequested) return;
          cancelRequested = true;
          controls.update({
            message: 'Cancelling modpack import...',
            buttons: [],
          });
          await requestOperationCancel(importId);
        },
      },
    ],
  });

  const progressInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/modpacks/import/progress/?id=${importId}`);
      const data = await res.json();
      if (!cancelRequested && data && data.ok && data.percent !== undefined) {
        setLoadingOverlayText(`Importing modpack... ${data.percent}%`);
      }
    } catch (e) {
      // ignore errors during polling
    }
  }, 500);

  fetch('/api/modpacks/import', { method: 'POST', body: formData })
    .then((r) => r.json())
    .then((result) => {
      clearInterval(progressInterval);
      hideLoadingOverlay();
      if (result && result.ok) {
        let msg = `Successfully imported modpack <b>${result.name || ''}</b>.`;
        if (result.source_format) {
          msg += `<br><br>Detected format: <b>${String(result.source_format).toUpperCase()}</b>.`;
        }
        if (result.disabled_standalone && result.disabled_standalone.length > 0) {
          msg += `<br><br>The following standalone mods were disabled because they conflict with the modpack:<br>` +
                  result.disabled_standalone.map((s) => `- ${s}`).join('<br>');
        }
        if (result.import_warnings && result.import_warnings.length > 0) {
          const preview = result.import_warnings.slice(0, 8).map((w) => `- ${w}`).join('<br>');
          const more = result.import_warnings.length > 8 ? `<br>...and ${result.import_warnings.length - 8} more warning(s).` : '';
          msg += `<br><br>Import warnings:<br>${preview}${more}`;
        }
        showMessageBox({
          title: 'Import Successful',
          message: msg,
          buttons: [{ label: 'OK' }],
        });
        loadInstalledMods();
      } else {
        if (result && (result.cancelled || String(result.error || '').toLowerCase().includes('cancelled'))) {
          showMessageBox({
            title: 'Import Cancelled',
            message: 'You cancelled the modpack import.',
            buttons: [{ label: 'OK' }],
          });
          return;
        }
        showMessageBox({
          title: 'Import Error',
          message: result.error || 'Failed to import modpack.',
          buttons: [{ label: 'OK' }],
        });
      }
    })
    .catch((err) => {
      clearInterval(progressInterval);
      hideLoadingOverlay();
      console.error('Failed to import modpack:', err);
      showMessageBox({
        title: 'Import Error',
        message: 'Network error while importing modpack.',
        buttons: [{ label: 'OK' }],
      });
    });
};

// --- Export Modpack Wizard ---
const MODPACK_EXPORT_FORMATS = [
  {
    value: 'histolauncher',
    label: 'Histolauncher',
    extension: '.hlmp',
    description: 'Histolauncher Modpack (.hlmp)',
  },
  {
    value: 'modrinth',
    label: 'Modrinth',
    extension: '.mrpack',
    description: 'Modrinth Modpack (.mrpack)',
  },
  {
    value: 'curseforge',
    label: 'CurseForge',
    extension: '.zip',
    description: 'CurseForge Modpack (.zip)',
  },
];

const getModpackExportFormat = (value) => (
  MODPACK_EXPORT_FORMATS.find((entry) => entry.value === value)
  || MODPACK_EXPORT_FORMATS[0]
);

const showExportModpackWizard = () => {
  const content = document.createElement('div');
  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.textContent = t('mods.exportModpack.selectFormat');

  const formatSelect = document.createElement('select');
  formatSelect.className = 'mod-version-select';
  formatSelect.style.cssText = 'width:100%;margin-top:4px;max-width:100%;';
  MODPACK_EXPORT_FORMATS.forEach((format) => {
    const opt = document.createElement('option');
    opt.value = format.value;
    opt.textContent = `${format.label} (${format.extension})`;
    formatSelect.appendChild(opt);
  });

  content.appendChild(label);
  content.appendChild(formatSelect);

  showMessageBox({
    title: t('mods.exportModpack.title'),
    customContent: content,
    buttons: [
      {
        label: t('common.next'),
        classList: ['primary'],
        onClick: () => showExportLoaderStep(formatSelect.value),
      },
      { label: t('common.cancel') },
    ],
  });
};

const showExportLoaderStep = (exportFormat = 'histolauncher') => {
  const step1Content = document.createElement('div');
  const step1Label = document.createElement('p');
  step1Label.style.marginBottom = '8px';
  step1Label.textContent = t('mods.exportModpack.selectLoader');

  const loaderSelect = document.createElement('select');
  loaderSelect.className = 'mod-version-select';
  loaderSelect.style.cssText = 'width:100%;margin-top:4px;max-width:100%;';
  LOADER_UI_ORDER.forEach((loaderType) => {
    const loaderName = getLoaderUi(loaderType).name;
    const opt = document.createElement('option');
    opt.value = loaderType;
    opt.textContent = loaderName;
    loaderSelect.appendChild(opt);
  });

  step1Content.appendChild(step1Label);
  step1Content.appendChild(loaderSelect);

  showMessageBox({
    title: t('mods.exportModpack.title'),
    customContent: step1Content,
    buttons: [
      {
        label: t('common.back'),
        onClick: () => showExportModpackWizard(),
      },
      {
        label: t('common.next'),
        classList: ['primary'],
        onClick: () => showExportStep2(exportFormat, loaderSelect.value),
      },
      { label: t('common.cancel') },
    ],
  });
};

const showExportStep2 = async (exportFormat, modLoader) => {
  // Step 2: Mod selection
  let installedMods = modsState.installedMods || [];
  if (!isModsAddonType()) {
    try {
      const res = await api('/api/addons/installed', 'POST', { addon_type: 'mods' });
      if (res && res.ok) installedMods = res.addons || res.mods || [];
    } catch (err) {
      console.warn('Failed to load mods for modpack export:', err);
    }
  }

  const modsForLoader = installedMods.filter(
    (m) => (m.mod_loader || '').toLowerCase() === modLoader
  );

  if (modsForLoader.length === 0) {
    showMessageBox({
      title: t('mods.exportModpack.title'),
      message: t('mods.exportModpack.noLoaderMods', { loader: modLoader }),
      buttons: [{ label: t('common.ok') }],
    });
    return;
  }

  const step2Content = document.createElement('div');
  const step2Label = document.createElement('p');
  step2Label.style.marginBottom = '8px';
  step2Label.textContent = t('mods.exportModpack.selectMods', { count: modsForLoader.length, loader: modLoader });
  step2Content.appendChild(step2Label);

  const selectAll = document.createElement('label');
  selectAll.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px;cursor:pointer;font-size:12px;color:var(--color-text-muted);';
  const selectAllCb = document.createElement('input');
  selectAllCb.type = 'checkbox';
  selectAll.appendChild(selectAllCb);
  selectAll.appendChild(document.createTextNode(t('common.selectAll')));
  step2Content.appendChild(selectAll);

  const disableHint = document.createElement('p');
  disableHint.style.cssText = 'font-size:11px;color:var(--color-text-muted);margin:0 0 8px 0;';
  disableHint.textContent = t('mods.exportModpack.disabledHint');
  step2Content.appendChild(disableHint);

  const allowAllModloaderOverwrite = _deps.isTruthySetting(state.settingsState.allow_override_classpath_all_modloaders);
  const canShowOverwriteControls = (String(modLoader || '').toLowerCase() === 'modloader') || allowAllModloaderOverwrite;

  if (canShowOverwriteControls) {
    const overwriteHint = document.createElement('p');
    overwriteHint.style.cssText = 'font-size:11px;color:var(--color-text-muted);margin:0 0 8px 0;';
    overwriteHint.textContent = t('mods.exportModpack.overwriteHint');
    step2Content.appendChild(overwriteHint);
  }

  const modListEl = document.createElement('div');
  modListEl.style.cssText = 'max-height:320px;overflow-y:auto;border:1px solid var(--color-border-input);padding:8px;';

  const modEntries = [];

  modsForLoader.forEach((mod) => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--color-border-input);flex-wrap:wrap;';

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = false;

    const disabledWrap = document.createElement('label');
    disabledWrap.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:11px;color:var(--color-text-muted);white-space:nowrap;';
    const disabledCb = document.createElement('input');
    disabledCb.type = 'checkbox';
    disabledCb.checked = false;
    const disabledTxt = document.createElement('span');
    disabledTxt.textContent = t('mods.exportModpack.disabled');
    disabledWrap.appendChild(disabledCb);
    disabledWrap.appendChild(disabledTxt);

    let overwriteCb = null;
    let overwriteWrap = null;
    let sourceWrap = null;
    let sourceSelect = null;

    const sourceMeta = (mod.versions || []).find((v) => v.version_label === mod.active_version)
      || (mod.versions || [])[0]
      || null;

    if (canShowOverwriteControls) {
      overwriteWrap = document.createElement('label');
      overwriteWrap.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:11px;color:var(--color-text-muted);white-space:nowrap;';
      overwriteCb = document.createElement('input');
      overwriteCb.type = 'checkbox';
      overwriteCb.checked = !!(sourceMeta && sourceMeta.overwrite_classes);
      const overwriteTxt = document.createElement('span');
      overwriteTxt.textContent = t('mods.exportModpack.overwriteClasspath');
      overwriteWrap.appendChild(overwriteCb);
      overwriteWrap.appendChild(overwriteTxt);

      sourceWrap = document.createElement('label');
      sourceWrap.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:11px;color:var(--color-text-muted);white-space:nowrap;';
      const sourceTxt = document.createElement('span');
      sourceTxt.textContent = t('mods.exportModpack.sourceLabel');
      sourceSelect = document.createElement('select');
      sourceSelect.className = 'mod-version-select';
      sourceSelect.style.cssText = 'max-width:160px;font-size:11px;';
      const placeholder = document.createElement('option');
      placeholder.value = String((sourceMeta && sourceMeta.source_subfolder) || '');
      placeholder.textContent = placeholder.value || t('mods.exportModpack.defaultSource');
      sourceSelect.appendChild(placeholder);
      sourceSelect.disabled = !overwriteCb.checked;
      sourceWrap.style.display = overwriteCb.checked ? '' : 'none';
      sourceWrap.appendChild(sourceTxt);
      sourceWrap.appendChild(sourceSelect);

      let sourceLoadedFor = null;
      const populateSourceFolders = async (versionLabel) => {
        if (!overwriteCb.checked) return;
        if (sourceLoadedFor === versionLabel) return;
        sourceLoadedFor = versionLabel;
        const preferred = String((sourceMeta && sourceMeta.source_subfolder) || '');
        try {
          const res = await api('/api/mods/archive-subfolders', 'POST', {
            mod_slug: mod.mod_slug,
            mod_loader: mod.mod_loader,
            version_label: versionLabel,
          });
          if (!res || !res.ok) throw new Error((res && res.error) || t('mods.exportModpack.failedSourceFolders'));
          const subfolders = Array.isArray(res.subfolders) ? res.subfolders : [];
          const seen = new Set();
          sourceSelect.innerHTML = '';
          const optDefault = document.createElement('option');
          optDefault.value = '';
          optDefault.textContent = t('mods.exportModpack.defaultSource');
          sourceSelect.appendChild(optDefault);
          seen.add('');
          subfolders.forEach((entry) => {
            const value = typeof entry === 'string'
              ? entry
              : String((entry && (entry.value !== undefined ? entry.value : entry.path)) || '').trim();
            const labelText = typeof entry === 'string'
              ? entry
              : String((entry && (entry.label !== undefined ? entry.label : entry.name)) || value).trim();
            if (seen.has(value)) return;
            seen.add(value);
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = labelText || value;
            sourceSelect.appendChild(opt);
          });
          sourceSelect.value = seen.has(preferred) ? preferred : '';
        } catch (err) {
          console.warn('Failed to load source folders for export wizard:', err);
        }
      };

      overwriteCb.addEventListener('change', () => {
        const enabled = overwriteCb.checked;
        sourceSelect.disabled = !enabled;
        sourceWrap.style.display = enabled ? '' : 'none';
        if (enabled) populateSourceFolders(versionSel.value);
      });
    }

    const label = document.createElement('span');
    label.style.cssText = 'flex:1;font-size:13px;color:var(--color-text-primary);';
    label.textContent = mod.mod_name || mod.mod_slug;

    const versionSel = document.createElement('select');
    versionSel.className = 'mod-version-select';
    versionSel.style.cssText = 'max-width:140px;';
    (mod.versions || []).forEach((v) => {
      const opt = document.createElement('option');
      opt.value = v.version_label;
      opt.textContent = v.version_label;
      if (v.version_label === mod.active_version) opt.selected = true;
      versionSel.appendChild(opt);
    });

    versionSel.addEventListener('change', () => {
      const selectedVersion = (mod.versions || []).find((v) => v.version_label === versionSel.value) || null;
      if (overwriteCb) {
        overwriteCb.checked = !!(selectedVersion && selectedVersion.overwrite_classes);
        sourceSelect.disabled = !overwriteCb.checked;
        sourceWrap.style.display = overwriteCb.checked ? '' : 'none';
        if (overwriteCb.checked) {
          // Force reload for new version
          sourceSelect.innerHTML = '';
          const placeholder = document.createElement('option');
          placeholder.value = String((selectedVersion && selectedVersion.source_subfolder) || '');
          placeholder.textContent = placeholder.value || t('mods.exportModpack.defaultSource');
          sourceSelect.appendChild(placeholder);
        }
      }
    });

    row.appendChild(cb);
    row.appendChild(label);
    row.appendChild(disabledWrap);
    if (overwriteWrap) row.appendChild(overwriteWrap);
    if (sourceWrap) row.appendChild(sourceWrap);
    row.appendChild(versionSel);
    modListEl.appendChild(row);

    modEntries.push({
      mod,
      checkbox: cb,
      disabledCheckbox: disabledCb,
      overwriteCheckbox: overwriteCb,
      sourceSelect,
      versionSelect: versionSel,
    });

    if (canShowOverwriteControls && overwriteCb && overwriteCb.checked) {
      // Trigger source folder load asynchronously for initial state
      overwriteCb.dispatchEvent(new Event('change'));
    }
  });

  selectAllCb.addEventListener('change', () => {
    modEntries.forEach((e) => {
      e.checkbox.checked = selectAllCb.checked;
    });
  });

  step2Content.appendChild(modListEl);

  showMessageBox({
    title: t('mods.exportModpack.title'),
    customContent: step2Content,
    buttons: [
      {
        label: t('common.back'),
        onClick: () => showExportLoaderStep(exportFormat),
      },
      {
        label: t('common.next'),
        classList: ['primary'],
        onClick: () => {
          const selected = modEntries
            .filter((e) => e.checkbox.checked)
            .map((e) => {
              const selectedVersion = (e.mod.versions || []).find((v) => v.version_label === e.versionSelect.value) || null;
              const overwriteOn = !!(e.overwriteCheckbox && e.overwriteCheckbox.checked);
              const sourceFromSelect = e.sourceSelect ? String(e.sourceSelect.value || '') : '';
              const sourceFromMeta = String((selectedVersion && selectedVersion.source_subfolder) || '');
              return {
                mod_slug: e.mod.mod_slug,
                version_label: e.versionSelect.value,
                mod_name: e.mod.mod_name || e.mod.mod_slug,
                disabled: e.disabledCheckbox.checked,
                overwrite_classes: overwriteOn,
                source_subfolder: overwriteOn ? (sourceFromSelect || sourceFromMeta) : '',
              };
            });
          if (selected.length === 0) {
            showMessageBox({
              title: t('mods.exportModpack.title'),
              message: t('mods.exportModpack.selectAtLeastOneMod'),
              buttons: [{ label: t('common.ok'), onClick: () => showExportStep2(exportFormat, modLoader) }],
            });
            return;
          }
          showExportResourcePacksStep(exportFormat, modLoader, selected);
        },
      },
      { label: t('common.cancel') },
    ],
  });
};

const loadInstalledAddonsForModpackExport = async (addonType) => {
  try {
    const res = await api('/api/addons/installed', 'POST', { addon_type: addonType });
    if (res && res.ok) return res.addons || res.mods || [];
  } catch (err) {
    console.warn(`Failed to load ${addonType} for modpack export:`, err);
  }
  return [];
};

const showExportAddonSelectionStep = async (
  exportFormat,
  modLoader,
  selectedMods,
  addonType,
  selectedResourcepacks = []
) => {
  const config = getAddonConfig(addonType);
  const installedAddons = await loadInstalledAddonsForModpackExport(addonType);
  const isResourceStep = addonType === 'resourcepacks';
  const stepContent = document.createElement('div');

  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.textContent = installedAddons.length > 0
    ? t('mods.exportModpack.selectOptionalAddons', { plural: getAddonConfigText('plural', addonType), count: installedAddons.length })
    : t('mods.exportModpack.noOptionalAddons', { plural: getAddonConfigText('plural', addonType) });
  stepContent.appendChild(label);

  const addonEntries = [];
  if (installedAddons.length > 0) {
    const selectAll = document.createElement('label');
    selectAll.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px;cursor:pointer;font-size:12px;color:var(--color-text-muted);';
    const selectAllCb = document.createElement('input');
    selectAllCb.type = 'checkbox';
    selectAll.appendChild(selectAllCb);
    selectAll.appendChild(document.createTextNode(t('common.selectAll')));
    stepContent.appendChild(selectAll);

    const addonListEl = document.createElement('div');
    addonListEl.style.cssText = 'max-height:320px;overflow-y:auto;border:1px solid var(--color-border-input);padding:8px;';

    installedAddons.forEach((addon) => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--color-border-input);flex-wrap:wrap;';

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = false;

      const labelEl = document.createElement('span');
      labelEl.style.cssText = 'flex:1;font-size:13px;color:var(--color-text-primary);';
      labelEl.textContent = addon.mod_name || addon.mod_slug || addon.name || 'Unknown';

      const versionSel = document.createElement('select');
      versionSel.className = 'mod-version-select';
      versionSel.style.cssText = 'max-width:160px;';
      (addon.versions || []).forEach((versionEntry) => {
        const opt = document.createElement('option');
        opt.value = versionEntry.version_label;
        opt.textContent = versionEntry.version_label;
        if (versionEntry.version_label === addon.active_version) opt.selected = true;
        versionSel.appendChild(opt);
      });

      row.appendChild(cb);
      row.appendChild(labelEl);
      row.appendChild(versionSel);
      addonListEl.appendChild(row);

      addonEntries.push({ addon, checkbox: cb, versionSelect: versionSel });
    });

    selectAllCb.addEventListener('change', () => {
      addonEntries.forEach((entry) => {
        entry.checkbox.checked = selectAllCb.checked;
      });
    });

    stepContent.appendChild(addonListEl);
  }

  const continueWithSelection = () => {
    const selectedAddons = addonEntries
      .filter((entry) => entry.checkbox.checked)
      .map((entry) => ({
        mod_slug: entry.addon.mod_slug,
        version_label: entry.versionSelect.value,
        mod_name: entry.addon.mod_name || entry.addon.mod_slug,
        disabled: false,
      }))
      .filter((entry) => entry.mod_slug && entry.version_label);

    if (isResourceStep) {
      showExportShaderPacksStep(exportFormat, modLoader, selectedMods, selectedAddons);
    } else {
      showExportStep3(exportFormat, modLoader, selectedMods, selectedResourcepacks, selectedAddons);
    }
  };

  showMessageBox({
    title: t('mods.exportModpack.title'),
    customContent: stepContent,
    buttons: [
      {
        label: t('common.back'),
        onClick: () => (isResourceStep
          ? showExportStep2(exportFormat, modLoader)
          : showExportResourcePacksStep(exportFormat, modLoader, selectedMods)),
      },
      {
        label: t('common.next'),
        classList: ['primary'],
        onClick: continueWithSelection,
      },
      { label: t('common.cancel') },
    ],
  });
};

const showExportResourcePacksStep = (exportFormat, modLoader, selectedMods) => (
  showExportAddonSelectionStep(exportFormat, modLoader, selectedMods, 'resourcepacks')
);

const showExportShaderPacksStep = (exportFormat, modLoader, selectedMods, selectedResourcepacks) => (
  showExportAddonSelectionStep(exportFormat, modLoader, selectedMods, 'shaderpacks', selectedResourcepacks)
);

const showExportStep3 = (exportFormat, modLoader, selectedMods, selectedResourcepacks = [], selectedShaderpacks = []) => {
  const step3Content = document.createElement('div');

  const makeField = (labelText, inputType, maxLen, placeholder) => {
    const wrap = document.createElement('div');
    wrap.style.marginBottom = '10px';
    const lbl = document.createElement('label');
    lbl.style.cssText = 'display:block;font-size:12px;color:var(--color-text-muted);margin-bottom:4px;';
    lbl.textContent = labelText;
    wrap.appendChild(lbl);
    if (inputType === 'textarea') {
      const ta = document.createElement('textarea');
      ta.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;background:var(--color-surface-input);border:1px solid var(--color-border-input);color:var(--color-text-primary);resize:vertical;min-height:60px;';
      ta.maxLength = maxLen;
      ta.placeholder = placeholder || '';
      wrap.appendChild(ta);
      return { wrap, input: ta };
    }
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;background:var(--color-surface-input);border:1px solid var(--color-border-input);color:var(--color-text-primary);';
    inp.maxLength = maxLen;
    inp.placeholder = placeholder || '';
    wrap.appendChild(inp);
    return { wrap, input: inp };
  };

  const nameField = makeField(t('mods.exportModpack.fields.name'), 'text', 64, t('mods.exportModpack.placeholders.name'));
  const versionField = makeField(t('mods.exportModpack.fields.version'), 'text', 16, '1.0.0');
  const authorField = makeField(t('mods.exportModpack.fields.author'), 'text', 64, t('mods.exportModpack.placeholders.author'));
  const descField = makeField(t('mods.exportModpack.fields.description'), 'textarea', 8192, t('mods.exportModpack.placeholders.description'));

  step3Content.appendChild(nameField.wrap);
  step3Content.appendChild(versionField.wrap);
  step3Content.appendChild(authorField.wrap);
  step3Content.appendChild(descField.wrap);

  // Image upload
  const imgWrap = document.createElement('div');
  imgWrap.style.marginBottom = '10px';
  const imgLabel = document.createElement('label');
  imgLabel.style.cssText = 'display:block;font-size:12px;color:var(--color-text-soft-alt);margin-bottom:4px;align:center;';
  imgLabel.textContent = t('mods.exportModpack.fields.icon');
  imgWrap.appendChild(imgLabel);

  const imgRow = document.createElement('div');
  imgRow.style.cssText = 'display:flex;align-items:center;gap:10px;';

  const imgPreview = document.createElement('img');
  imgPreview.style.cssText = 'width:64px;height:64px;object-fit:cover;border:2px solid var(--color-border-quiet);display:none;';

  const imgInput = document.createElement('input');
  imgInput.type = 'file';
  imgInput.accept = 'image/png,image/jpeg';
  imgInput.style.display = 'none';

  const imgPickBtn = document.createElement('button');
  imgPickBtn.type = 'button';
  imgPickBtn.textContent = t('common.chooseFile');

  const imgPickLabel = document.createElement('span');
  imgPickLabel.style.cssText =
    'font-size:12px;color:var(--color-text-muted);overflow-wrap:anywhere;font-style:italic;';
  imgPickLabel.textContent = t('common.noFileChosen');

  const renderImgPickLabel = () => {
    const file = imgInput.files && imgInput.files[0];
    if (file && file.name) {
      imgPickLabel.textContent = file.name;
      imgPickLabel.style.color = 'var(--color-text-secondary-strong)';
      imgPickLabel.style.fontStyle = 'normal';
    } else {
      imgPickLabel.textContent = t('common.noFileChosen');
      imgPickLabel.style.color = 'var(--color-text-muted)';
      imgPickLabel.style.fontStyle = 'italic';
    }
  };

  let imageBase64 = null;
  imgPickBtn.addEventListener('click', () => imgInput.click());
  imgInput.addEventListener('change', () => {
    renderImgPickLabel();
    const file = imgInput.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      imageBase64 = e.target.result.split(',')[1]; // strip data:... prefix
      imgPreview.src = e.target.result;
      imgPreview.style.display = 'block';
    };
    reader.readAsDataURL(file);
  });

  imgRow.appendChild(imgPreview);
  imgRow.appendChild(imgPickBtn);
  imgRow.appendChild(imgPickLabel);
  imgRow.appendChild(imgInput);
  imgWrap.appendChild(imgRow);
  step3Content.appendChild(imgWrap);

  const summary = document.createElement('p');
  summary.style.cssText = 'font-size:12px;color:var(--color-text-muted);margin-top:8px;';
  const formatInfo = getModpackExportFormat(exportFormat);
  summary.textContent = t('mods.exportModpack.summary', {
    format: formatInfo.label,
    extension: formatInfo.extension,
    mods: selectedMods.length,
    resourcepacks: selectedResourcepacks.length,
    shaderpacks: selectedShaderpacks.length,
    loader: modLoader,
  });
  step3Content.appendChild(summary);

  showMessageBox({
    title: t('mods.exportModpack.title'),
    customContent: step3Content,
    buttons: [
      {
        label: t('common.back'),
        onClick: () => showExportShaderPacksStep(exportFormat, modLoader, selectedMods, selectedResourcepacks),
      },
      {
        label: t('common.export'),
        classList: ['primary'],
        onClick: async () => {
          const packName = nameField.input.value.trim();
          const packVersion = versionField.input.value.trim();
          const packAuthor = authorField.input.value.trim();
          const packDesc = descField.input.value.trim();

          if (!packName || packName.length > 64) {
            showMessageBox({ title: t('common.error'), message: t('mods.exportModpack.validation.nameLength'), buttons: [{ label: t('common.ok'), onClick: () => showExportStep3(exportFormat, modLoader, selectedMods, selectedResourcepacks, selectedShaderpacks) }] });
            return;
          }
          if (/[<>:"/\\|?*]/.test(packName)) {
            showMessageBox({ title: t('common.error'), message: t('mods.exportModpack.validation.nameForbidden'), buttons: [{ label: t('common.ok'), onClick: () => showExportStep3(exportFormat, modLoader, selectedMods, selectedResourcepacks, selectedShaderpacks) }] });
            return;
          }
          if (!packVersion || packVersion.length > 16) {
            showMessageBox({ title: t('common.error'), message: t('mods.exportModpack.validation.versionLength'), buttons: [{ label: t('common.ok'), onClick: () => showExportStep3(exportFormat, modLoader, selectedMods, selectedResourcepacks, selectedShaderpacks) }] });
            return;
          }
          if (packAuthor.length > 64) {
            showMessageBox({ title: t('common.error'), message: t('mods.exportModpack.validation.authorLength'), buttons: [{ label: t('common.ok'), onClick: () => showExportStep3(exportFormat, modLoader, selectedMods, selectedResourcepacks, selectedShaderpacks) }] });
            return;
          }
          if (/[<>:"/\\|?*]/.test(packAuthor)) {
            showMessageBox({ title: t('common.error'), message: t('mods.exportModpack.validation.authorForbidden'), buttons: [{ label: t('common.ok'), onClick: () => showExportStep3(exportFormat, modLoader, selectedMods, selectedResourcepacks, selectedShaderpacks) }] });
            return;
          }

          try {
            const operationId = createOperationId('modpack_export');
            let cancelRequested = false;

            showLoadingOverlay(t('mods.exportModpack.exporting'), {
              buttons: [
                {
                  label: t('common.cancel'),
                  classList: ['danger'],
                  closeOnClick: false,
                  onClick: async (_values, controls) => {
                    if (cancelRequested) return;
                    cancelRequested = true;
                    controls.update({
                      message: t('mods.exportModpack.cancelling'),
                      buttons: [],
                    });
                    await requestOperationCancel(operationId);
                  },
                },
              ],
            });

            const res = await api('/api/modpacks/export', 'POST', {
              export_format: exportFormat,
              name: packName,
              version: packVersion,
              author: packAuthor,
              description: packDesc,
              mod_loader: modLoader,
              mods: selectedMods,
              resourcepacks: selectedResourcepacks,
              shaderpacks: selectedShaderpacks,
              image_data: imageBase64 || null,
              save_to_disk: true,
              operation_id: operationId,
            });

            if (res && res.ok) {
              if (res.filepath) {
                hideLoadingOverlay();
                const fileSize = Number(res.size_bytes || 0);
                const fileSizeMb = fileSize > 0 ? (fileSize / (1024 * 1024)).toFixed(2) : null;
                showMessageBox({
                  title: t('mods.exportModpack.successTitle'),
                  message: fileSizeMb
                    ? t('mods.exportModpack.successSavedSize', { name: packName, filepath: res.filepath, size: fileSizeMb })
                    : t('mods.exportModpack.successSaved', { name: packName, filepath: res.filepath }),
                  buttons: [{ label: t('common.ok') }],
                });
                return;
              }

              if (res.modpack_data || res.hlmp_data) {
                const fileName = res.filename || `${packName}${formatInfo.extension}`;
                const bytes = Uint8Array.from(atob(res.modpack_data || res.hlmp_data), (c) => c.charCodeAt(0));
                const blob = new Blob([bytes], { type: 'application/octet-stream' });
                let savedLabel = '';

                if (window.showSaveFilePicker) {
                  try {
                    const fileHandle = await window.showSaveFilePicker({
                      suggestedName: fileName,
                      types: [{
                        description: res.type_description || formatInfo.description,
                        accept: { 'application/octet-stream': [res.extension || formatInfo.extension] },
                      }],
                    });
                    const writable = await fileHandle.createWritable();
                    await writable.write(blob);
                    await writable.close();
                    savedLabel = fileName;
                  } catch (saveErr) {
                    if (saveErr && saveErr.name === 'AbortError') {
                      hideLoadingOverlay();
                      showMessageBox({
                        title: t('mods.exportModpack.cancelledTitle'),
                        message: t('mods.exportModpack.cancelledMessage'),
                        buttons: [{ label: t('common.ok') }],
                      });
                      return;
                    }
                    console.error('Save dialog failed, falling back to download:', saveErr);
                  }
                }

                if (!savedLabel) {
                  try {
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = fileName;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                    savedLabel = `Downloads/${fileName}`;
                  } catch (downloadErr) {
                    hideLoadingOverlay();
                    showMessageBox({
                      title: t('mods.exportModpack.errorTitle'),
                      message: t('mods.exportModpack.failedSave', { error: (downloadErr && downloadErr.message) || t('common.unknownError') }),
                      buttons: [{ label: t('common.ok') }],
                    });
                    return;
                  }
                }

                hideLoadingOverlay();
                showMessageBox({
                  title: t('mods.exportModpack.successTitle'),
                  message: t('mods.exportModpack.successSavedAs', { name: packName, filepath: savedLabel }),
                  buttons: [{ label: t('common.ok') }],
                });
                return;
              }
            }

            hideLoadingOverlay();
            if (res && (res.cancelled || String(res.error || '').toLowerCase().includes('cancelled'))) {
              showMessageBox({
                title: t('mods.exportModpack.cancelledTitle'),
                message: t('mods.exportModpack.cancelledMessage'),
                buttons: [{ label: t('common.ok') }],
              });
            } else {
              showMessageBox({
                title: t('mods.exportModpack.errorTitle'),
                message: (res && res.error) || t('mods.exportModpack.failed'),
                buttons: [{ label: t('common.ok') }],
              });
            }
          } catch (err) {
            hideLoadingOverlay();
            console.error('Failed to export modpack:', err);
            showMessageBox({
              title: t('mods.exportModpack.errorTitle'),
              message: t('mods.exportModpack.failedWithError', { error: (err && err.message) || t('mods.exportModpack.networkError') }),
              buttons: [{ label: t('common.ok') }],
            });
          }
        },
      },
      { label: t('common.cancel') },
    ],
  });
};
