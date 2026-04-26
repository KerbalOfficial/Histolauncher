// ui/modules/worlds.js

import { state } from './state.js';
import {
  $,
  getEl,
  bindKeyboardActivation,
  wireCardActionArrowNavigation,
  imageAttachErrorPlaceholder,
  isShiftDelete,
} from './dom-utils.js';
import { unicodeList } from './config.js';
import { api, createOperationId } from './api.js';
import { showMessageBox } from './modal.js';
import { showLoadingOverlay, hideLoadingOverlay, setLoadingOverlayText } from './modal.js';
import { refreshActionOverflowMenus } from './action-overflow.js';
import { initTooltips } from './tooltips.js';
import { renderCommonPagination } from './pagination.js';
import { formatBytes } from './string-utils.js';
import { createEmptyState, createInlineLoadingState } from './ui-states.js';
import { buildWorldNbtTreeEditor } from './worlds-nbt-tree.js';

let _autoSaveSetting = () => {
  throw new Error('worlds.js: autoSaveSetting was not configured. Call setAutoSaveSetting() first.');
};
export const setAutoSaveSetting = (fn) => {
  _autoSaveSetting = fn;
};

// ---------------- Worlds Page ----------------

const WORLDS_PAGE_SIZE = 20;
const WORLD_ICON_SIZE = 64;

let worldsState = {
  provider: 'curseforge',
  storageTarget: 'default',
  customPath: '',
  searchQuery: '',
  gameVersion: '',
  category: '',
  sortBy: 'relevance',
  currentPage: 1,
  totalPages: 1,
  categoryOptions: [],
  availableWorldsRaw: [],
  availableWorlds: [],
  installedWorlds: [],
  storageOptions: [],
  versionOptions: [],
  storageLabel: 'Default',
  storagePath: '',
  installedLoading: false,
  installedError: null,
  searchRequestId: 0,
  lastError: null,
};

const clampWorldInstallPercent = (value) => Math.max(0, Math.min(100, Number(value) || 0));

const normalizeWorldIconFileToDataUrl = (file) => new Promise((resolve, reject) => {
  const objectUrl = URL.createObjectURL(file);
  const image = new Image();

  image.onload = () => {
    try {
      const sourceWidth = image.naturalWidth || image.width;
      const sourceHeight = image.naturalHeight || image.height;
      if (!sourceWidth || !sourceHeight) {
        throw new Error('World icon PNG could not be decoded.');
      }

      const canvas = document.createElement('canvas');
      canvas.width = WORLD_ICON_SIZE;
      canvas.height = WORLD_ICON_SIZE;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        throw new Error('World icon PNG could not be prepared.');
      }

      const sourceSize = Math.min(sourceWidth, sourceHeight);
      const sourceX = Math.floor((sourceWidth - sourceSize) / 2);
      const sourceY = Math.floor((sourceHeight - sourceSize) / 2);

      ctx.clearRect(0, 0, WORLD_ICON_SIZE, WORLD_ICON_SIZE);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(
        image,
        sourceX,
        sourceY,
        sourceSize,
        sourceSize,
        0,
        0,
        WORLD_ICON_SIZE,
        WORLD_ICON_SIZE
      );
      resolve(canvas.toDataURL('image/png'));
    } catch (err) {
      reject(err);
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  };

  image.onerror = () => {
    URL.revokeObjectURL(objectUrl);
    reject(new Error('World icon must be a valid PNG file.'));
  };
  image.src = objectUrl;
});

const formatWorldInstallProgressText = (progress, fallback = 'Downloading') => {
  const pct = Math.round(clampWorldInstallPercent(progress && progress.overall_percent));
  const message = String((progress && progress.message) || '').trim();
  const bytesDone = Number((progress && progress.bytes_done) || 0);
  const bytesTotal = Number((progress && progress.bytes_total) || 0);
  const base = bytesTotal > 0
    ? `${pct}% (${formatBytes(bytesDone)} / ${formatBytes(bytesTotal)})`
    : `${pct}%`;
  if (message && message !== fallback) return `${base} - ${message}`;
  return message || base || fallback;
};

const ensureWorldInstallProgressElements = (card) => {
  if (!card) return null;
  if (card._worldInstallProgressFill && card._worldInstallProgressTextEl) {
    return { fill: card._worldInstallProgressFill, text: card._worldInstallProgressTextEl };
  }

  const progressBar = document.createElement('div');
  progressBar.className = 'version-progress world-install-progress';

  const fill = document.createElement('div');
  fill.className = 'version-progress-fill';
  progressBar.appendChild(fill);

  const progressText = document.createElement('div');
  progressText.className = 'version-progress-text world-install-progress-text';
  progressText.textContent = 'Starting...';

  card.appendChild(progressBar);
  card.appendChild(progressText);
  card._worldInstallProgressFill = fill;
  card._worldInstallProgressTextEl = progressText;
  return { fill, text: progressText };
};

const updateWorldInlineInstallProgress = ({ card, button }, pct, text, buttonText = '') => {
  const progressEls = ensureWorldInstallProgressElements(card);
  if (progressEls) {
    progressEls.fill.style.width = `${clampWorldInstallPercent(pct)}%`;
    progressEls.text.textContent = text;
  }
  if (button && buttonText) button.textContent = buttonText;
};

const startWorldInlineInstallProgress = ({ installKey, button, card, activeLabel = 'Downloading', doneLabel = 'Downloaded', idleLabel = 'Download' }) => {
  if (!installKey) {
    return { complete: () => {}, fail: () => {}, close: () => {} };
  }

  let eventSource = null;
  let closed = false;
  const target = { card, button };
  updateWorldInlineInstallProgress(target, 0, 'Starting...', `${activeLabel}...`);

  const close = () => {
    if (closed) return;
    closed = true;
    if (eventSource) eventSource.close();
  };
  const complete = (message = doneLabel) => {
    updateWorldInlineInstallProgress(target, 100, message, doneLabel);
    close();
  };
  const fail = (message = 'Download failed') => {
    updateWorldInlineInstallProgress(target, 0, message, idleLabel);
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
      const pct = clampWorldInstallPercent(progress.overall_percent);
      if (status === 'installed') {
        complete(progress.message || doneLabel);
        return;
      }
      if (status === 'failed' || status === 'cancelled') {
        fail(progress.message || (status === 'cancelled' ? 'Download cancelled' : 'Download failed'));
        return;
      }

      const text = formatWorldInstallProgressText(progress, activeLabel);
      const stage = String(progress.stage || '').toLowerCase();
      const stageLabel = stage === 'extract' ? 'Extracting' : stage === 'finalize' ? 'Finalizing' : activeLabel;
      updateWorldInlineInstallProgress(target, pct, text, `${stageLabel} ${Math.round(pct)}%`);
    };
  } catch (_err) {
    updateWorldInlineInstallProgress(target, 0, 'Starting...', `${activeLabel}...`);
  }

  return { complete, fail, close };
};

const normalizeWorldStorageTarget = (value) => {
  const raw = String(value || 'default').trim();
  if (raw.toLowerCase().startsWith('version:')) {
    return `version:${raw.split(':', 2)[1] || ''}`;
  }
  const normalized = raw.toLowerCase();
  if (normalized === 'global' || normalized === 'custom' || normalized === 'default') {
    return normalized;
  }
  return 'default';
};

const formatWorldDateTime = (value) => {
  const ts = Number(value || 0);
  if (!Number.isFinite(ts) || ts <= 0) return 'Unknown';
  try {
    return new Date(ts).toLocaleString();
  } catch (err) {
    return 'Unknown';
  }
};

const normalizeWorldSearchText = (value) => {
  let text = String(value || '').toLowerCase();
  try {
    text = decodeURIComponent(text);
  } catch (_) {
    // Keep original text when it cannot be decoded.
  }
  return text
    .replace(/\+/g, ' ')
    .replace(/[%_\-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
};

const buildWorldCardSummary = (world) => {
  const explicit = String(world.description || world.summary || '').trim();
  if (explicit) return explicit;

  const parts = [];
  if (world.game_mode && world.game_mode !== 'Unknown') parts.push(world.game_mode);
  if (world.version_name) parts.push(world.version_name);
  const modifiedText = formatWorldDateTime(world.modified_at);
  if (modifiedText !== 'Unknown') parts.push(`Modified ${modifiedText}`);
  return parts.join(' | ');
};

const compareMinecraftVersionValues = (left, right) => (
  String(left || '').localeCompare(String(right || ''), undefined, { numeric: true, sensitivity: 'base' })
);

const compareMinecraftVersions = (a, b) => compareMinecraftVersionValues(
  String(b || ''),
  String(a || '')
);

const getWorldVersionOptions = () => {
  const versions = new Set();
  (worldsState.versionOptions || []).forEach((entry) => {
    const version = String((entry && (entry.version || entry.folder || entry.display)) || '').trim();
    if (version) versions.add(version);
  });
  (worldsState.installedWorlds || []).forEach((world) => {
    const version = String(world.version_name || world.minecraft_version || '').trim();
    if (version) versions.add(version);
  });
  return Array.from(versions).sort(compareMinecraftVersions);
};

const renderWorldVersionDropdown = () => {
  const select = getEl('worlds-version-select');
  if (!select) return;

  const previousValue = String(worldsState.gameVersion || select.value || '').trim();
  const versions = getWorldVersionOptions();

  select.innerHTML = '<option value="">All</option>';
  versions.forEach((version) => {
    const option = document.createElement('option');
    option.value = version;
    option.textContent = version;
    select.appendChild(option);
  });

  if (previousValue && versions.includes(previousValue)) {
    select.value = previousValue;
    worldsState.gameVersion = previousValue;
  } else {
    select.value = '';
    worldsState.gameVersion = '';
  }
};

const populateWorldVersionDropdown = async () => {
  try {
    const res = await api('/api/worlds/version-options', 'POST', {});
    worldsState.versionOptions = (res && res.ok && Array.isArray(res.versions))
      ? res.versions
      : [];
  } catch (err) {
    console.error('Failed to load world version options:', err);
    worldsState.versionOptions = [];
  }
  renderWorldVersionDropdown();
};

const matchesWorldVersionFilter = (world) => {
  const localSelected = String(worldsState.gameVersion || '').trim();
  if (!localSelected) return true;
  return [world.version_name, world.minecraft_version]
    .map((value) => String(value || '').trim())
    .filter(Boolean)
    .includes(localSelected);
};

const refreshWorldCategoryOptions = () => {
  const select = getEl('worlds-category-select');
  if (!select) return;

  const previousValue = String(worldsState.category || select.value || '').trim();
  const categories = new Set(
    (worldsState.categoryOptions || [])
      .map((category) => String(category || '').trim())
      .filter(Boolean)
  );
  if (previousValue) categories.add(previousValue);
  const sortedCategories = Array.from(categories).sort((a, b) => a.localeCompare(b));
  select.innerHTML = '<option value="">All</option>';
  sortedCategories.forEach((category) => {
    const option = document.createElement('option');
    option.value = category;
    option.textContent = category;
    select.appendChild(option);
  });

  if (previousValue && sortedCategories.includes(previousValue)) {
    select.value = previousValue;
    worldsState.category = previousValue;
  } else {
    select.value = '';
    worldsState.category = '';
  }
};

const applyWorldsClientFilters = () => {
  worldsState.availableWorlds = (worldsState.availableWorldsRaw || []).slice();
};

const sanitizeRemoteDetailHtml = (html) => {
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

const ensureScreenshotLightbox = () => {
  let lightbox = document.getElementById('screenshot-lightbox');
  if (lightbox) return lightbox;

  lightbox = document.createElement('div');
  lightbox.id = 'screenshot-lightbox';
  lightbox.className = 'screenshot-lightbox';
  const image = document.createElement('img');
  image.className = 'screenshot-lightbox-img';
  lightbox.appendChild(image);
  lightbox.addEventListener('click', () => {
    lightbox.classList.remove('active');
  });
  document.body.appendChild(lightbox);
  return lightbox;
};

const updateWorldsWarning = (message = '') => {
  const warn = getEl('worlds-section-warning');
  if (!warn) return;
  if (message) {
    warn.textContent = message;
    warn.classList.remove('hidden');
  } else {
    warn.textContent = '';
    warn.classList.add('hidden');
  }
};

const updateWorldsProviderDisplay = () => {
  const display = getEl('worlds-provider-display');
  if (display) display.textContent = 'CurseForge';

  const subtitle = getEl('worlds-available-subtitle');
  if (subtitle) {
    subtitle.innerHTML = 'Worlds from <span id="worlds-provider-display">CurseForge</span>';
  }
};

const syncWorldsCustomControls = () => {
  const item = getEl('worlds-custom-filter-item');
  const pathLabel = getEl('worlds-custom-path');
  if (item) item.classList.toggle('hidden', worldsState.storageTarget !== 'custom');
  if (pathLabel) pathLabel.textContent = worldsState.customPath || 'None';
};

const applyWorldsViewMode = () => {
  const mode = state.settingsState.worlds_view || 'list';
  const installed = getEl('installed-worlds-list');
  const available = getEl('available-worlds-list');
  if (installed) installed.classList.toggle('list-view', mode === 'list');
  if (available) available.classList.toggle('list-view', mode === 'list');

  const gridBtn = getEl('worlds-view-grid-btn');
  const listBtn = getEl('worlds-view-list-btn');
  if (gridBtn) gridBtn.classList.toggle('active', mode === 'grid');
  if (listBtn) listBtn.classList.toggle('active', mode === 'list');
};

const initWorldsViewToggle = () => {
  const gridBtn = getEl('worlds-view-grid-btn');
  const listBtn = getEl('worlds-view-list-btn');

  if (gridBtn) {
    gridBtn.addEventListener('click', () => {
      if (state.settingsState.worlds_view !== 'grid') {
        _autoSaveSetting('worlds_view', 'grid');
        applyWorldsViewMode();
      }
    });
  }

  if (listBtn) {
    listBtn.addEventListener('click', () => {
      if (state.settingsState.worlds_view !== 'list') {
        _autoSaveSetting('worlds_view', 'list');
        applyWorldsViewMode();
      }
    });
  }

  applyWorldsViewMode();
};

const populateWorldStorageOptions = async () => {
  const select = getEl('worlds-storage-select');
  if (!select) return;

  const previousValue = normalizeWorldStorageTarget(worldsState.storageTarget || select.value || 'default');
  select.innerHTML = '<option value="default">Default</option>';

  try {
    const res = await api('/api/worlds/storage-options', 'POST', {});
    if (!res || !res.ok) {
      worldsState.storageOptions = [];
      select.value = previousValue;
      return;
    }

    const options = Array.isArray(res.options) ? res.options : [];
    worldsState.storageOptions = options;
    select.innerHTML = '';
    options.forEach((optionData) => {
      const option = document.createElement('option');
      option.value = optionData.value || 'default';
      option.textContent = optionData.label || option.value || 'Default';
      select.appendChild(option);
    });

    if (Array.from(select.options).some((option) => option.value === previousValue)) {
      select.value = previousValue;
      worldsState.storageTarget = previousValue;
    } else {
      select.value = 'default';
      worldsState.storageTarget = 'default';
    }
  } catch (err) {
    console.error('Failed to load world storage options:', err);
    select.value = previousValue;
  }
};

export const loadInstalledWorlds = async () => {
  worldsState.installedLoading = true;
  renderInstalledWorlds();

  try {
    const res = await api('/api/worlds/installed', 'POST', {
      storage_target: worldsState.storageTarget,
      custom_path: worldsState.customPath,
    });

    worldsState.installedWorlds = (res && res.ok && Array.isArray(res.worlds)) ? res.worlds : [];
    worldsState.storageLabel = (res && res.storage_label) || 'Default';
    worldsState.storagePath = (res && res.storage_path) || '';
    worldsState.installedError = (!res || !res.ok)
      ? ((res && res.error) || 'Failed to load installed worlds.')
      : null;
  } catch (err) {
    console.error('Failed to load installed worlds:', err);
    worldsState.installedWorlds = [];
    worldsState.installedError = 'Failed to load installed worlds.';
  } finally {
    worldsState.installedLoading = false;
    renderWorldVersionDropdown();
    renderInstalledWorlds();
    updateWorldsWarning(worldsState.installedError || worldsState.lastError || '');
    return !worldsState.installedError;
  }
};

const searchWorlds = async () => {
  const requestId = ++worldsState.searchRequestId;
  try {
    worldsState.lastError = null;
    const loading = getEl('worlds-loading');
    const list = getEl('available-worlds-list');
    if (loading) loading.classList.remove('hidden');
    if (list) list.innerHTML = '';

    const res = await api('/api/worlds/search', 'POST', {
      provider: worldsState.provider,
      search_query: worldsState.searchQuery,
      game_version: worldsState.gameVersion,
      category: worldsState.category || '',
      sort_by: worldsState.sortBy || 'relevance',
      page_size: WORLDS_PAGE_SIZE,
      page_index: Math.max(0, worldsState.currentPage - 1),
    });

    if (requestId !== worldsState.searchRequestId) return true;

    if (res && res.ok) {
      worldsState.availableWorldsRaw = Array.isArray(res.worlds) ? res.worlds : [];
      worldsState.categoryOptions = Array.isArray(res.categories) ? res.categories : [];
      refreshWorldCategoryOptions();
      applyWorldsClientFilters();
      const totalCount = Number(res.total_count || worldsState.availableWorlds.length || 0);
      worldsState.totalPages = Math.max(1, Math.ceil(totalCount / WORLDS_PAGE_SIZE));
      worldsState.lastError = res.error || null;
    } else {
      worldsState.availableWorldsRaw = [];
      worldsState.availableWorlds = [];
      worldsState.totalPages = 1;
      worldsState.lastError = (res && res.error) || 'Failed to search worlds.';
    }

    if (loading) loading.classList.add('hidden');
    updateWorldsWarning(worldsState.installedError || worldsState.lastError || '');
    renderAvailableWorlds();
    renderWorldsPagination();
    return !worldsState.lastError;
  } catch (err) {
    if (requestId !== worldsState.searchRequestId) return true;
    console.error('Failed to search worlds:', err);
    worldsState.availableWorldsRaw = [];
    worldsState.availableWorlds = [];
    worldsState.totalPages = 1;
    worldsState.lastError = 'Failed to search worlds.';
    const loading = getEl('worlds-loading');
    if (loading) loading.classList.add('hidden');
    updateWorldsWarning(worldsState.installedError || worldsState.lastError || '');
    renderAvailableWorlds();
    renderWorldsPagination();
    return false;
  }
};

const renderWorldsPagination = () => {
  const container = getEl('worlds-pagination');
  if (!container) return;
  renderCommonPagination(container, worldsState.totalPages, worldsState.currentPage, (page) => {
    worldsState.currentPage = page;
    searchWorlds();
  });
};

const getWorldBulkKey = (world) => String((world && world.world_id) || '');

export const pruneWorldsBulkSelection = () => {
  if (!state.worldsBulkState.enabled) return;
  const installed = new Set((worldsState.installedWorlds || []).map((w) => getWorldBulkKey(w)).filter(Boolean));
  const next = new Set();
  state.worldsBulkState.selected.forEach((key) => {
    if (installed.has(key)) next.add(key);
  });
  state.worldsBulkState.selected = next;
};

export const updateWorldsBulkActionsUI = () => {
  const toggleBtn = getEl('worlds-bulk-toggle-btn');
  const deleteBtn = getEl('worlds-bulk-delete-btn');
  const count = state.worldsBulkState.selected.size;

  if (toggleBtn) {
    toggleBtn.textContent = state.worldsBulkState.enabled ? 'Cancel Bulk' : 'Bulk Select';
    toggleBtn.className = state.worldsBulkState.enabled ? 'primary' : 'mild';
  }
  if (deleteBtn) {
    deleteBtn.classList.toggle('hidden', !state.worldsBulkState.enabled);
    deleteBtn.textContent = `Delete Selected (${count})`;
    deleteBtn.disabled = count === 0;
  }
  refreshActionOverflowMenus();
};

const setWorldsBulkMode = (enabled) => {
  const shouldEnable = !!enabled;
  state.worldsBulkState.enabled = shouldEnable;
  if (!shouldEnable) state.worldsBulkState.selected = new Set();
  updateWorldsBulkActionsUI();
  renderInstalledWorlds();
};

const toggleWorldBulkSelection = (world) => {
  if (!state.worldsBulkState.enabled || !world) return;
  const key = getWorldBulkKey(world);
  if (!key) return;
  if (state.worldsBulkState.selected.has(key)) state.worldsBulkState.selected.delete(key);
  else state.worldsBulkState.selected.add(key);
  updateWorldsBulkActionsUI();
  renderInstalledWorlds();
};

const bulkDeleteSelectedWorlds = async ({ skipConfirm = false } = {}) => {
  const keys = Array.from(state.worldsBulkState.selected);
  if (!keys.length) {
    showMessageBox({
      title: 'Bulk Delete Worlds',
      message: 'No installed worlds selected.',
      buttons: [{ label: 'OK' }],
    });
    return;
  }

  const runDelete = async () => {
    let cancelRequested = false;
    let processed = 0;
    showLoadingOverlay(`Deleting selected worlds... (0/${keys.length})`, {
      buttons: [
        {
          label: 'Cancel',
          classList: ['danger'],
          closeOnClick: false,
          onClick: (_values, controls) => {
            if (cancelRequested) return;
            cancelRequested = true;
            controls.update({
              message: 'Cancelling bulk delete after the current world finishes...',
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
      try {
        const res = await api('/api/worlds/delete', 'POST', {
          storage_target: worldsState.storageTarget,
          custom_path: worldsState.customPath,
          world_id: key,
        });
        if (res && res.ok) {
          deleted += 1;
        } else {
          failures.push(`${key}: ${(res && res.error) || 'unknown error'}`);
        }
      } catch (err) {
        failures.push(`${key}: ${(err && err.message) || 'request failed'}`);
      }
      processed += 1;
      setLoadingOverlayText(`Deleting selected worlds... (${processed}/${keys.length})`);
    }

    hideLoadingOverlay();
    setWorldsBulkMode(false);
    await loadInstalledWorlds();

    if (cancelRequested) {
      showMessageBox({
        title: 'Bulk Delete Cancelled',
        message: `Deleted ${deleted} world${deleted !== 1 ? 's' : ''} before cancellation.${failures.length ? `<br><br>Failures: ${failures.length}` : ''}`,
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    if (!failures.length) {
      showMessageBox({
        title: 'Bulk Delete Complete',
        message: `Deleted ${deleted} world${deleted !== 1 ? 's' : ''}.`,
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    const preview = failures.slice(0, 8).join('<br>');
    const more = failures.length > 8 ? `<br>...and ${failures.length - 8} more.` : '';
    showMessageBox({
      title: 'Bulk Delete Finished With Errors',
      message: `Deleted ${deleted} world${deleted !== 1 ? 's' : ''}.<br><br>Failures:<br>${preview}${more}`,
      buttons: [{ label: 'OK' }],
    });
  };

  if (skipConfirm || state.isShiftDown) {
    await runDelete();
    return;
  }

  showMessageBox({
    title: 'Bulk Delete Worlds',
    message: `Delete ${keys.length} selected world${keys.length !== 1 ? 's' : ''}?<br><i>This cannot be undone!</i>`,
    buttons: [
      { label: 'Delete', classList: ['danger'], onClick: runDelete },
      { label: 'Cancel' },
    ],
  });
};

const renderInstalledWorlds = () => {
  const list = getEl('installed-worlds-list');
  if (!list) return;

  const subtitle = getEl('installed-worlds-subtitle');
  const query = normalizeWorldSearchText(worldsState.searchQuery || '');
  let filtered = worldsState.installedWorlds || [];
  filtered = filtered.filter(matchesWorldVersionFilter);
  if (query) {
    filtered = filtered.filter((world) => {
      const title = normalizeWorldSearchText(world.title || world.display_name || '');
      const worldId = normalizeWorldSearchText(world.world_id || '');
      return title.includes(query) || worldId.includes(query);
    });
  }

  const count = filtered.length;
  if (subtitle) {
    subtitle.textContent = worldsState.installedLoading
      ? `Loading worlds in ${worldsState.storageLabel || 'Default'}...`
      : `${count} world${count !== 1 ? 's' : ''} in ${worldsState.storageLabel || 'Default'}`;
  }

  pruneWorldsBulkSelection();

  list.innerHTML = '';
  if (worldsState.installedLoading) {
    list.appendChild(createInlineLoadingState('Loading worlds...', { centered: true }));
    applyWorldsViewMode();
    updateWorldsBulkActionsUI();
    return;
  }

  if (!filtered.length) {
    list.appendChild(createEmptyState('No worlds installed'));
    applyWorldsViewMode();
    updateWorldsBulkActionsUI();
    return;
  }

  filtered.forEach((world) => {
    list.appendChild(createWorldCard(world, true));
  });
  applyWorldsViewMode();
  updateWorldsBulkActionsUI();
};

const renderAvailableWorlds = () => {
  const list = getEl('available-worlds-list');
  if (!list) return;

  list.innerHTML = '';
  if (!worldsState.availableWorlds.length) {
    if (worldsState.lastError) {
      list.appendChild(createEmptyState(worldsState.lastError, { isError: true }));
    } else {
      list.appendChild(createEmptyState('No worlds found'));
    }
    applyWorldsViewMode();
    return;
  }

  worldsState.availableWorlds.forEach((world) => {
    list.appendChild(createWorldCard(world, false));
  });
  applyWorldsViewMode();
};

const openWorldFolder = async (world) => {
  try {
    const res = await api('/api/worlds/open', 'POST', {
      storage_target: worldsState.storageTarget,
      custom_path: worldsState.customPath,
      world_id: world.world_id,
    });
    if (!res || !res.ok) {
      showMessageBox({
        title: 'Open Folder Failed',
        message: (res && res.error) || 'Failed to open the world folder.',
        buttons: [{ label: 'OK' }],
      });
    }
  } catch (err) {
    console.error('Failed to open world folder:', err);
  }
};

const promptEditWorld = (world) => openWorldNbtEditor(world, 'simple');

const deleteWorld = (world, options = {}) => {
  const runDelete = async () => {
    try {
      const res = await api('/api/worlds/delete', 'POST', {
        storage_target: worldsState.storageTarget,
        custom_path: worldsState.customPath,
        world_id: world.world_id,
      });
      if (!res || !res.ok) {
        showMessageBox({
          title: 'Delete Failed',
          message: (res && res.error) || 'Failed to delete the world.',
          buttons: [{ label: 'OK' }],
        });
        return;
      }
      await loadInstalledWorlds();
    } catch (err) {
      console.error('Failed to delete world:', err);
    }
  };

  if (options.skipConfirm || state.isShiftDown) {
    runDelete();
    return;
  }

  showMessageBox({
    title: 'Delete World',
    message: `Delete <b>${world.title || world.world_id || 'this world'}</b>?<br><i>This cannot be undone!</i>`,
    buttons: [
      { label: 'Delete', classList: ['danger'], onClick: runDelete },
      { label: 'Cancel' },
    ],
  });
};

const exportWorld = async (world) => {
  const worldId = String(world && world.world_id || '').trim();
  if (!worldId) return;

  const progressBox = showMessageBox({
    title: 'Export World',
    message: `Building world archive for <b>${world.title || worldId}</b>...`,
    buttons: [],
  });

  let res = null;
  try {
    res = await api('/api/worlds/export', 'POST', {
      storage_target: worldsState.storageTarget,
      custom_path: worldsState.customPath,
      world_id: worldId,
    });
  } catch (err) {
    res = { ok: false, error: (err && err.message) || String(err) };
  }

  if (!res || !res.ok || !res.zip_b64) {
    progressBox.update({
      title: 'Export Failed',
      message: (res && res.error) || 'Failed to export the world.',
      buttons: [{ label: 'OK' }],
    });
    return;
  }

  let bytes;
  try {
    bytes = Uint8Array.from(atob(res.zip_b64), (c) => c.charCodeAt(0));
  } catch (err) {
    progressBox.update({
      title: 'Export Failed',
      message: 'Failed to decode exported world data.',
      buttons: [{ label: 'OK' }],
    });
    return;
  }

  const blob = new Blob([bytes], { type: 'application/zip' });
  const fileName = res.suggested_filename || `${worldId}.zip`;
  let savedLabel = '';

  if (window.showSaveFilePicker) {
    try {
      const fileHandle = await window.showSaveFilePicker({
        suggestedName: fileName,
        types: [{ description: 'World archive (.zip)', accept: { 'application/zip': ['.zip'] } }],
      });
      const writable = await fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();
      savedLabel = fileName;
    } catch (saveErr) {
      if (saveErr && saveErr.name === 'AbortError') {
        progressBox.update({
          title: 'Export Cancelled',
          message: 'You cancelled the export.',
          buttons: [{ label: 'OK' }],
        });
        return;
      }
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
      progressBox.update({
        title: 'Export Failed',
        message: `Failed to save the exported file.<br><br>${(downloadErr && downloadErr.message) || 'Unknown save error'}`,
        buttons: [{ label: 'OK' }],
      });
      return;
    }
  }

  const sizeMb = bytes.length > 0 ? (bytes.length / (1024 * 1024)).toFixed(2) : '0.00';
  progressBox.update({
    title: 'Export Successful',
    message: `World <b>${world.title || worldId}</b> was exported.<br><br>Saved to: <b>${savedLabel}</b><br>File size: <b>${sizeMb} MB</b>`,
    buttons: [{ label: 'OK' }],
  });
};

const _uploadWorldZip = async (file, endpoint, extraFields = {}) => {
  const form = new FormData();
  form.append('world_file', file, file.name || 'world.zip');
  form.append('storage_target', worldsState.storageTarget || 'default');
  form.append('custom_path', worldsState.customPath || '');
  Object.keys(extraFields).forEach((key) => {
    const value = extraFields[key];
    if (value === null || value === undefined) return;
    form.append(key, typeof value === 'string' ? value : JSON.stringify(value));
  });

  const response = await fetch(endpoint, { method: 'POST', body: form });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
};

const importWorldFlow = async () => {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.zip,application/zip';
  input.style.display = 'none';
  document.body.appendChild(input);

  const fileSelected = await new Promise((resolve) => {
    let resolved = false;
    input.addEventListener('change', () => {
      resolved = true;
      resolve(input.files && input.files[0] ? input.files[0] : null);
    });
    // If the user dismisses the picker, focus returns without a change event.
    window.addEventListener('focus', () => {
      setTimeout(() => {
        if (!resolved) resolve(null);
      }, 400);
    }, { once: true });
    input.click();
  });

  document.body.removeChild(input);

  if (!fileSelected) return;

  const progressBox = showMessageBox({
    title: 'Import World',
    message: `Scanning <b>${fileSelected.name}</b>...`,
    buttons: [],
  });

  let scanRes = null;
  try {
    scanRes = await _uploadWorldZip(fileSelected, '/api/worlds/import-scan');
  } catch (err) {
    progressBox.update({
      title: 'Import Failed',
      message: (err && err.message) || 'Failed to scan the world archive.',
      buttons: [{ label: 'OK' }],
    });
    return;
  }

  if (!scanRes || !scanRes.ok || !Array.isArray(scanRes.roots) || scanRes.roots.length === 0) {
    progressBox.update({
      title: 'Import Failed',
      message: (scanRes && scanRes.error) || 'No worlds were found in the archive.',
      buttons: [{ label: 'OK' }],
    });
    return;
  }

  const roots = scanRes.roots;

  const performImport = async (selectedRoots) => {
    progressBox.update({
      title: 'Import World',
      message: `Importing ${selectedRoots ? selectedRoots.length : roots.length} world(s)...`,
      buttons: [],
    });

    let importRes = null;
    try {
      const extra = {};
      if (selectedRoots && selectedRoots.length) {
        extra.selected_roots = JSON.stringify(selectedRoots);
      }
      importRes = await _uploadWorldZip(fileSelected, '/api/worlds/import', extra);
    } catch (err) {
      progressBox.update({
        title: 'Import Failed',
        message: (err && err.message) || 'Failed to import the world archive.',
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    if (!importRes || !importRes.ok) {
      progressBox.update({
        title: 'Import Failed',
        message: (importRes && importRes.error) || 'Failed to import the world archive.',
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    await loadInstalledWorlds();

    const importedCount = Array.isArray(importRes.imported) ? importRes.imported.length : 0;
    const skippedCount = Array.isArray(importRes.skipped) ? importRes.skipped.length : 0;
    const errorCount = Array.isArray(importRes.errors) ? importRes.errors.length : 0;
    const lines = [
      `Imported: <b>${importedCount}</b>`,
      skippedCount > 0 ? `Skipped: <b>${skippedCount}</b>` : null,
      errorCount > 0 ? `Errors: <b>${errorCount}</b>` : null,
    ].filter(Boolean).join('<br>');

    progressBox.update({
      title: 'Import Complete',
      message: lines || importRes.message || 'World import finished.',
      buttons: [{ label: 'OK' }],
    });
  };

  if (roots.length === 1) {
    performImport(null);
    return;
  }

  const content = document.createElement('div');
  content.style.cssText = 'display:flex;flex-direction:column;gap:8px;';

  const intro = document.createElement('p');
  intro.style.cssText = 'margin:0 0 4px 0;font-size:12px;color:#cbd5e1;';
  intro.innerHTML = `The archive contains <b>${roots.length}</b> worlds. Choose which ones to import.`;
  content.appendChild(intro);

  const selectAllRow = document.createElement('label');
  selectAllRow.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:12px;color:#e5e7eb;border-bottom:1px solid #1f2937;padding-bottom:4px;';
  const selectAllCb = document.createElement('input');
  selectAllCb.type = 'checkbox';
  selectAllCb.checked = true;
  const selectAllText = document.createElement('span');
  selectAllText.textContent = 'Select all';
  selectAllRow.appendChild(selectAllCb);
  selectAllRow.appendChild(selectAllText);
  content.appendChild(selectAllRow);

  const list = document.createElement('div');
  list.style.cssText = 'max-height:280px;overflow-y:auto;border:1px solid #1f2937;padding:6px;display:flex;flex-direction:column;gap:4px;';

  const rowEntries = roots.map((entry) => {
    const row = document.createElement('label');
    row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:3px 0;font-size:12px;color:#e5e7eb;';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    const labelText = document.createElement('span');
    labelText.style.cssText = 'flex:1;';
    const sizeKb = entry.level_dat_size > 0 ? `${(entry.level_dat_size / 1024).toFixed(1)} KB` : '';
    labelText.innerHTML = `<b>${entry.label || entry.path}</b>` + (entry.path && entry.path !== entry.label
      ? ` <span style="color:#9ca3af;">(${entry.path})</span>`
      : '') + (sizeKb ? ` <span style="color:#6b7280;">level.dat: ${sizeKb}</span>` : '');
    row.appendChild(cb);
    row.appendChild(labelText);
    list.appendChild(row);
    return { entry, checkbox: cb };
  });

  selectAllCb.addEventListener('change', () => {
    rowEntries.forEach((e) => { e.checkbox.checked = selectAllCb.checked; });
  });
  rowEntries.forEach((e) => {
    e.checkbox.addEventListener('change', () => {
      selectAllCb.checked = rowEntries.every((entry) => entry.checkbox.checked);
    });
  });

  content.appendChild(list);

  progressBox.update({
    title: 'Import World',
    customContent: content,
    buttons: [
      {
        label: 'Import',
        classList: ['primary'],
        closeOnClick: false,
        onClick: () => {
          const selected = rowEntries.filter((e) => e.checkbox.checked).map((e) => e.entry.path);
          if (selected.length === 0) return;
          performImport(selected);
        },
      },
      { label: 'Cancel' },
    ],
  });
};

const installWorld = async (world, version, installBtn) => {
  let progress = null;
  try {
    const idleLabel = installBtn ? (installBtn.textContent || 'Download') : 'Download';
    const installKey = `worlds/${createOperationId('install')}`;
    if (installBtn) {
      installBtn.disabled = true;
      installBtn.textContent = 'Downloading...';
    }
    progress = startWorldInlineInstallProgress({
      installKey,
      button: installBtn,
      card: installBtn ? installBtn.closest('.world-card') : null,
      activeLabel: 'Downloading',
      doneLabel: 'Downloaded',
      idleLabel,
    });

    const res = await api('/api/worlds/install', 'POST', {
      install_key: installKey,
      provider: world.provider || worldsState.provider,
      project_id: world.project_id,
      world_slug: world.world_slug,
      world_name: world.name || world.title || world.world_id || '',
      download_url: version.download_url,
      file_name: version.file_name,
      storage_target: worldsState.storageTarget,
      custom_path: worldsState.customPath,
    });

    if (!res || !res.ok) {
      if (progress) progress.fail((res && res.error) || 'Failed to download the world.');
      if (installBtn) {
        installBtn.disabled = false;
        installBtn.textContent = idleLabel;
      }
      showMessageBox({
        title: 'Download Failed',
        message: (res && res.error) || 'Failed to download the world.',
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    if (progress) progress.complete(res.message || 'Downloaded');

    if (installBtn) {
      installBtn.disabled = false;
      installBtn.textContent = 'Downloaded';
      installBtn.className = '';
      installBtn.style.color = '#4ade80';
      installBtn.style.fontWeight = 'bold';
      installBtn.style.border = 'none';
      installBtn.style.background = 'transparent';
      installBtn.style.cursor = 'default';
    }

    await loadInstalledWorlds();
  } catch (err) {
    console.error('Failed to install world:', err);
    if (progress) progress.fail('Unexpected download error');
    if (installBtn) {
      installBtn.disabled = false;
      installBtn.textContent = 'Download';
    }
    showMessageBox({
      title: 'Download Failed',
      message: 'An unexpected error occurred while downloading the world.',
      buttons: [{ label: 'OK' }],
    });
  }
};

const createWorldCard = (world, isInstalled) => {
  const card = document.createElement('div');
  card.className = 'version-card mod-card world-card mod-entry-card';
  card.classList.add('unselectable', isInstalled ? 'section-installed' : 'section-available');

  const worldBulkKey = isInstalled ? getWorldBulkKey(world) : '';
  const isWorldBulkSelected = isInstalled && state.worldsBulkState.enabled && worldBulkKey
    && state.worldsBulkState.selected.has(worldBulkKey);

  if (isInstalled && state.worldsBulkState.enabled) {
    card.classList.add('bulk-select-active');
    if (isWorldBulkSelected) card.classList.add('bulk-selected');
  }

  const icon = document.createElement('img');
  icon.className = 'version-image mod-image mod-card-image';
  icon.src = world.icon_url || 'assets/images/placeholder_pack.png';
  imageAttachErrorPlaceholder(icon, 'assets/images/placeholder_pack.png');

  const info = document.createElement('div');
  info.className = 'version-info mod-card-info';

  const headerRow = document.createElement('div');
  headerRow.className = 'version-header-row';

  const name = document.createElement('div');
  name.className = 'version-display';
  name.textContent = world.title || world.display_name || world.name || world.world_id || 'Unknown World';

  const desc = document.createElement('div');
  desc.className = 'version-folder mod-card-description';
  desc.textContent = buildWorldCardSummary(world);

  headerRow.appendChild(name);
  info.appendChild(headerRow);
  info.appendChild(desc);

  const badgeRow = document.createElement('div');
  badgeRow.className = 'version-badge-row';

  if (isInstalled) {
    const installedBadge = document.createElement('span');
    installedBadge.className = 'version-badge installed';
    installedBadge.textContent = 'INSTALLED';
    badgeRow.appendChild(installedBadge);

    if (world.game_mode && world.game_mode !== 'Unknown') {
      const modeBadge = document.createElement('span');
      modeBadge.className = 'version-badge lite';
      modeBadge.textContent = String(world.game_mode).toUpperCase();
      badgeRow.appendChild(modeBadge);
    }

    if (world.version_name) {
      const versionBadge = document.createElement('span');
      versionBadge.className = 'version-badge size';
      versionBadge.textContent = String(world.version_name).toUpperCase();
      badgeRow.appendChild(versionBadge);
    }
  } else {
    const providerBadge = document.createElement('span');
    providerBadge.className = 'version-badge nonofficial';
    providerBadge.textContent = 'CURSEFORGE';
    badgeRow.appendChild(providerBadge);
  }

  const deleteIconContainer = document.createElement('div');
  deleteIconContainer.className = 'mod-card-delete-icon';
  if (isInstalled) {
    const exportBtn = document.createElement('div');
    exportBtn.className = 'icon-button';
    bindKeyboardActivation(exportBtn, {
      ariaLabel: `Export world ${String(name.textContent || '').trim() || 'this world'}`,
    });
    const exportImg = document.createElement('img');
    exportImg.alt = 'export';
    exportImg.src = 'assets/images/export_version.png';
    imageAttachErrorPlaceholder(exportImg, 'assets/images/placeholder.png');
    exportBtn.appendChild(exportImg);
    exportBtn.title = 'Export world to .zip archive';
    exportBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.worldsBulkState.enabled) {
        toggleWorldBulkSelection(world);
        return;
      }
      exportWorld(world);
    });
    deleteIconContainer.appendChild(exportBtn);

    const delBtn = document.createElement('div');
    delBtn.className = 'icon-button';
    bindKeyboardActivation(delBtn, {
      ariaLabel: `Delete world ${String(name.textContent || '').trim() || 'this world'}`,
    });
    const delImg = document.createElement('img');
    delImg.alt = 'delete';
    delImg.src = 'assets/images/unfilled_delete.png';
    imageAttachErrorPlaceholder(delImg, 'assets/images/placeholder.png');
    delBtn.appendChild(delImg);
    delBtn.addEventListener('mouseenter', () => { delImg.src = 'assets/images/filled_delete.png'; });
    delBtn.addEventListener('mouseleave', () => { delImg.src = 'assets/images/unfilled_delete.png'; });
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.worldsBulkState.enabled) {
        toggleWorldBulkSelection(world);
        return;
      }
      deleteWorld(world, { skipConfirm: isShiftDelete(e) });
    });
    deleteIconContainer.appendChild(delBtn);
  }

  const actions = document.createElement('div');
  actions.className = 'version-actions';

  if (isInstalled) {
    const editBtn = document.createElement('button');
    editBtn.className = 'primary';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      promptEditWorld(world);
    });
    actions.appendChild(editBtn);

    const openBtn = document.createElement('button');
    openBtn.className = 'important';
    openBtn.textContent = 'Open Folder';
    openBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openWorldFolder(world);
    });
    actions.appendChild(openBtn);
  } else {
    const quickWrap = document.createElement('div');
    quickWrap.className = 'quick-install-wrap';

    const quickBtn = document.createElement('button');
    quickBtn.className = 'primary';
    quickBtn.textContent = 'Download';

    const quickVersion = document.createElement('div');
    quickVersion.className = 'quick-install-version';
    quickVersion.textContent = 'Latest';

    quickBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      quickBtn.disabled = true;
      quickBtn.textContent = 'Fetching...';
      try {
        const versionsRes = await api('/api/worlds/versions', 'POST', {
          provider: world.provider || worldsState.provider,
          project_id: world.project_id,
          game_version: worldsState.gameVersion || '',
        });
        if (!versionsRes || !versionsRes.ok) {
          quickBtn.disabled = false;
          quickBtn.textContent = 'Download';
          quickVersion.textContent = 'Lookup failed';
          showMessageBox({
            title: 'Version Lookup Failed',
            message: (versionsRes && versionsRes.error) || 'Failed to fetch world versions.',
            buttons: [{ label: 'OK' }],
          });
          return;
        }
        const versions = Array.isArray(versionsRes.versions) ? versionsRes.versions : [];
        if (!versions.length) {
          quickBtn.disabled = false;
          quickBtn.textContent = 'Download';
          quickVersion.textContent = 'No versions found';
          return;
        }
        let recommendedIdx = versions.findIndex((ver) => String(ver.version_type || '').toLowerCase() === 'release');
        if (recommendedIdx === -1) recommendedIdx = versions.findIndex((ver) => String(ver.version_type || '').toLowerCase() === 'beta');
        if (recommendedIdx === -1) recommendedIdx = 0;
        const version = versions[recommendedIdx];
        quickVersion.textContent = version.version_number || version.display_name || 'Latest';
        quickBtn.textContent = 'Download';
        installWorld(world, version, quickBtn);
      } catch (err) {
        console.error('Failed quick world version lookup:', err);
        quickBtn.disabled = false;
        quickBtn.textContent = 'Download';
      }
    });

    quickWrap.addEventListener('click', (e) => e.stopPropagation());
    quickWrap.appendChild(quickBtn);
    quickWrap.appendChild(quickVersion);
    actions.appendChild(quickWrap);
  }

  card.appendChild(icon);
  card.appendChild(info);
  if (isInstalled) card.appendChild(deleteIconContainer);
  card.appendChild(badgeRow);
  card.appendChild(actions);

  if (isInstalled && state.worldsBulkState.enabled) {
    const checkbox = document.createElement('div');
    checkbox.className = 'bulk-select-checkbox';
    checkbox.textContent = isWorldBulkSelected ? '✔' : '';
    card.appendChild(checkbox);
  }

  card.style.cursor = 'pointer';
  bindKeyboardActivation(card, {
    ariaLabel: `View details for world ${String(name.textContent || '').trim() || 'this world'}`,
  });
  card.addEventListener('click', (e) => {
    if (e.target.closest('button, select, input, .icon-button')) return;
    if (isInstalled && state.worldsBulkState.enabled) {
      toggleWorldBulkSelection(world);
      return;
    }
    if (isInstalled) {
      showInstalledWorldDetailModal(world);
    } else {
      showAvailableWorldDetailModal(world);
    }
  });
  wireCardActionArrowNavigation(card);

  return card;
};

const renderInstalledWorldDetailContent = (detail) => {
  const content = document.createElement('div');
  content.className = 'mod-detail-content';

  const hero = document.createElement('div');
  hero.className = 'world-detail-hero';

  const image = document.createElement('img');
  image.className = 'world-detail-image';
  image.src = detail.icon_url || 'assets/images/placeholder_pack.png';
  image.onerror = () => { image.src = 'assets/images/placeholder_pack.png'; };

  const meta = document.createElement('div');
  meta.className = 'world-detail-meta';

  const title = document.createElement('h4');
  title.textContent = detail.title || detail.world_id || 'Unknown World';
  meta.appendChild(title);

  const addRow = (...parts) => {
    const row = document.createElement('div');
    row.className = 'world-detail-meta-row';
    parts.filter(Boolean).forEach((text) => {
      const span = document.createElement('span');
      span.textContent = text;
      row.appendChild(span);
    });
    if (row.childNodes.length) meta.appendChild(row);
  };

  addRow(`World ID: ${detail.world_id || 'Unknown'}`, `Storage: ${detail.storage_label || worldsState.storageLabel || 'Default'}`);
  addRow(`Modified: ${formatWorldDateTime(detail.modified_at)}`, `Last Played: ${formatWorldDateTime(detail.last_played)}`);
  addRow(`Size: ${formatBytes(detail.size_bytes) || 'Unknown'}`, `Game Mode: ${detail.game_mode || 'Unknown'}`, `Difficulty: ${detail.difficulty || 'Unknown'}`);
  addRow(`Version: ${detail.version_name || 'Unknown'}`, `Cheats: ${detail.allow_commands ? 'Enabled' : 'Disabled'}`, `Hardcore: ${detail.hardcore ? 'Yes' : 'No'}`);

  if (detail.path) {
    const note = document.createElement('div');
    note.className = 'world-detail-note';
    note.textContent = detail.path;
    meta.appendChild(note);
  }

  hero.appendChild(image);
  hero.appendChild(meta);
  content.appendChild(hero);
  return content;
};

const createWorldEditorLoadingContent = (message) => {
  return createInlineLoadingState(message);
};

const setWorldEditorStatus = (statusEl, message = '', tone = '') => {
  if (!statusEl) return;
  statusEl.className = 'world-nbt-status';
  if (tone) statusEl.classList.add(`world-nbt-status-${tone}`);
  statusEl.textContent = message;
  statusEl.classList.toggle('hidden', !message);
};

const createWorldEditorSection = (titleText, descriptionText = '') => {
  const section = document.createElement('section');
  section.className = 'world-nbt-section';

  const title = document.createElement('h4');
  title.innerHTML = titleText;
  section.appendChild(title);

  if (descriptionText) {
    const description = document.createElement('p');
    description.className = 'world-nbt-section-note';
    description.innerHTML = descriptionText;
    section.appendChild(description);
  }

  const body = document.createElement('div');
  body.className = 'world-nbt-section-body';
  section.appendChild(body);

  return { section, body };
};

const createWorldEditorInfoBubble = (tooltipText = '') => {
  const text = String(tooltipText || '').trim();
  if (!text) return null;

  const bubble = document.createElement('img');
  bubble.className = 'info-bubble';
  bubble.src = 'assets/images/info.png';
  bubble.alt = 'i';
  bubble.setAttribute('data-tooltip', text);
  return bubble;
};

const createWorldEditorLabelRow = (labelText, tooltipText = '') => {
  const row = document.createElement('span');
  row.className = 'world-nbt-label-row';

  const label = document.createElement('span');
  label.className = 'world-nbt-label';
  label.textContent = labelText;
  row.appendChild(label);

  const bubble = createWorldEditorInfoBubble(tooltipText);
  if (bubble) row.appendChild(bubble);

  return row;
};

const createWorldEditorField = (labelText, inputEl, options = {}) => {
  const normalizedOptions = typeof options === 'string'
    ? { hintText: options }
    : (options || {});
  const { hintText = '', tooltipText = '' } = normalizedOptions;

  const field = document.createElement('label');
  field.className = 'world-nbt-field';

  field.appendChild(createWorldEditorLabelRow(labelText, tooltipText));

  const control = document.createElement('div');
  control.className = 'world-nbt-control';
  control.appendChild(inputEl);
  field.appendChild(control);

  if (hintText) {
    const hint = document.createElement('span');
    hint.className = 'world-nbt-hint';
    hint.textContent = hintText;
    field.appendChild(hint);
  }

  return field;
};

const createWorldEditorCheckboxField = (labelText, inputEl, options = {}) => {
  const normalizedOptions = typeof options === 'string'
    ? { hintText: options }
    : (options || {});
  const { hintText = '', tooltipText = '', accessoryEl = null } = normalizedOptions;

  const field = document.createElement('label');
  field.className = 'world-nbt-field world-nbt-checkbox-field';

  const row = document.createElement('div');
  row.className = 'world-nbt-checkbox-row';
  row.appendChild(inputEl);
  row.appendChild(createWorldEditorLabelRow(labelText, tooltipText));
  if (accessoryEl) {
    accessoryEl.classList.add('world-nbt-checkbox-accessory');
    row.appendChild(accessoryEl);
  }

  field.appendChild(row);

  if (hintText) {
    const hint = document.createElement('span');
    hint.className = 'world-nbt-hint';
    hint.textContent = hintText;
    field.appendChild(hint);
  }

  return field;
};

const createWorldEditorTextInput = (value = '') => {
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'world-nbt-input';
  input.value = value ?? '';
  return input;
};

const createWorldEditorNumberInput = (value, { step = '1', min = '', max = '' } = {}) => {
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'world-nbt-input';
  input.value = value ?? '';
  input.step = step;
  if (min !== '') input.min = String(min);
  if (max !== '') input.max = String(max);
  return input;
};

const createWorldEditorWeatherDurationAccessory = (inputEl, tooltipText = '') => {
  const accessory = document.createElement('div');
  accessory.className = 'world-nbt-weather-duration';

  const durationLabel = createWorldEditorLabelRow('Lasts', tooltipText);
  durationLabel.classList.add('world-nbt-weather-duration-label');

  inputEl.classList.add('world-nbt-weather-duration-input');

  const unit = document.createElement('span');
  unit.className = 'world-nbt-inline-unit';
  unit.textContent = 'seconds';

  accessory.appendChild(durationLabel);
  accessory.appendChild(inputEl);
  accessory.appendChild(unit);

  return accessory;
};

const createWorldEditorSelect = (options, selectedValue) => {
  const select = document.createElement('select');
  select.className = 'world-nbt-input';
  options.forEach((optionData) => {
    const option = document.createElement('option');
    option.value = String(optionData.value);
    option.textContent = optionData.label;
    select.appendChild(option);
  });
  select.value = String(selectedValue ?? '');
  return select;
};

const WORLD_SIMPLE_TOOLTIPS = {
  gameMode: 'Changes how the world plays for the current player.\n\nSurvival: Normal gameplay.\nCreative: Unlimited blocks and flying.\nAdventure: Restricted map play.\nSpectator: Free-fly camera mode.',
  difficulty: 'Changes how harsh the world feels.\n\nHigher difficulty means tougher enemies and faster hunger loss.',
  allowCommands: 'Turns commands on or off for this world.\n\nUseful if you want things like teleporting, giving items, or using other cheats.',
  hardcore: 'Marks the world as Hardcore.\n\nHardcore worlds are much less forgiving and are meant for a one-life style challenge.',
  spawnX: 'The default X coordinate where players respawn in this world.',
  spawnY: 'The default Y height where players respawn in this world.',
  spawnZ: 'The default Z coordinate where players respawn in this world.',
  timeOfDay: 'Controls where the sun or moon is right now.\n\nCommon values:\n0: Sunrise\n6000: Midday\n12000: Sunset\n18000: Midnight',
  raining: 'Turns rain on or off.',
  thundering: 'Turns thunderstorms on or off.',
  rainDuration: 'How long rain should stay active before Minecraft can clear it again.',
  thunderDuration: 'How long the thunderstorm should stay active before Minecraft can calm it down.',
  health: 'The player\'s current health.\n\n20 is full health for a normal player.',
  foodLevel: 'The player\'s current hunger bar.\n\n20 is full hunger.',
  foodSaturation: 'How long the hunger bar stays full before it starts dropping.',
  xpLevel: 'The green experience level number shown above the hotbar.',
  xpTotal: 'The player\'s total saved experience points.',
  playerX: 'The player\'s saved X coordinate.\n\nThis decides where they will stand when the world loads.',
  playerY: 'The player\'s saved Y height.\n\nThis decides how high or low they will be when the world loads.',
  playerZ: 'The player\'s saved Z coordinate.\n\nThis decides where they will stand when the world loads.',
  inventorySlot: 'The slot number used for this item.\n\nUse the picker button if you want a visual hotbar, inventory, armor, and offhand layout instead of remembering slot numbers.',
  inventoryItem: 'The item id to place in this slot.\n\nExample: minecraft:stone',
  inventoryCount: 'How many items should be in this slot.',
  enderSlot: 'The ender chest slot number.\n\nUse the picker button if you want a visual 9x3 ender chest layout.',
  enderItem: 'The item id to place in this ender chest slot.\n\nExample: minecraft:diamond_block',
  enderCount: 'How many items should be in this ender chest slot.',
  hotbarSlot: 'Which hotbar slot is selected when the player loads in.\n\nThis is shown as 1 through 9 to match what players normally see in game.',
};

const WORLD_NBT_TAGS = {
  END: 0,
  BYTE: 1,
  SHORT: 2,
  INT: 3,
  LONG: 4,
  FLOAT: 5,
  DOUBLE: 6,
  BYTE_ARRAY: 7,
  STRING: 8,
  LIST: 9,
  COMPOUND: 10,
  INT_ARRAY: 11,
  LONG_ARRAY: 12,
};

const WORLD_NBT_NUMERIC_TAGS = new Set([
  WORLD_NBT_TAGS.BYTE,
  WORLD_NBT_TAGS.SHORT,
  WORLD_NBT_TAGS.INT,
  WORLD_NBT_TAGS.LONG,
  WORLD_NBT_TAGS.FLOAT,
  WORLD_NBT_TAGS.DOUBLE,
]);

const isWorldEditorObject = (value) => !!value && typeof value === 'object' && !Array.isArray(value);

const worldEditorIntValue = (value, fallback = null) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
};

const worldEditorFloatValue = (value, fallback = null) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const worldEditorBoolValue = (value) => {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').trim().toLowerCase());
};

const getWorldEditorRootValue = (root) => {
  if (!isWorldEditorObject(root)) return {};
  if (!isWorldEditorObject(root.value)) root.value = {};
  return root.value;
};

const getWorldEditorTag = (compound, key) => {
  if (!isWorldEditorObject(compound)) return null;
  const tag = compound[key];
  return isWorldEditorObject(tag) ? tag : null;
};

const getWorldEditorTagType = (tag, fallback = WORLD_NBT_TAGS.END) => {
  const parsed = worldEditorIntValue(tag && tag.type, fallback);
  return parsed === null ? fallback : parsed;
};

const getWorldEditorTagValue = (compound, key, fallback = null) => {
  const tag = getWorldEditorTag(compound, key);
  return tag && Object.prototype.hasOwnProperty.call(tag, 'value') ? tag.value : fallback;
};

const getWorldEditorCompoundValue = (compound, key) => {
  const tag = getWorldEditorTag(compound, key);
  if (!tag || getWorldEditorTagType(tag) !== WORLD_NBT_TAGS.COMPOUND || !isWorldEditorObject(tag.value)) {
    return null;
  }
  return tag.value;
};

const ensureWorldEditorCompoundValue = (compound, key) => {
  const existing = getWorldEditorCompoundValue(compound, key);
  if (existing) return existing;
  const child = { type: WORLD_NBT_TAGS.COMPOUND, value: {} };
  compound[key] = child;
  return child.value;
};

const getWorldEditorListPayload = (compound, key) => {
  const tag = getWorldEditorTag(compound, key);
  if (!tag || getWorldEditorTagType(tag) !== WORLD_NBT_TAGS.LIST || !isWorldEditorObject(tag.value)) {
    return null;
  }
  return tag.value;
};

const coerceWorldEditorValueForType = (tagType, value) => {
  if (WORLD_NBT_NUMERIC_TAGS.has(tagType)) {
    return tagType === WORLD_NBT_TAGS.FLOAT || tagType === WORLD_NBT_TAGS.DOUBLE
      ? (worldEditorFloatValue(value, 0) ?? 0)
      : (worldEditorIntValue(value, 0) ?? 0);
  }
  if (tagType === WORLD_NBT_TAGS.STRING) return String(value || '');
  return value;
};

const setWorldEditorCompoundTag = (compound, key, tagType, value) => {
  if (!isWorldEditorObject(compound)) return;
  const existing = getWorldEditorTag(compound, key);
  const existingType = getWorldEditorTagType(existing, tagType);
  let effectiveType = tagType;

  if (WORLD_NBT_NUMERIC_TAGS.has(tagType) && WORLD_NBT_NUMERIC_TAGS.has(existingType)) {
    effectiveType = existingType;
  } else if (tagType === WORLD_NBT_TAGS.STRING && existingType === WORLD_NBT_TAGS.STRING) {
    effectiveType = WORLD_NBT_TAGS.STRING;
  }

  compound[key] = {
    type: effectiveType,
    value: coerceWorldEditorValueForType(effectiveType, value),
  };
};

const getWorldEditorItemList = (playerValue, listKey) => {
  const listValue = getWorldEditorListPayload(playerValue, listKey);
  if (!isWorldEditorObject(listValue)) return [];

  const listType = getWorldEditorTagType({ type: listValue.list_type }, WORLD_NBT_TAGS.END);
  if (![WORLD_NBT_TAGS.COMPOUND, WORLD_NBT_TAGS.END].includes(listType)) return [];

  const items = [];
  const entries = Array.isArray(listValue.items) ? listValue.items : [];
  entries.forEach((entry) => {
    if (!isWorldEditorObject(entry)) return;
    const slot = worldEditorIntValue(getWorldEditorTagValue(entry, 'Slot', null), null);
    if (slot === null) return;
    const itemId = String(getWorldEditorTagValue(entry, 'id', '') || '').trim();
    const count = worldEditorIntValue(
      getWorldEditorTagValue(entry, 'Count', getWorldEditorTagValue(entry, 'count', null)),
      null
    );
    items.push({
      slot,
      item_id: itemId,
      count: Math.max(1, Math.min(127, count || 1)),
      has_extra_data: Object.keys(entry).some((key) => !['Slot', 'id', 'Count', 'count'].includes(key)),
    });
  });

  items.sort((left, right) => {
    if ((left.slot ?? 0) !== (right.slot ?? 0)) return (left.slot ?? 0) - (right.slot ?? 0);
    return String(left.item_id || '').localeCompare(String(right.item_id || ''));
  });
  return items;
};

const getWorldEditorPosition = (playerValue, key = 'Pos') => {
  const listValue = getWorldEditorListPayload(playerValue, key);
  if (!isWorldEditorObject(listValue)) return [null, null, null];

  const listType = getWorldEditorTagType({ type: listValue.list_type }, WORLD_NBT_TAGS.END);
  if (![WORLD_NBT_TAGS.DOUBLE, WORLD_NBT_TAGS.FLOAT, WORLD_NBT_TAGS.LONG, WORLD_NBT_TAGS.INT].includes(listType)) {
    return [null, null, null];
  }

  const items = Array.isArray(listValue.items) ? listValue.items : [];
  return [0, 1, 2].map((index) => worldEditorFloatValue(items[index], null));
};

const WORLD_SIMPLE_WEATHER_DURATION = 6000;
const WORLD_TICKS_PER_SECOND = 20;

const normalizeWorldEditorMinecraftVersion = (value = '') => {
  const match = String(value || '').trim().match(/\d+(?:\.\d+)+/);
  return match ? match[0] : '';
};

const getWorldEditorVersionInfo = (dataValue) => {
  const versionValue = getWorldEditorCompoundValue(dataValue, 'Version');
  return {
    version_name: String(getWorldEditorTagValue(versionValue, 'Name', '') || '').trim(),
    data_version: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'DataVersion', null), null),
  };
};

const worldEditorSupportsMinecraftVersion = (versionInfo, minimumVersion) => {
  const normalizedVersion = normalizeWorldEditorMinecraftVersion(versionInfo && versionInfo.version_name);
  if (!normalizedVersion) return false;
  return compareMinecraftVersionValues(normalizedVersion, minimumVersion) >= 0;
};

const worldEditorUsesModernItemFormat = (versionInfo, itemLists = []) => {
  if (worldEditorSupportsMinecraftVersion(versionInfo, '1.20.5')) return true;
  return itemLists.some((listValue) => {
    const listPayload = isWorldEditorObject(listValue) ? listValue : null;
    const entries = Array.isArray(listPayload && listPayload.items) ? listPayload.items : [];
    return entries.some((entry) => isWorldEditorObject(entry) && !!getWorldEditorTag(entry, 'count'));
  });
};

const getWorldEditorWeatherDuration = (...values) => {
  for (const value of values) {
    const parsed = worldEditorIntValue(value, null);
    if (parsed !== null && parsed > 1) return parsed;
  }
  return WORLD_SIMPLE_WEATHER_DURATION;
};

const getWorldEditorWeatherDurationSeconds = (...values) => Math.max(
  1,
  Math.ceil(getWorldEditorWeatherDuration(...values) / WORLD_TICKS_PER_SECOND)
);

const formatWorldGameRuleLabel = (name = '') => String(name || '')
  .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  .replace(/[_-]+/g, ' ')
  .replace(/\s+/g, ' ')
  .replace(/^minecraft:/, '')
  .trim()
  .replace(/\b\w/g, (char) => char.toUpperCase());

const createWorldGameRuleTooltipText = (rule) => {
  const valueType = String(rule && rule.value_type || 'text');
  const typeLabel = valueType === 'boolean'
    ? 'On/Off rule'
    : valueType === 'integer'
      ? 'Number rule'
      : 'Text rule';
  return `${typeLabel}\n\nMinecraft gamerule: ${String(rule && rule.name || '')}`;
};

const extractWorldGameRules = (dataValue) => {
  const gameRulesValue = getWorldEditorCompoundValue(dataValue, 'GameRules');
  if (!gameRulesValue) return [];

  return Object.keys(gameRulesValue)
    .sort((left, right) => left.localeCompare(right))
    .map((name) => {
      const tag = getWorldEditorTag(gameRulesValue, name);
      const storageTagType = getWorldEditorTagType(tag, WORLD_NBT_TAGS.STRING);
      const rawValue = tag && Object.prototype.hasOwnProperty.call(tag, 'value') ? tag.value : '';

      let valueType = 'text';
      let value = String(rawValue ?? '');

      if (storageTagType === WORLD_NBT_TAGS.STRING) {
        const textValue = String(rawValue ?? '');
        const normalized = textValue.trim().toLowerCase();
        if (normalized === 'true' || normalized === 'false') {
          valueType = 'boolean';
          value = normalized === 'true';
        } else if (/^-?\d+$/.test(textValue.trim())) {
          valueType = 'integer';
          value = parseInt(textValue, 10);
        } else {
          value = textValue;
        }
      } else if (storageTagType === WORLD_NBT_TAGS.BYTE) {
        const numericValue = worldEditorIntValue(rawValue, 0) ?? 0;
        if (numericValue === 0 || numericValue === 1) {
          valueType = 'boolean';
          value = numericValue === 1;
        } else {
          valueType = 'integer';
          value = numericValue;
        }
      } else if (
        storageTagType === WORLD_NBT_TAGS.SHORT ||
        storageTagType === WORLD_NBT_TAGS.INT ||
        storageTagType === WORLD_NBT_TAGS.LONG
      ) {
        valueType = 'integer';
        value = worldEditorIntValue(rawValue, 0) ?? 0;
      } else {
        value = String(rawValue ?? '');
      }

      return {
        name,
        label: formatWorldGameRuleLabel(name),
        value_type: valueType,
        value,
        storage_tag_type: storageTagType,
      };
    });
};

const setWorldEditorGameRuleValue = (gameRulesValue, rule) => {
  if (!isWorldEditorObject(gameRulesValue) || !rule || !rule.name) return;

  const existingTag = getWorldEditorTag(gameRulesValue, rule.name);
  const storageTagType = getWorldEditorTagType(
    existingTag,
    rule.storage_tag_type ?? WORLD_NBT_TAGS.STRING
  );

  if (storageTagType === WORLD_NBT_TAGS.STRING || !WORLD_NBT_NUMERIC_TAGS.has(storageTagType)) {
    const serializedValue = rule.value_type === 'boolean'
      ? (rule.value ? 'true' : 'false')
      : String(rule.value ?? '');
    setWorldEditorCompoundTag(gameRulesValue, rule.name, WORLD_NBT_TAGS.STRING, serializedValue);
    return;
  }

  if (rule.value_type === 'boolean') {
    setWorldEditorCompoundTag(gameRulesValue, rule.name, storageTagType, rule.value ? 1 : 0);
    return;
  }

  if (rule.value_type === 'integer') {
    setWorldEditorCompoundTag(
      gameRulesValue,
      rule.name,
      storageTagType,
      worldEditorIntValue(rule.value, 0) ?? 0
    );
    return;
  }

  setWorldEditorCompoundTag(gameRulesValue, rule.name, WORLD_NBT_TAGS.STRING, String(rule.value ?? ''));
};

const extractWorldSimpleStateFromRoot = (root) => {
  const rootValue = getWorldEditorRootValue(root);
  const dataValue = getWorldEditorCompoundValue(rootValue, 'Data') || {};
  const playerValue = getWorldEditorCompoundValue(dataValue, 'Player');
  const [playerX, playerY, playerZ] = playerValue ? getWorldEditorPosition(playerValue) : [null, null, null];
  const inventoryListValue = playerValue ? getWorldEditorListPayload(playerValue, 'Inventory') : null;
  const enderListValue = playerValue ? getWorldEditorListPayload(playerValue, 'EnderItems') : null;
  const inventoryItems = playerValue ? getWorldEditorItemList(playerValue, 'Inventory') : [];
  const enderItems = playerValue ? getWorldEditorItemList(playerValue, 'EnderItems') : [];
  const gameRules = extractWorldGameRules(dataValue);
  const versionInfo = getWorldEditorVersionInfo(dataValue);
  const supportsEnderChest = worldEditorSupportsMinecraftVersion(versionInfo, '1.3.1');
  const supportsOffhandSlot = worldEditorSupportsMinecraftVersion(versionInfo, '1.9');
  const usesModernItemFormat = worldEditorUsesModernItemFormat(versionInfo, [inventoryListValue, enderListValue]);
  const features = {
    has_raining: !!getWorldEditorTag(dataValue, 'raining'),
    has_thundering: !!getWorldEditorTag(dataValue, 'thundering'),
    has_rain_time: !!getWorldEditorTag(dataValue, 'rainTime'),
    has_thunder_time: !!getWorldEditorTag(dataValue, 'thunderTime'),
    has_clear_weather_time: !!getWorldEditorTag(dataValue, 'clearWeatherTime'),
    has_selected_item_slot: !!(playerValue && getWorldEditorTag(playerValue, 'SelectedItemSlot')),
    has_ender_chest: !!(playerValue && getWorldEditorTag(playerValue, 'EnderItems')) || supportsEnderChest,
    has_offhand_slot: inventoryItems.some((item) => item.slot === -106) || supportsOffhandSlot,
    has_gamerules: gameRules.length > 0,
    uses_modern_item_format: usesModernItemFormat,
  };

  return {
    world_title: String(getWorldEditorTagValue(dataValue, 'LevelName', '') || ''),
    game_mode: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'GameType', 0), 0),
    difficulty: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'Difficulty', 1), 1),
    allow_commands: worldEditorBoolValue(getWorldEditorTagValue(dataValue, 'allowCommands', 0)),
    hardcore: worldEditorBoolValue(getWorldEditorTagValue(dataValue, 'hardcore', 0)),
    raining: worldEditorBoolValue(getWorldEditorTagValue(dataValue, 'raining', 0)),
    thundering: worldEditorBoolValue(getWorldEditorTagValue(dataValue, 'thundering', 0)),
    time: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'Time', 0), 0),
    day_time: worldEditorIntValue(
      getWorldEditorTagValue(dataValue, 'DayTime', getWorldEditorTagValue(dataValue, 'Time', 0)),
      0
    ),
    rain_time: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'rainTime', 0), 0),
    thunder_time: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'thunderTime', 0), 0),
    clear_weather_time: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'clearWeatherTime', 0), 0),
    spawn_x: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'SpawnX', 0), 0),
    spawn_y: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'SpawnY', 0), 0),
    spawn_z: worldEditorIntValue(getWorldEditorTagValue(dataValue, 'SpawnZ', 0), 0),
    has_player_data: !!playerValue,
    health: playerValue ? worldEditorFloatValue(getWorldEditorTagValue(playerValue, 'Health', null), null) : null,
    food_level: playerValue ? worldEditorIntValue(getWorldEditorTagValue(playerValue, 'foodLevel', null), null) : null,
    food_saturation: playerValue
      ? worldEditorFloatValue(getWorldEditorTagValue(playerValue, 'foodSaturationLevel', null), null)
      : null,
    xp_level: playerValue ? worldEditorIntValue(getWorldEditorTagValue(playerValue, 'XpLevel', null), null) : null,
    xp_total: playerValue ? worldEditorIntValue(getWorldEditorTagValue(playerValue, 'XpTotal', null), null) : null,
    selected_item_slot: playerValue
      ? worldEditorIntValue(getWorldEditorTagValue(playerValue, 'SelectedItemSlot', null), null)
      : null,
    player_x: playerX,
    player_y: playerY,
    player_z: playerZ,
    inventory_items: inventoryItems,
    ender_items: enderItems,
    game_rules: gameRules,
    features,
  };
};

const setWorldEditorItemList = (playerValue, listKey, items, { useModernItemFormat = false } = {}) => {
  if (!isWorldEditorObject(playerValue)) return;

  const existingTag = getWorldEditorTag(playerValue, listKey);
  const existingBySlot = new Map();
  let listUsesModernItemFormat = !!useModernItemFormat;
  if (existingTag && getWorldEditorTagType(existingTag) === WORLD_NBT_TAGS.LIST && isWorldEditorObject(existingTag.value)) {
    const currentItems = Array.isArray(existingTag.value.items) ? existingTag.value.items : [];
    currentItems.forEach((entry) => {
      if (!isWorldEditorObject(entry)) return;
      if (getWorldEditorTag(entry, 'count')) {
        listUsesModernItemFormat = true;
      }
      const slot = worldEditorIntValue(getWorldEditorTagValue(entry, 'Slot', null), null);
      if (slot === null) return;
      existingBySlot.set(slot, entry);
    });
  }

  const nextItems = [];
  (Array.isArray(items) ? items : []).forEach((item) => {
    const slot = worldEditorIntValue(item && item.slot, 0) ?? 0;
    let entry = existingBySlot.get(slot);
    if (!isWorldEditorObject(entry)) entry = {};
    setWorldEditorCompoundTag(entry, 'Slot', WORLD_NBT_TAGS.BYTE, slot);
    setWorldEditorCompoundTag(entry, 'id', WORLD_NBT_TAGS.STRING, item && item.item_id ? item.item_id : '');
    const stackCount = worldEditorIntValue(item && item.count, 1) ?? 1;
    if (listUsesModernItemFormat || getWorldEditorTag(entry, 'count')) {
      setWorldEditorCompoundTag(entry, 'count', WORLD_NBT_TAGS.INT, stackCount);
      delete entry.Count;
    } else {
      setWorldEditorCompoundTag(entry, 'Count', WORLD_NBT_TAGS.BYTE, stackCount);
      delete entry.count;
    }
    nextItems.push(entry);
  });

  playerValue[listKey] = {
    type: WORLD_NBT_TAGS.LIST,
    value: {
      list_type: WORLD_NBT_TAGS.COMPOUND,
      items: nextItems,
    },
  };
};

const setWorldEditorPosition = (playerValue, xValue, yValue, zValue) => {
  if (!isWorldEditorObject(playerValue)) return;
  if (xValue === null || yValue === null || zValue === null) return;

  const existingValue = getWorldEditorListPayload(playerValue, 'Pos') || {};
  let listType = worldEditorIntValue(existingValue.list_type, WORLD_NBT_TAGS.DOUBLE) ?? WORLD_NBT_TAGS.DOUBLE;
  if (![WORLD_NBT_TAGS.DOUBLE, WORLD_NBT_TAGS.FLOAT].includes(listType)) {
    listType = WORLD_NBT_TAGS.DOUBLE;
  }

  playerValue.Pos = {
    type: WORLD_NBT_TAGS.LIST,
    value: {
      list_type: listType,
      items: [Number(xValue), Number(yValue), Number(zValue)],
    },
  };
};

const applyWorldEditorTitleToRoot = (root, title) => {
  const trimmedTitle = String(title || '').trim();
  if (!trimmedTitle) return root;
  const rootValue = getWorldEditorRootValue(root);
  const dataValue = ensureWorldEditorCompoundValue(rootValue, 'Data');
  setWorldEditorCompoundTag(dataValue, 'LevelName', WORLD_NBT_TAGS.STRING, trimmedTitle);
  return root;
};

const applyWorldSimpleStateToRoot = (root, simpleState, worldTitle = '') => {
  if (!isWorldEditorObject(root)) return root;

  const rootValue = getWorldEditorRootValue(root);
  const dataValue = ensureWorldEditorCompoundValue(rootValue, 'Data');
  const features = isWorldEditorObject(simpleState && simpleState.features) ? simpleState.features : {};
  const wantsRain = !!(simpleState.raining || simpleState.thundering);
  const wantsThunder = !!simpleState.thundering;
  const normalizedRainTime = getWorldEditorWeatherDuration(simpleState.rain_time);
  const normalizedThunderTime = getWorldEditorWeatherDuration(simpleState.thunder_time);
  const effectiveRainTime = wantsThunder
    ? Math.max(normalizedRainTime, normalizedThunderTime)
    : normalizedRainTime;
  const normalizedClearWeatherTime = wantsRain
    ? 0
    : getWorldEditorWeatherDuration(simpleState.clear_weather_time);

  applyWorldEditorTitleToRoot(root, worldTitle || simpleState.world_title);
  setWorldEditorCompoundTag(dataValue, 'GameType', WORLD_NBT_TAGS.INT, simpleState.game_mode ?? 0);
  setWorldEditorCompoundTag(dataValue, 'Difficulty', WORLD_NBT_TAGS.BYTE, simpleState.difficulty ?? 1);
  setWorldEditorCompoundTag(dataValue, 'allowCommands', WORLD_NBT_TAGS.BYTE, simpleState.allow_commands ? 1 : 0);
  setWorldEditorCompoundTag(dataValue, 'hardcore', WORLD_NBT_TAGS.BYTE, simpleState.hardcore ? 1 : 0);
  if (features.has_raining) {
    setWorldEditorCompoundTag(dataValue, 'raining', WORLD_NBT_TAGS.BYTE, wantsRain ? 1 : 0);
  }
  if (features.has_thundering) {
    setWorldEditorCompoundTag(dataValue, 'thundering', WORLD_NBT_TAGS.BYTE, wantsThunder ? 1 : 0);
  }
  setWorldEditorCompoundTag(dataValue, 'Time', WORLD_NBT_TAGS.LONG, simpleState.time ?? 0);
  setWorldEditorCompoundTag(
    dataValue,
    'DayTime',
    WORLD_NBT_TAGS.LONG,
    simpleState.day_time ?? simpleState.time ?? 0
  );
  if (features.has_rain_time) {
    setWorldEditorCompoundTag(dataValue, 'rainTime', WORLD_NBT_TAGS.INT, effectiveRainTime);
  }
  if (features.has_thunder_time) {
    setWorldEditorCompoundTag(dataValue, 'thunderTime', WORLD_NBT_TAGS.INT, normalizedThunderTime);
  }
  if (features.has_clear_weather_time) {
    setWorldEditorCompoundTag(dataValue, 'clearWeatherTime', WORLD_NBT_TAGS.INT, normalizedClearWeatherTime);
  }
  setWorldEditorCompoundTag(dataValue, 'SpawnX', WORLD_NBT_TAGS.INT, simpleState.spawn_x ?? 0);
  setWorldEditorCompoundTag(dataValue, 'SpawnY', WORLD_NBT_TAGS.INT, simpleState.spawn_y ?? 0);
  setWorldEditorCompoundTag(dataValue, 'SpawnZ', WORLD_NBT_TAGS.INT, simpleState.spawn_z ?? 0);

  if (features.has_gamerules && Array.isArray(simpleState.game_rules) && simpleState.game_rules.length > 0) {
    const gameRulesValue = ensureWorldEditorCompoundValue(dataValue, 'GameRules');
    simpleState.game_rules.forEach((rule) => {
      setWorldEditorGameRuleValue(gameRulesValue, rule);
    });
  }

  const wantsPlayerUpdates =
    !!simpleState.has_player_data ||
    simpleState.health !== null ||
    simpleState.food_level !== null ||
    simpleState.food_saturation !== null ||
    simpleState.xp_level !== null ||
    simpleState.xp_total !== null ||
    simpleState.selected_item_slot !== null ||
    simpleState.player_x !== null ||
    simpleState.player_y !== null ||
    simpleState.player_z !== null ||
    (Array.isArray(simpleState.inventory_items) && simpleState.inventory_items.length > 0) ||
    (Array.isArray(simpleState.ender_items) && simpleState.ender_items.length > 0);

  const playerValue = wantsPlayerUpdates
    ? ensureWorldEditorCompoundValue(dataValue, 'Player')
    : getWorldEditorCompoundValue(dataValue, 'Player');

  if (playerValue) {
    if (simpleState.health !== null) {
      setWorldEditorCompoundTag(playerValue, 'Health', WORLD_NBT_TAGS.FLOAT, simpleState.health);
    }
    if (simpleState.food_level !== null) {
      setWorldEditorCompoundTag(playerValue, 'foodLevel', WORLD_NBT_TAGS.INT, simpleState.food_level);
    }
    if (simpleState.food_saturation !== null) {
      setWorldEditorCompoundTag(
        playerValue,
        'foodSaturationLevel',
        WORLD_NBT_TAGS.FLOAT,
        simpleState.food_saturation
      );
    }
    if (simpleState.xp_level !== null) {
      setWorldEditorCompoundTag(playerValue, 'XpLevel', WORLD_NBT_TAGS.INT, simpleState.xp_level);
    }
    if (simpleState.xp_total !== null) {
      setWorldEditorCompoundTag(playerValue, 'XpTotal', WORLD_NBT_TAGS.INT, simpleState.xp_total);
    }
    if (simpleState.selected_item_slot !== null) {
      setWorldEditorCompoundTag(
        playerValue,
        'SelectedItemSlot',
        WORLD_NBT_TAGS.INT,
        simpleState.selected_item_slot
      );
    }
    if (
      simpleState.player_x !== null &&
      simpleState.player_y !== null &&
      simpleState.player_z !== null
    ) {
      setWorldEditorPosition(playerValue, simpleState.player_x, simpleState.player_y, simpleState.player_z);
    }
    if (Array.isArray(simpleState.inventory_items)) {
      setWorldEditorItemList(playerValue, 'Inventory', simpleState.inventory_items, {
        useModernItemFormat: !!features.uses_modern_item_format,
      });
    }
    if (features.has_ender_chest && Array.isArray(simpleState.ender_items)) {
      setWorldEditorItemList(playerValue, 'EnderItems', simpleState.ender_items, {
        useModernItemFormat: !!features.uses_modern_item_format,
      });
    }
  }

  return root;
};

const parseWorldEditorAdvancedRoot = (text) => {
  const parsed = JSON.parse(String(text || '').trim() || '{}');
  if (!isWorldEditorObject(parsed)) {
    throw new Error('The advanced NBT editor expects a JSON object at the root.');
  }
  if (worldEditorIntValue(parsed.type, null) !== WORLD_NBT_TAGS.COMPOUND) {
    throw new Error('root.type must be 10 so the level.dat root stays a compound tag.');
  }
  if (!isWorldEditorObject(parsed.value)) {
    throw new Error('root.value must be a JSON object.');
  }
  if (typeof parsed.name !== 'string') {
    parsed.name = String(parsed.name || '');
  }
  return parsed;
};

const formatWorldEditorAdvancedRoot = (root) => JSON.stringify(root, null, 2);

const parseWorldEditorIntegerField = (
  rawValue,
  label,
  {
    min = null,
    max = null,
    defaultValue = null,
    allowEmpty = true,
  } = {}
) => {
  const raw = String(rawValue ?? '').trim();
  if (!raw) {
    if (allowEmpty) return defaultValue;
    throw new Error(`${label} is required.`);
  }
  if (!/^-?\d+$/.test(raw)) {
    throw new Error(`${label} must be a whole number.`);
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${label} must be a whole number.`);
  }
  if (min !== null && parsed < min) {
    throw new Error(`${label} must be at least ${min}.`);
  }
  if (max !== null && parsed > max) {
    throw new Error(`${label} must be at most ${max}.`);
  }
  return Math.trunc(parsed);
};

const parseWorldEditorFloatField = (
  rawValue,
  label,
  {
    min = null,
    max = null,
    defaultValue = null,
    allowEmpty = true,
  } = {}
) => {
  const raw = String(rawValue ?? '').trim();
  if (!raw) {
    if (allowEmpty) return defaultValue;
    throw new Error(`${label} is required.`);
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${label} must be a number.`);
  }
  if (min !== null && parsed < min) {
    throw new Error(`${label} must be at least ${min}.`);
  }
  if (max !== null && parsed > max) {
    throw new Error(`${label} must be at most ${max}.`);
  }
  return parsed;
};

const normalizeWorldEditorInventoryItems = (
  value,
  {
    itemLabel = 'Inventory item',
    minSlot = 0,
    maxSlot = 255,
  } = {}
) => {
  if (!Array.isArray(value)) return [];

  const normalizedBySlot = new Map();
  value.forEach((entry, index) => {
    if (!entry || typeof entry !== 'object') {
      throw new Error(`${itemLabel} #${index + 1} is invalid.`);
    }

    const rawSlot = String(entry.slot ?? '').trim();
    const rawItemId = String(entry.item_id || entry.id || '').trim();
    const rawCount = String(entry.count ?? '').trim();

    if (!rawSlot && !rawItemId && !rawCount) return;

    const slot = parseWorldEditorIntegerField(rawSlot, `${itemLabel} #${index + 1} slot`, {
      min: minSlot,
      max: maxSlot,
      allowEmpty: false,
    });
    const count = parseWorldEditorIntegerField(rawCount, `${itemLabel} #${index + 1} count`, {
      min: 0,
      max: 127,
      defaultValue: 1,
    });

    if (normalizedBySlot.has(slot)) {
      throw new Error(`${itemLabel} slot ${slot} is duplicated.`);
    }

    if (!rawItemId || !count) return;
    normalizedBySlot.set(slot, {
      slot,
      item_id: rawItemId,
      count,
    });
  });

  return Array.from(normalizedBySlot.values()).sort((left, right) => left.slot - right.slot);
};

const closeAllWorldEditorPickers = (exceptPopover = null) => {
  document.querySelectorAll('.world-nbt-picker-popover').forEach((popover) => {
    if (!(popover instanceof HTMLElement)) return;
    if (exceptPopover && popover === exceptPopover) return;
    if (typeof popover._worldNbtClose === 'function') {
      popover._worldNbtClose();
      return;
    }
    popover.classList.add('hidden');
  });
};

const createWorldEditorPickerControl = (
  input,
  {
    buttonLabel = 'Pick',
    popoverClassName = '',
    renderPopover = null,
  } = {}
) => {
  const wrapper = document.createElement('div');
  wrapper.className = 'world-nbt-input-with-picker';

  const inputWrap = document.createElement('div');
  inputWrap.className = 'world-nbt-input-with-picker-input';
  inputWrap.appendChild(input);
  wrapper.appendChild(inputWrap);

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'important world-nbt-picker-button';
  button.textContent = buttonLabel;
  wrapper.appendChild(button);

  const popover = document.createElement('div');
  popover.className = ['world-nbt-picker-popover', 'hidden', popoverClassName].filter(Boolean).join(' ');
  wrapper.appendChild(popover);

  let detachGlobalHandlers = null;

  const handleViewportChange = () => {
    if (!popover.classList.contains('hidden')) {
      requestAnimationFrame(updatePosition);
    }
  };

  const handleDocumentPointerDown = (event) => {
    if (!(event.target instanceof Node)) return;
    if (!wrapper.contains(event.target)) close();
  };

  const attachGlobalHandlers = () => {
    if (detachGlobalHandlers) return;
    window.addEventListener('resize', handleViewportChange);
    document.addEventListener('scroll', handleViewportChange, true);
    document.addEventListener('mousedown', handleDocumentPointerDown);
    detachGlobalHandlers = () => {
      window.removeEventListener('resize', handleViewportChange);
      document.removeEventListener('scroll', handleViewportChange, true);
      document.removeEventListener('mousedown', handleDocumentPointerDown);
      detachGlobalHandlers = null;
    };
  };

  const close = () => {
    if (typeof detachGlobalHandlers === 'function') {
      detachGlobalHandlers();
    }
    popover.classList.add('hidden');
  };
  popover._worldNbtClose = close;

  const updatePosition = () => {
    if (popover.classList.contains('hidden')) return;
    if (!wrapper.isConnected) {
      close();
      return;
    }

    const anchorRect = button.getBoundingClientRect();
    const viewportPadding = 12;

    popover.style.left = `${viewportPadding}px`;
    popover.style.top = `${viewportPadding}px`;

    const popoverWidth = Math.min(
      popover.offsetWidth || 0,
      Math.max(240, window.innerWidth - (viewportPadding * 2))
    );
    const popoverHeight = popover.offsetHeight || 0;

    let left = anchorRect.left;
    if (left + popoverWidth > window.innerWidth - viewportPadding) {
      left = window.innerWidth - popoverWidth - viewportPadding;
    }
    left = Math.max(viewportPadding, left);

    let top = anchorRect.bottom + 6;
    if (top + popoverHeight > window.innerHeight - viewportPadding) {
      top = Math.max(viewportPadding, anchorRect.top - popoverHeight - 6);
    }

    popover.style.left = `${Math.round(left)}px`;
    popover.style.top = `${Math.round(top)}px`;
  };

  const refresh = () => {
    if (typeof renderPopover !== 'function') return;
    popover.innerHTML = '';
    renderPopover(popover, { close });
    if (!popover.classList.contains('hidden')) {
      requestAnimationFrame(updatePosition);
    }
  };

  button.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (popover.classList.contains('hidden')) {
      closeAllWorldEditorPickers(popover);
      refresh();
      popover.classList.remove('hidden');
      attachGlobalHandlers();
      requestAnimationFrame(updatePosition);
    } else {
      close();
    }
  });

  input.addEventListener('input', () => {
    if (!popover.classList.contains('hidden')) refresh();
  });

  return { element: wrapper, input, button, popover, close, refresh };
};

const createWorldEditorSlotGridSection = ({
  title,
  rows,
  selectedSlot = null,
  onSelect,
  noteText = '',
}) => {
  const section = document.createElement('div');
  section.className = 'world-nbt-picker-section';

  const header = document.createElement('div');
  header.className = 'world-nbt-picker-title';
  header.textContent = title;
  section.appendChild(header);

  (Array.isArray(rows) ? rows : []).forEach((rowData) => {
    const row = document.createElement('div');
    row.className = 'world-nbt-picker-row';
    if (!rowData || !rowData.label) {
      row.classList.add('world-nbt-picker-row-full');
    }

    if (rowData && rowData.label) {
      const rowLabel = document.createElement('span');
      rowLabel.className = 'world-nbt-picker-row-label';
      rowLabel.textContent = rowData.label;
      row.appendChild(rowLabel);
    }

    const grid = document.createElement('div');
    grid.className = 'world-nbt-picker-grid';

    (Array.isArray(rowData && rowData.slots) ? rowData.slots : []).forEach((slotData) => {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'world-nbt-picker-slot';
      cell.textContent = String(slotData && slotData.label ? slotData.label : '');
      cell.title = String(slotData && slotData.ariaLabel ? slotData.ariaLabel : '');
      cell.classList.toggle('selected', slotData && slotData.slot === selectedSlot);
      cell.addEventListener('click', () => {
        if (typeof onSelect === 'function') onSelect(slotData.slot);
      });
      grid.appendChild(cell);
    });

    row.appendChild(grid);
    section.appendChild(row);
  });

  if (noteText) {
    const note = document.createElement('p');
    note.className = 'world-nbt-picker-note';
    note.textContent = noteText;
    section.appendChild(note);
  }

  return section;
};

const createWorldEditorHotbarSelector = (selectedSlot = null) => {
  const input = createWorldEditorNumberInput(
    selectedSlot === null || selectedSlot === undefined ? '' : selectedSlot + 1,
    { min: 1, max: 9 }
  );
  input.placeholder = '1-9';

  const picker = createWorldEditorPickerControl(input, {
    buttonLabel: 'Pick',
    renderPopover: (popover, { close }) => {
      const parsedInputValue = worldEditorIntValue(input.value, null);
      const currentValue = parsedInputValue !== null && parsedInputValue >= 1 && parsedInputValue <= 9
        ? parsedInputValue
        : null;

      popover.appendChild(createWorldEditorSlotGridSection({
        title: 'Hotbar',
        rows: [
          {
            slots: Array.from({ length: 9 }, (_item, index) => ({
              slot: index,
              label: String(index + 1),
              ariaLabel: `Hotbar slot ${index + 1}`,
            })),
          },
        ],
        selectedSlot: currentValue === null ? null : currentValue - 1,
        onSelect: (slot) => {
          input.value = String(slot + 1);
          close();
        },
        noteText: 'Choose the hotbar slot the player should have selected when the world loads.',
      }));
    },
  });

  return {
    element: picker.element,
    input,
    getValue: () => parseWorldEditorIntegerField(input.value, 'Selected Hotbar Slot', {
      min: 1,
      max: 9,
      defaultValue: null,
    }),
  };
};

const createWorldEditorSlotPickerInput = ({
  value = '',
  min = 0,
  max = 255,
  placeholder = 'Slot',
  pickerType = 'player-inventory',
  showOffhandSlot = true,
} = {}) => {
  const input = createWorldEditorNumberInput(value, { min, max });
  input.placeholder = placeholder;

  const picker = createWorldEditorPickerControl(input, {
    buttonLabel: 'Pick',
    renderPopover: (popover, { close }) => {
      const parsedInputValue = worldEditorIntValue(input.value, null);
      const selectedSlot = parsedInputValue !== null && parsedInputValue >= min && parsedInputValue <= max
        ? parsedInputValue
        : null;

      if (pickerType === 'ender-chest') {
        const rows = [
          [0, 1, 2, 3, 4, 5, 6, 7, 8],
          [9, 10, 11, 12, 13, 14, 15, 16, 17],
          [18, 19, 20, 21, 22, 23, 24, 25, 26],
        ].map((slots, rowIndex) => ({
          label: ['Top', 'Middle', 'Bottom'][rowIndex],
          slots: slots.map((slot, slotIndex) => ({
            slot,
            label: String(slot),
            ariaLabel: `Ender chest row ${rowIndex + 1}, slot ${slot}`,
          })),
        }));

        popover.appendChild(createWorldEditorSlotGridSection({
          title: 'Ender Chest Layout',
          rows,
          selectedSlot,
          onSelect: (slot) => {
            input.value = String(slot);
            close();
          },
        }));
        return;
      }

      const inventoryRows = [
        [9, 10, 11, 12, 13, 14, 15, 16, 17],
        [18, 19, 20, 21, 22, 23, 24, 25, 26],
        [27, 28, 29, 30, 31, 32, 33, 34, 35],
      ].map((slots, rowIndex) => ({
        label: ['Top', 'Middle', 'Bottom'][rowIndex],
        slots: slots.map((slot, slotIndex) => ({
          slot,
          label: String(slot),
          ariaLabel: `Inventory row ${rowIndex + 1}, slot ${slot}`,
        })),
      }));

      const hotbarRows = [
        {
          slots: Array.from({ length: 9 }, (_item, index) => ({
            slot: index,
            label: String(index),
            ariaLabel: `Hotbar slot ${index}`,
          })),
        },
      ];

      const armorAndOffhandRows = [
        { label: 'Helmet', slot: 103 },
        { label: 'Chest', slot: 102 },
        { label: 'Legs', slot: 101 },
        { label: 'Boots', slot: 100 },
      ];

      if (showOffhandSlot) {
        armorAndOffhandRows.push({ label: 'Offhand', slot: -106 });
      }

      const armorAndOffhandRowsLayout = armorAndOffhandRows.map((entry) => ({
        label: entry.label,
        slots: [
          {
            slot: entry.slot,
            label: String(entry.slot),
            ariaLabel: `${entry.label} slot ${entry.slot}`,
          },
        ],
      }));

      popover.appendChild(createWorldEditorSlotGridSection({
        title: showOffhandSlot ? 'Armor & Offhand' : 'Armor',
        rows: armorAndOffhandRowsLayout,
        selectedSlot,
        onSelect: (slot) => {
          input.value = String(slot);
          close();
        },
      }));

      popover.appendChild(createWorldEditorSlotGridSection({
        title: 'Inventory Layout',
        rows: inventoryRows,
        selectedSlot,
        onSelect: (slot) => {
          input.value = String(slot);
          close();
        },
      }));

      popover.appendChild(createWorldEditorSlotGridSection({
        title: 'Hotbar',
        rows: hotbarRows,
        selectedSlot,
        onSelect: (slot) => {
          input.value = String(slot);
          close();
        },
        noteText: 'This picker covers inventory, hotbar, armor, and offhand slots (if compatible).',
      }));
    },
  });

  return {
    element: picker.element,
    input,
    getValue: () => String(input.value || '').trim(),
  };
};

const createWorldEditorInventorySection = ({
  title,
  description,
  items,
  addButtonLabel,
  slotPlaceholder,
  itemPlaceholder,
  countPlaceholder = 'Count',
  slotTooltip,
  itemTooltip,
  countTooltip,
  slotMax,
  createSlotControl = null,
}) => {
  const { section, body } = createWorldEditorSection(title, description);

  const header = document.createElement('div');
  header.className = 'world-nbt-inventory-header';
  [
    createWorldEditorLabelRow('Slot', slotTooltip),
    createWorldEditorLabelRow('Item ID', itemTooltip),
    createWorldEditorLabelRow('Count', countTooltip),
    document.createElement('span'),
  ].forEach((node) => header.appendChild(node));
  body.appendChild(header);

  const inventoryList = document.createElement('div');
  inventoryList.className = 'world-nbt-inventory-list';
  body.appendChild(inventoryList);

  const addRow = (item = {}) => {
    const row = document.createElement('div');
    row.className = 'world-nbt-inventory-row';

    const slotControl = typeof createSlotControl === 'function'
      ? createSlotControl(item.slot ?? '')
      : (() => {
          const slotInput = createWorldEditorNumberInput(item.slot ?? '', { min: 0, max: slotMax });
          slotInput.placeholder = slotPlaceholder;
          slotInput.dataset.field = 'slot';
          return {
            element: slotInput,
            getValue: () => slotInput.value || '',
          };
        })();

    const itemIdInput = createWorldEditorTextInput(item.item_id || '');
    itemIdInput.placeholder = itemPlaceholder;
    itemIdInput.dataset.field = 'item_id';

    const countValue = Object.prototype.hasOwnProperty.call(item, 'count') ? item.count : '';
    const countInput = createWorldEditorNumberInput(countValue, { min: 0, max: 127 });
    countInput.placeholder = countPlaceholder;
    countInput.dataset.field = 'count';

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'danger';
    removeBtn.textContent = 'Remove';
    removeBtn.addEventListener('click', () => row.remove());

    row._slotControl = slotControl;
    row.appendChild(slotControl.element);
    row.appendChild(itemIdInput);
    row.appendChild(countInput);
    row.appendChild(removeBtn);
    inventoryList.appendChild(row);
  };

  (Array.isArray(items) ? items : []).forEach((item) => addRow(item));
  if (!inventoryList.childElementCount) addRow();

  const actions = document.createElement('div');
  actions.className = 'world-nbt-inline-actions';

  const addItemBtn = document.createElement('button');
  addItemBtn.type = 'button';
  addItemBtn.className = 'primary';
  addItemBtn.textContent = addButtonLabel;
  addItemBtn.addEventListener('click', () => addRow());
  actions.appendChild(addItemBtn);
  body.appendChild(actions);

  const getItems = () => Array.from(inventoryList.querySelectorAll('.world-nbt-inventory-row')).map((row) => ({
    slot: row._slotControl && typeof row._slotControl.getValue === 'function'
      ? row._slotControl.getValue()
      : (row.querySelector('[data-field="slot"]')?.value || ''),
    item_id: row.querySelector('[data-field="item_id"]')?.value || '',
    count: row.querySelector('[data-field="count"]')?.value || '',
  }));

  return { section, getItems };
};

const cloneWorldSimpleItems = (items) => Array.isArray(items)
  ? items.map((item) => ({ ...(item || {}) }))
  : [];

const cloneWorldSimpleGameRules = (rules) => Array.isArray(rules)
  ? rules.map((rule) => ({ ...(rule || {}) }))
  : [];

const cloneWorldSimpleFeatures = (features) => isWorldEditorObject(features)
  ? { ...features }
  : {};

const cloneWorldSimpleState = (simple) => {
  const cloned = isWorldEditorObject(simple) ? { ...simple } : {};
  cloned.features = cloneWorldSimpleFeatures(simple && simple.features);
  cloned.inventory_items = cloneWorldSimpleItems(simple && simple.inventory_items);
  cloned.ender_items = cloneWorldSimpleItems(simple && simple.ender_items);
  cloned.game_rules = cloneWorldSimpleGameRules(simple && simple.game_rules);
  return cloned;
};

const getWorldSimpleGlobalSnapshot = (simple) => {
  const source = cloneWorldSimpleState(simple);
  return {
    world_title: String(source.world_title || ''),
    game_mode: source.game_mode ?? 0,
    difficulty: source.difficulty ?? 1,
    allow_commands: !!source.allow_commands,
    hardcore: !!source.hardcore,
    raining: !!source.raining,
    thundering: !!source.thundering,
    time: source.time ?? 0,
    day_time: source.day_time ?? source.time ?? 0,
    rain_time: source.rain_time ?? 0,
    thunder_time: source.thunder_time ?? 0,
    clear_weather_time: source.clear_weather_time ?? 0,
    spawn_x: source.spawn_x ?? 0,
    spawn_y: source.spawn_y ?? 0,
    spawn_z: source.spawn_z ?? 0,
    game_rules: cloneWorldSimpleGameRules(source.game_rules),
    features: {
      has_raining: !!(source.features && source.features.has_raining),
      has_thundering: !!(source.features && source.features.has_thundering),
      has_rain_time: !!(source.features && source.features.has_rain_time),
      has_thunder_time: !!(source.features && source.features.has_thunder_time),
      has_clear_weather_time: !!(source.features && source.features.has_clear_weather_time),
      has_gamerules: !!(source.features && source.features.has_gamerules),
    },
  };
};

const getWorldSimplePlayerSnapshot = (simple) => {
  const source = cloneWorldSimpleState(simple);
  return {
    has_player_data: !!source.has_player_data,
    health: source.health ?? null,
    food_level: source.food_level ?? null,
    food_saturation: source.food_saturation ?? null,
    xp_level: source.xp_level ?? null,
    xp_total: source.xp_total ?? null,
    selected_item_slot: source.selected_item_slot ?? null,
    player_x: source.player_x ?? null,
    player_y: source.player_y ?? null,
    player_z: source.player_z ?? null,
    inventory_items: cloneWorldSimpleItems(source.inventory_items),
    ender_items: cloneWorldSimpleItems(source.ender_items),
    features: {
      has_selected_item_slot: !!(source.features && source.features.has_selected_item_slot),
      has_ender_chest: !!(source.features && source.features.has_ender_chest),
      has_offhand_slot: !!(source.features && source.features.has_offhand_slot),
      uses_modern_item_format: !!(source.features && source.features.uses_modern_item_format),
    },
  };
};

const applyWorldSimpleGlobalSnapshot = (targetState, snapshot) => {
  if (!isWorldEditorObject(targetState) || !isWorldEditorObject(snapshot)) return targetState;

  targetState.world_title = String(snapshot.world_title || '');
  targetState.game_mode = snapshot.game_mode ?? 0;
  targetState.difficulty = snapshot.difficulty ?? 1;
  targetState.allow_commands = !!snapshot.allow_commands;
  targetState.hardcore = !!snapshot.hardcore;
  targetState.raining = !!snapshot.raining;
  targetState.thundering = !!snapshot.thundering;
  targetState.time = snapshot.time ?? 0;
  targetState.day_time = snapshot.day_time ?? targetState.time ?? 0;
  targetState.rain_time = snapshot.rain_time ?? 0;
  targetState.thunder_time = snapshot.thunder_time ?? 0;
  targetState.clear_weather_time = snapshot.clear_weather_time ?? 0;
  targetState.spawn_x = snapshot.spawn_x ?? 0;
  targetState.spawn_y = snapshot.spawn_y ?? 0;
  targetState.spawn_z = snapshot.spawn_z ?? 0;
  targetState.game_rules = cloneWorldSimpleGameRules(snapshot.game_rules);
  targetState.features = cloneWorldSimpleFeatures(targetState.features);

  const snapshotFeatures = isWorldEditorObject(snapshot.features) ? snapshot.features : {};
  [
    'has_raining',
    'has_thundering',
    'has_rain_time',
    'has_thunder_time',
    'has_clear_weather_time',
    'has_gamerules',
  ].forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(snapshotFeatures, key)) {
      targetState.features[key] = !!snapshotFeatures[key];
    }
  });

  return targetState;
};

const applyWorldSimplePlayerSnapshot = (targetState, snapshot) => {
  if (!isWorldEditorObject(targetState) || !isWorldEditorObject(snapshot)) return targetState;

  targetState.has_player_data = !!snapshot.has_player_data;
  targetState.health = snapshot.health ?? null;
  targetState.food_level = snapshot.food_level ?? null;
  targetState.food_saturation = snapshot.food_saturation ?? null;
  targetState.xp_level = snapshot.xp_level ?? null;
  targetState.xp_total = snapshot.xp_total ?? null;
  targetState.selected_item_slot = snapshot.selected_item_slot ?? null;
  targetState.player_x = snapshot.player_x ?? null;
  targetState.player_y = snapshot.player_y ?? null;
  targetState.player_z = snapshot.player_z ?? null;
  targetState.inventory_items = cloneWorldSimpleItems(snapshot.inventory_items);
  targetState.ender_items = cloneWorldSimpleItems(snapshot.ender_items);
  targetState.features = cloneWorldSimpleFeatures(targetState.features);

  const snapshotFeatures = isWorldEditorObject(snapshot.features) ? snapshot.features : {};
  [
    'has_selected_item_slot',
    'has_ender_chest',
    'has_offhand_slot',
    'uses_modern_item_format',
  ].forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(snapshotFeatures, key)) {
      targetState.features[key] = !!snapshotFeatures[key];
    }
  });

  return targetState;
};

const mergeWorldSimpleSnapshots = (baseSimple, globalSnapshot, playerSnapshot) => {
  const nextState = cloneWorldSimpleState(baseSimple);
  applyWorldSimpleGlobalSnapshot(nextState, globalSnapshot);
  applyWorldSimplePlayerSnapshot(nextState, playerSnapshot);
  return nextState;
};

const collectWorldSimpleGlobalState = ({
  baseSimple,
  refs,
}) => {
  const nextState = getWorldSimpleGlobalSnapshot(baseSimple);

  nextState.game_mode = parseWorldEditorIntegerField(refs.gameModeSelect.value, 'Game Mode', {
    min: 0,
    max: 3,
    defaultValue: 0,
    allowEmpty: false,
  });
  nextState.difficulty = parseWorldEditorIntegerField(refs.difficultySelect.value, 'Difficulty', {
    min: 0,
    max: 3,
    defaultValue: 1,
    allowEmpty: false,
  });
  nextState.allow_commands = !!refs.allowCommandsInput.checked;
  nextState.hardcore = !!refs.hardcoreInput.checked;
  nextState.raining = refs.rainingInput ? !!refs.rainingInput.checked : !!baseSimple.raining;
  nextState.thundering = refs.thunderingInput ? !!refs.thunderingInput.checked : !!baseSimple.thundering;
  if (nextState.thundering) nextState.raining = true;
  nextState.day_time = parseWorldEditorIntegerField(refs.dayTimeInput.value, 'Time of Day', {
    defaultValue: baseSimple.day_time ?? 0,
    allowEmpty: false,
  });
  nextState.time = baseSimple.time ?? nextState.day_time ?? 0;
  nextState.rain_time = refs.rainDurationInput
    ? parseWorldEditorIntegerField(refs.rainDurationInput.value, 'Rain Duration', {
        min: 1,
        defaultValue: getWorldEditorWeatherDurationSeconds(baseSimple.rain_time),
        allowEmpty: !nextState.raining,
      }) * WORLD_TICKS_PER_SECOND
    : (baseSimple.rain_time ?? 0);
  nextState.thunder_time = refs.thunderDurationInput
    ? parseWorldEditorIntegerField(refs.thunderDurationInput.value, 'Thunder Duration', {
        min: 1,
        defaultValue: getWorldEditorWeatherDurationSeconds(baseSimple.thunder_time),
        allowEmpty: !nextState.thundering,
      }) * WORLD_TICKS_PER_SECOND
    : (baseSimple.thunder_time ?? 0);
  if (nextState.thundering) {
    nextState.rain_time = Math.max(nextState.rain_time || 0, nextState.thunder_time || 0);
  }
  nextState.clear_weather_time = baseSimple.clear_weather_time ?? 0;
  nextState.spawn_x = parseWorldEditorIntegerField(refs.spawnXInput.value, 'Spawn X', {
    defaultValue: baseSimple.spawn_x ?? 0,
    allowEmpty: false,
  });
  nextState.spawn_y = parseWorldEditorIntegerField(refs.spawnYInput.value, 'Spawn Y', {
    defaultValue: baseSimple.spawn_y ?? 0,
    allowEmpty: false,
  });
  nextState.spawn_z = parseWorldEditorIntegerField(refs.spawnZInput.value, 'Spawn Z', {
    defaultValue: baseSimple.spawn_z ?? 0,
    allowEmpty: false,
  });

  if (Array.isArray(refs.gameRuleInputs) && refs.gameRuleInputs.length > 0) {
    nextState.game_rules = refs.gameRuleInputs.map((ruleRef) => {
      const baseRule = { ...(ruleRef.rule || {}) };
      if (ruleRef.value_type === 'boolean') {
        baseRule.value = !!ruleRef.input.checked;
      } else if (ruleRef.value_type === 'integer') {
        baseRule.value = parseWorldEditorIntegerField(
          ruleRef.input.value,
          ruleRef.rule.label || ruleRef.rule.name || 'Game Rule',
          {
            defaultValue: worldEditorIntValue(ruleRef.rule.value, 0) ?? 0,
            allowEmpty: false,
          }
        );
      } else {
        baseRule.value = String(ruleRef.input.value || '');
      }
      return baseRule;
    });
  }

  return nextState;
};

const collectWorldSimplePlayerState = ({
  baseSimple,
  refs,
}) => {
  const nextState = getWorldSimplePlayerSnapshot(baseSimple);

  nextState.health = parseWorldEditorFloatField(refs.healthInput.value, 'Health', {
    min: 0,
    defaultValue: baseSimple.health,
  });
  nextState.food_level = parseWorldEditorIntegerField(refs.foodLevelInput.value, 'Food Level', {
    min: 0,
    defaultValue: baseSimple.food_level,
  });
  nextState.food_saturation = parseWorldEditorFloatField(refs.foodSaturationInput.value, 'Food Saturation', {
    min: 0,
    defaultValue: baseSimple.food_saturation,
  });
  nextState.xp_level = parseWorldEditorIntegerField(refs.xpLevelInput.value, 'XP Level', {
    min: 0,
    defaultValue: baseSimple.xp_level,
  });
  nextState.xp_total = parseWorldEditorIntegerField(refs.xpTotalInput.value, 'XP Total', {
    min: 0,
    defaultValue: baseSimple.xp_total,
  });

  const selectedHotbarSlot = refs.selectedHotbarControl.getValue();
  nextState.selected_item_slot = selectedHotbarSlot === null
    ? (baseSimple.selected_item_slot ?? null)
    : (selectedHotbarSlot - 1);

  const rawPlayerX = String(refs.playerXInput.value || '').trim();
  const rawPlayerY = String(refs.playerYInput.value || '').trim();
  const rawPlayerZ = String(refs.playerZInput.value || '').trim();
  const hasAnyPlayerPosition = !!(rawPlayerX || rawPlayerY || rawPlayerZ);
  const positionDefaults = {
    x: baseSimple.player_x ?? 0,
    y: baseSimple.player_y ?? 0,
    z: baseSimple.player_z ?? 0,
  };

  nextState.player_x = parseWorldEditorFloatField(rawPlayerX, 'Player X', {
    defaultValue: hasAnyPlayerPosition ? positionDefaults.x : baseSimple.player_x,
  });
  nextState.player_y = parseWorldEditorFloatField(rawPlayerY, 'Player Y', {
    defaultValue: hasAnyPlayerPosition ? positionDefaults.y : baseSimple.player_y,
  });
  nextState.player_z = parseWorldEditorFloatField(rawPlayerZ, 'Player Z', {
    defaultValue: hasAnyPlayerPosition ? positionDefaults.z : baseSimple.player_z,
  });

  nextState.inventory_items = normalizeWorldEditorInventoryItems(refs.inventorySection.getItems(), {
    itemLabel: 'Inventory item',
    minSlot: -128,
    maxSlot: 127,
  });
  nextState.ender_items = refs.enderChestSection
    ? normalizeWorldEditorInventoryItems(refs.enderChestSection.getItems(), {
        itemLabel: 'Ender chest item',
        maxSlot: 26,
      })
    : cloneWorldSimpleItems(baseSimple.ender_items);

  nextState.has_player_data =
    !!baseSimple.has_player_data ||
    nextState.health !== null ||
    nextState.food_level !== null ||
    nextState.food_saturation !== null ||
    nextState.xp_level !== null ||
    nextState.xp_total !== null ||
    nextState.selected_item_slot !== null ||
    nextState.player_x !== null ||
    nextState.player_y !== null ||
    nextState.player_z !== null ||
    nextState.inventory_items.length > 0 ||
    nextState.ender_items.length > 0;

  return nextState;
};

const createWorldEditorPlayerDropdown = (playerMeta, bodyContent) => {
  const dropdown = document.createElement('details');
  dropdown.className = 'world-nbt-player-dropdown';
  if (playerMeta && playerMeta.isPrimary) {
    dropdown.open = true;
  }

  const summary = document.createElement('summary');
  summary.className = 'world-nbt-player-summary';

  const summaryMain = document.createElement('div');
  summaryMain.className = 'world-nbt-player-summary-main';

  const summaryLabel = document.createElement('div');
  summaryLabel.className = 'world-nbt-player-summary-label';
  summaryLabel.textContent = String(playerMeta && playerMeta.label || 'Player');
  summaryMain.appendChild(summaryLabel);

  const summaryMeta = document.createElement('div');
  summaryMeta.className = 'world-nbt-player-summary-meta';
  summaryMeta.textContent = playerMeta && playerMeta.hasSavedData
    ? 'Saved player data'
    : 'Player data will be created when you save';
  summaryMain.appendChild(summaryMeta);
  summary.appendChild(summaryMain);

  const summaryActions = document.createElement('div');
  summaryActions.className = 'world-nbt-player-summary-actions';

  if (playerMeta && playerMeta.isPrimary) {
    const badge = document.createElement('span');
    badge.className = 'world-nbt-player-badge';
    badge.textContent = 'Primary';
    summaryActions.appendChild(badge);
  }

  const indicator = document.createElement('span');
  indicator.className = 'world-nbt-player-summary-indicator';
  indicator.setAttribute('aria-hidden', 'true');
  summaryActions.appendChild(indicator);

  const updateIndicator = () => {
    indicator.textContent = dropdown.open ? unicodeList.dropdown_open : unicodeList.dropdown_close;
  };
  updateIndicator();
  dropdown.addEventListener('toggle', updateIndicator);

  summary.appendChild(summaryActions);
  dropdown.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'world-nbt-player-dropdown-body';
  body.appendChild(bodyContent);
  dropdown.appendChild(body);

  return dropdown;
};

const buildWorldSimplePlayerEditor = (simple, playerMeta = {}) => {
  const content = document.createElement('div');
  content.className = 'world-nbt-player-editor';
  const features = isWorldEditorObject(simple && simple.features) ? simple.features : {};
  const playerName = String(playerMeta && playerMeta.label || 'Player').trim() || 'Player';

  const playerIntro = document.createElement('p');
  playerIntro.className = 'world-nbt-section-note';
  if (simple.has_player_data) {
    playerIntro.textContent = `These settings only affect ${playerName}.`;
  } else {
    playerIntro.textContent = `${playerName} does not have saved player data in this world yet. Any fields you set here will be created when you save.`;
  }
  content.appendChild(playerIntro);

  const playerSection = createWorldEditorSection('Player Stats', 'Health, hunger, experience, and the selected hotbar slot are all saved per player.');
  const healthInput = createWorldEditorNumberInput(simple.health ?? '', { step: '0.5', min: 0 });
  const foodLevelInput = createWorldEditorNumberInput(simple.food_level ?? '', { min: 0 });
  const foodSaturationInput = createWorldEditorNumberInput(simple.food_saturation ?? '', { step: '0.5', min: 0 });
  const xpLevelInput = createWorldEditorNumberInput(simple.xp_level ?? '', { min: 0 });
  const xpTotalInput = createWorldEditorNumberInput(simple.xp_total ?? '', { min: 0 });
  const selectedHotbarControl = createWorldEditorHotbarSelector(simple.selected_item_slot ?? null);
  [
    createWorldEditorField('Health', healthInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.health, hintText: '20 is full health' }),
    createWorldEditorField('Food Level', foodLevelInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.foodLevel, hintText: '20 is a full hunger bar' }),
    createWorldEditorField('Food Saturation', foodSaturationInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.foodSaturation }),
    createWorldEditorField('XP Level', xpLevelInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.xpLevel }),
    createWorldEditorField('XP Total', xpTotalInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.xpTotal }),
    createWorldEditorField('Selected Hotbar Slot', selectedHotbarControl.element, {
      tooltipText: WORLD_SIMPLE_TOOLTIPS.hotbarSlot,
      hintText: 'Shown as 1 through 9, just like the in-game hotbar.',
    }),
  ].forEach((field) => playerSection.body.appendChild(field));
  content.appendChild(playerSection.section);

  const playerPositionSection = createWorldEditorSection('Player Position', 'This is where this player appears when they join the world.');
  const playerXInput = createWorldEditorNumberInput(simple.player_x ?? '', { step: '0.1' });
  const playerYInput = createWorldEditorNumberInput(simple.player_y ?? '', { step: '0.1' });
  const playerZInput = createWorldEditorNumberInput(simple.player_z ?? '', { step: '0.1' });
  [
    createWorldEditorField('X', playerXInput, {
      tooltipText: WORLD_SIMPLE_TOOLTIPS.playerX,
      hintText: 'Decimals are allowed',
    }),
    createWorldEditorField('Y', playerYInput, {
      tooltipText: WORLD_SIMPLE_TOOLTIPS.playerY,
      hintText: 'Decimals are allowed',
    }),
    createWorldEditorField('Z', playerZInput, {
      tooltipText: WORLD_SIMPLE_TOOLTIPS.playerZ,
      hintText: 'Decimals are allowed',
    }),
  ].forEach((field) => playerPositionSection.body.appendChild(field));
  content.appendChild(playerPositionSection.section);

  const inventorySection = createWorldEditorInventorySection({
    title: 'Inventory Layout',
    description: 'Use the slot picker if you want a visual hotbar, inventory, armor, and offhand layout, or type a different slot number manually when you need something more advanced.',
    items: simple.inventory_items,
    addButtonLabel: 'Add Inventory Item',
    slotPlaceholder: 'Slot',
    itemPlaceholder: 'minecraft:stone',
    slotTooltip: WORLD_SIMPLE_TOOLTIPS.inventorySlot,
    itemTooltip: WORLD_SIMPLE_TOOLTIPS.inventoryItem,
    countTooltip: WORLD_SIMPLE_TOOLTIPS.inventoryCount,
    slotMax: 255,
    createSlotControl: (value) => createWorldEditorSlotPickerInput({
      value,
      min: -128,
      max: 127,
      placeholder: 'Slot',
      pickerType: 'player-inventory',
      showOffhandSlot: !!features.has_offhand_slot,
    }),
  });
  content.appendChild(inventorySection.section);

  let enderChestSection = null;
  if (features.has_ender_chest) {
    enderChestSection = createWorldEditorInventorySection({
      title: 'Ender Chest',
      description: 'This is the personal storage this player can open from any ender chest, and the picker shows the same 9x3 layout Minecraft uses.',
      items: simple.ender_items,
      addButtonLabel: 'Add Ender Chest Item',
      slotPlaceholder: '0-26',
      itemPlaceholder: 'minecraft:diamond_block',
      slotTooltip: WORLD_SIMPLE_TOOLTIPS.enderSlot,
      itemTooltip: WORLD_SIMPLE_TOOLTIPS.enderItem,
      countTooltip: WORLD_SIMPLE_TOOLTIPS.enderCount,
      slotMax: 26,
      createSlotControl: (value) => createWorldEditorSlotPickerInput({
        value,
        min: 0,
        max: 26,
        placeholder: '0-26',
        pickerType: 'ender-chest',
      }),
    });
    content.appendChild(enderChestSection.section);
  }

  return {
    content,
    getState: () => collectWorldSimplePlayerState({
      baseSimple: simple,
      refs: {
        healthInput,
        foodLevelInput,
        foodSaturationInput,
        xpLevelInput,
        xpTotalInput,
        selectedHotbarControl,
        playerXInput,
        playerYInput,
        playerZInput,
        inventorySection,
        enderChestSection,
      },
    }),
  };
};

const buildWorldSimpleEditorView = (simple, detail) => {
  const content = document.createElement('div');
  content.className = 'world-nbt-editor';
  const features = isWorldEditorObject(simple && simple.features) ? simple.features : {};
  const rawPlayerEntries = Array.isArray(detail && detail.player_entries) && detail.player_entries.length > 0
    ? detail.player_entries
    : [{
        player_id: String(detail && detail.selected_player_id || ''),
        label: 'Primary Player',
        isPrimary: true,
        simple,
      }];
  const playerEditors = [];

  const gameSection = createWorldEditorSection('World Rules', `Editing ${detail.title || detail.world_id || 'this world'}`);
  const gameModeSelect = createWorldEditorSelect([
    { value: 0, label: 'Survival' },
    { value: 1, label: 'Creative' },
    { value: 2, label: 'Adventure' },
    { value: 3, label: 'Spectator' },
  ], simple.game_mode ?? 0);
  const difficultySelect = createWorldEditorSelect([
    { value: 0, label: 'Peaceful' },
    { value: 1, label: 'Easy' },
    { value: 2, label: 'Normal' },
    { value: 3, label: 'Hard' },
  ], simple.difficulty ?? 1);
  const allowCommandsInput = document.createElement('input');
  allowCommandsInput.type = 'checkbox';
  allowCommandsInput.checked = !!simple.allow_commands;
  const hardcoreInput = document.createElement('input');
  hardcoreInput.type = 'checkbox';
  hardcoreInput.checked = !!simple.hardcore;
  [
    createWorldEditorField('Game Mode', gameModeSelect, { tooltipText: WORLD_SIMPLE_TOOLTIPS.gameMode }),
    createWorldEditorField('Difficulty', difficultySelect, { tooltipText: WORLD_SIMPLE_TOOLTIPS.difficulty }),
    createWorldEditorCheckboxField('Allow Commands', allowCommandsInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.allowCommands }),
    createWorldEditorCheckboxField('Hardcore', hardcoreInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.hardcore }),
  ].forEach((field) => gameSection.body.appendChild(field));
  content.appendChild(gameSection.section);

  const spawnSection = createWorldEditorSection('Spawn Position', 'This is the place players return to when the world uses the default spawn point.');
  const spawnXInput = createWorldEditorNumberInput(simple.spawn_x ?? 0);
  const spawnYInput = createWorldEditorNumberInput(simple.spawn_y ?? 0);
  const spawnZInput = createWorldEditorNumberInput(simple.spawn_z ?? 0);
  [
    createWorldEditorField('X', spawnXInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.spawnX }),
    createWorldEditorField('Y', spawnYInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.spawnY }),
    createWorldEditorField('Z', spawnZInput, { tooltipText: WORLD_SIMPLE_TOOLTIPS.spawnZ }),
  ].forEach((field) => spawnSection.body.appendChild(field));
  content.appendChild(spawnSection.section);

  const timeSection = createWorldEditorSection('Time & Weather', 'Use this when you want the world to open at a certain time or weather state.');
  const dayTimeInput = createWorldEditorNumberInput(simple.day_time ?? 0);
  const rainingInput = features.has_raining ? document.createElement('input') : null;
  if (rainingInput) {
    rainingInput.type = 'checkbox';
    rainingInput.checked = !!simple.raining;
  }
  const rainDurationInput = features.has_rain_time
    ? createWorldEditorNumberInput(getWorldEditorWeatherDurationSeconds(simple.rain_time), { min: 1 })
    : null;
  const rainDurationAccessory = rainDurationInput
    ? createWorldEditorWeatherDurationAccessory(rainDurationInput, WORLD_SIMPLE_TOOLTIPS.rainDuration)
    : null;
  const thunderingInput = features.has_thundering ? document.createElement('input') : null;
  if (thunderingInput) {
    thunderingInput.type = 'checkbox';
    thunderingInput.checked = !!simple.thundering;
  }
  const thunderDurationInput = features.has_thunder_time
    ? createWorldEditorNumberInput(getWorldEditorWeatherDurationSeconds(simple.thunder_time), { min: 1 })
    : null;
  const thunderDurationAccessory = thunderDurationInput
    ? createWorldEditorWeatherDurationAccessory(thunderDurationInput, WORLD_SIMPLE_TOOLTIPS.thunderDuration)
    : null;
  const timeFields = [
    createWorldEditorField('Time of Day', dayTimeInput, {
      tooltipText: WORLD_SIMPLE_TOOLTIPS.timeOfDay,
      hintText: '0 sunrise | 6000 noon | 12000 sunset | 18000 midnight',
    }),
  ];
  if (rainingInput) {
    timeFields.push(createWorldEditorCheckboxField('Raining', rainingInput, {
      tooltipText: WORLD_SIMPLE_TOOLTIPS.raining,
      accessoryEl: rainDurationAccessory,
    }));
  }
  if (thunderingInput) {
    timeFields.push(createWorldEditorCheckboxField('Thundering', thunderingInput, {
      tooltipText: WORLD_SIMPLE_TOOLTIPS.thundering,
      accessoryEl: thunderDurationAccessory,
    }));
  }
  timeFields.forEach((field) => timeSection.body.appendChild(field));
  content.appendChild(timeSection.section);

  const updateWeatherDurationVisibility = () => {
    if (rainDurationAccessory && rainingInput) {
      rainDurationAccessory.classList.toggle('hidden', !rainingInput.checked);
    }
    if (thunderDurationAccessory && thunderingInput) {
      thunderDurationAccessory.classList.toggle('hidden', !thunderingInput.checked);
    }
  };

  if (rainingInput && thunderingInput) {
    thunderingInput.addEventListener('change', () => {
      if (thunderingInput.checked) {
        rainingInput.checked = true;
      }
      updateWeatherDurationVisibility();
    });
    rainingInput.addEventListener('change', () => {
      if (!rainingInput.checked) {
        thunderingInput.checked = false;
      }
      updateWeatherDurationVisibility();
    });
  } else {
    if (rainingInput) {
      rainingInput.addEventListener('change', updateWeatherDurationVisibility);
    }
    if (thunderingInput) {
      thunderingInput.addEventListener('change', updateWeatherDurationVisibility);
    }
  }
  updateWeatherDurationVisibility();

  const playersSection = createWorldEditorSection(
    'Player Data',
    'Each player keeps their own position, health, inventory, and other personal values. Open a player below to edit their saved data.'
  );
  const playersList = document.createElement('div');
  playersList.className = 'world-nbt-player-list';

  rawPlayerEntries.forEach((playerEntry, index) => {
    const playerSimple = isWorldEditorObject(playerEntry && playerEntry.simple)
      ? playerEntry.simple
      : simple;
    const normalizedEntry = {
      playerId: String(playerEntry && (playerEntry.playerId ?? playerEntry.player_id) || '').trim(),
      label: String(playerEntry && playerEntry.label || playerEntry && playerEntry.uuid || `Player ${index + 1}`),
      isPrimary: !!(playerEntry && (playerEntry.isPrimary || playerEntry.is_primary)),
      simple: cloneWorldSimpleState(playerSimple),
    };
    const playerView = buildWorldSimplePlayerEditor(normalizedEntry.simple, normalizedEntry);
    playerEditors.push({
      playerId: normalizedEntry.playerId,
      label: normalizedEntry.label,
      isPrimary: normalizedEntry.isPrimary,
      getState: playerView.getState,
    });
    playersList.appendChild(createWorldEditorPlayerDropdown({
      label: normalizedEntry.label,
      isPrimary: normalizedEntry.isPrimary,
      hasSavedData: !!normalizedEntry.simple.has_player_data,
    }, playerView.content));
  });

  playersSection.body.appendChild(playersList);
  content.appendChild(playersSection.section);

  const gameRuleInputs = [];
  if (features.has_gamerules && Array.isArray(simple.game_rules) && simple.game_rules.length > 0) {
    const gameRulesSection = createWorldEditorSection(
      'Game Rules',
      'Use these settings to affect the rules and mechanics of the world, like whether fire spreads or how mobs spawn.'
    );

    simple.game_rules.forEach((rule) => {
      const tooltipText = createWorldGameRuleTooltipText(rule);
      if (rule.value_type === 'boolean') {
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = !!rule.value;
        gameRuleInputs.push({ rule, input: checkbox, value_type: 'boolean' });
        gameRulesSection.body.appendChild(createWorldEditorCheckboxField(rule.label, checkbox, {
          tooltipText,
        }));
        return;
      }

      if (rule.value_type === 'integer') {
        const input = createWorldEditorNumberInput(rule.value ?? 0);
        gameRuleInputs.push({ rule, input, value_type: 'integer' });
        gameRulesSection.body.appendChild(createWorldEditorField(rule.label, input, {
          tooltipText,
          hintText: rule.name,
        }));
        return;
      }

      const input = createWorldEditorTextInput(rule.value ?? '');
      gameRuleInputs.push({ rule, input, value_type: 'text' });
      gameRulesSection.body.appendChild(createWorldEditorField(rule.label, input, {
        tooltipText,
        hintText: rule.name,
      }));
    });

    content.appendChild(gameRulesSection.section);
  }

  return {
    content,
    getState: () => ({
      global: collectWorldSimpleGlobalState({
        baseSimple: simple,
        refs: {
          gameModeSelect,
          difficultySelect,
          allowCommandsInput,
          hardcoreInput,
          dayTimeInput,
          rainingInput,
          thunderingInput,
          rainDurationInput,
          thunderDurationInput,
          spawnXInput,
          spawnYInput,
          spawnZInput,
          gameRuleInputs,
        },
      }),
      players: playerEditors.map((playerEditor) => ({
        player_id: playerEditor.playerId,
        label: playerEditor.label,
        is_primary: playerEditor.isPrimary,
        simple: playerEditor.getState(),
      })),
    }),
  };
};

const buildWorldAdvancedEditorView = (advancedText, options = {}) => {
  const onSubModeChange = typeof options.onSubModeChange === 'function'
    ? options.onSubModeChange
    : null;

  const content = document.createElement('div');
  content.className = 'world-nbt-editor world-nbt-advanced-editor';

  const subTabs = document.createElement('div');
  subTabs.className = 'world-nbt-tabs world-nbt-subtabs';
  const treeBtn = document.createElement('button');
  treeBtn.type = 'button';
  treeBtn.className = 'world-nbt-tab active';
  treeBtn.textContent = 'Tree';
  const rawBtn = document.createElement('button');
  rawBtn.type = 'button';
  rawBtn.className = 'world-nbt-tab';
  rawBtn.textContent = 'Raw JSON';
  subTabs.appendChild(treeBtn);
  subTabs.appendChild(rawBtn);
  content.appendChild(subTabs);

  const subPanel = document.createElement('div');
  subPanel.className = 'world-nbt-subtab-panel';
  content.appendChild(subPanel);

  let activeSubMode = 'tree';
  let currentRoot = null;
  let textarea = null;
  let treeView = null;

  try {
    currentRoot = parseWorldEditorAdvancedRoot(String(advancedText || '').trim() || '{}');
  } catch (_e) {
    try {
      currentRoot = JSON.parse(String(advancedText || '').trim() || '{}');
    } catch (_e2) {
      currentRoot = { type: WORLD_NBT_TAGS.COMPOUND, name: '', value: {} };
    }
  }

  const renderTree = () => {
    while (subPanel.firstChild) subPanel.removeChild(subPanel.firstChild);
    treeView = buildWorldNbtTreeEditor(currentRoot);
    textarea = null;
    subPanel.appendChild(treeView.element);
  };

  const renderRaw = () => {
    while (subPanel.firstChild) subPanel.removeChild(subPanel.firstChild);
    textarea = document.createElement('textarea');
    textarea.className = 'world-nbt-json-textarea';
    textarea.spellcheck = false;
    textarea.value = formatWorldEditorAdvancedRoot(currentRoot);
    treeView = null;
    subPanel.appendChild(textarea);
  };

  const captureCurrentRoot = () => {
    if (activeSubMode === 'raw' && textarea) {
      currentRoot = parseWorldEditorAdvancedRoot(textarea.value);
    } else if (activeSubMode === 'tree' && treeView) {
      currentRoot = treeView.getRoot();
    }
    return currentRoot;
  };

  const switchSub = (next) => {
    if (next === activeSubMode) return;
    try {
      captureCurrentRoot();
    } catch (err) {
      // Block switch when current view has invalid contents.
      const message = (err && err.message) || String(err);
      const previewBtn = next === 'tree' ? treeBtn : rawBtn;
      previewBtn.classList.remove('active');
      const targetBtn = activeSubMode === 'tree' ? treeBtn : rawBtn;
      targetBtn.classList.add('active');
      throw err instanceof Error ? err : new Error(String(message));
    }
    activeSubMode = next;
    treeBtn.classList.toggle('active', next === 'tree');
    rawBtn.classList.toggle('active', next === 'raw');
    if (next === 'tree') renderTree();
    else renderRaw();
    if (onSubModeChange) {
      try { onSubModeChange(next); } catch (_e) { /* ignore */ }
    }
  };

  treeBtn.addEventListener('click', () => {
    try { switchSub('tree'); } catch (_e) { /* surfaced via thrown error from caller-installed handler not available here */ }
  });
  rawBtn.addEventListener('click', () => {
    try { switchSub('raw'); } catch (_e) { /* see above */ }
  });

  renderTree();

  const view = {
    content,
    get textarea() { return textarea; },
    get treeView() { return treeView; },
    getActiveSubMode: () => activeSubMode,
    getCurrentRoot: () => captureCurrentRoot(),
    setRoot: (root) => {
      currentRoot = root;
      if (activeSubMode === 'tree') renderTree();
      else if (activeSubMode === 'raw' && textarea) {
        textarea.value = formatWorldEditorAdvancedRoot(root);
      }
    },
  };

  return view;
};

const openWorldNbtEditor = async (world, initialTab = 'simple', options = {}) => {
  const loading = createWorldEditorLoadingContent('Loading world editor...');
  const controls = showMessageBox({
    title: `Edit World: ${world.title || world.world_id || 'World'}`,
    customContent: loading,
    boxClassList: ['world-nbt-dialog'],
    buttons: [{ label: 'Close' }],
  });

  try {
    const result = await api('/api/worlds/nbt', 'POST', {
      storage_target: worldsState.storageTarget,
      custom_path: worldsState.customPath,
      world_id: world.world_id,
      player_id: '',
    });

    if (!result || !result.ok) {
      loading.innerHTML = `<p style="color:#ff4141;">${(result && result.error) || 'Failed to load world NBT data.'}</p>`;
      return;
    }

    const detail = result.detail || world;
    const parsedRoot = parseWorldEditorAdvancedRoot(result.advanced_json || '{}');
    const initialSimple = extractWorldSimpleStateFromRoot(parsedRoot);
    const availablePlayers = Array.isArray(result.players) ? result.players : [];
    const selectedPlayerId = String(result.selected_player_id || '').trim();
    const normalizedPlayers = availablePlayers.length > 0
      ? availablePlayers.map((entry, index) => ({
          player_id: String(entry && entry.player_id || '').trim(),
          label: String(entry && entry.label || entry && entry.uuid || `Player ${index + 1}`),
          uuid: String(entry && entry.uuid || '').trim(),
          is_primary: String(entry && entry.player_id || '').trim() === selectedPlayerId,
        }))
      : [{
          player_id: selectedPlayerId,
          label: 'Primary Player',
          uuid: '',
          is_primary: true,
        }];
    if (!normalizedPlayers.some((entry) => entry.is_primary) && normalizedPlayers[0]) {
      normalizedPlayers[0].is_primary = true;
    }

    const playerRecords = await Promise.all(normalizedPlayers.map(async (entry, index) => {
      const shouldUsePrimaryResult = !!entry.is_primary || (!selectedPlayerId && index === 0);
      const playerResult = shouldUsePrimaryResult
        ? result
        : await api('/api/worlds/nbt', 'POST', {
            storage_target: worldsState.storageTarget,
            custom_path: worldsState.customPath,
            world_id: world.world_id,
            player_id: entry.player_id,
          });

      if (!playerResult || !playerResult.ok) {
        throw new Error((playerResult && playerResult.error) || `Failed to load data for ${entry.label}.`);
      }

      const playerRoot = parseWorldEditorAdvancedRoot(playerResult.advanced_json || '{}');
      const playerSimple = extractWorldSimpleStateFromRoot(playerRoot);
      return {
        playerId: entry.player_id,
        label: entry.label,
        uuid: entry.uuid,
        isPrimary: !!entry.is_primary,
        root: playerRoot,
        simple: playerSimple,
        advancedText: formatWorldEditorAdvancedRoot(playerRoot),
      };
    }));
    const primaryPlayerRecord = playerRecords.find((entry) => entry.isPrimary) || playerRecords[0] || {
      playerId: '',
      label: 'Primary Player',
      uuid: '',
      isPrimary: true,
      root: parsedRoot,
      simple: initialSimple,
      advancedText: formatWorldEditorAdvancedRoot(parsedRoot),
    };
    const content = document.createElement('div');
    content.className = 'world-nbt-editor world-nbt-editor-shell';

    const lead = document.createElement('p');
    lead.className = 'world-nbt-section-note';
    content.appendChild(lead);

    const status = document.createElement('div');
    status.className = 'world-nbt-status hidden';
    content.appendChild(status);

    const identitySection = createWorldEditorSection(
      'World Identity',
      'Rename the world here or change the world icon.'
    );
    let pendingWorldIconBase64 = null;
    const titleInput = createWorldEditorTextInput(detail.title || primaryPlayerRecord.simple.world_title || world.title || world.world_id || '');
    const worldIdInput = createWorldEditorTextInput(detail.world_id || world.world_id || '');
    identitySection.body.appendChild(createWorldEditorField('World Title', titleInput, {
      hintText: 'This is the name players see inside Minecraft.',
    }));
    identitySection.body.appendChild(createWorldEditorField('World ID', worldIdInput, {
      hintText: 'This is the folder name on disk.',
    }));
    const iconPicker = document.createElement('div');
    iconPicker.className = 'world-icon-replacer';
    const iconPreview = document.createElement('img');
    iconPreview.className = 'world-icon-replacer-preview';
    iconPreview.alt = 'World icon preview';
    iconPreview.src = detail.icon_url || world.icon_url || 'assets/images/placeholder_pack.png';
    imageAttachErrorPlaceholder(iconPreview, 'assets/images/placeholder_pack.png');

    const iconActions = document.createElement('div');
    iconActions.className = 'world-icon-replacer-actions';
    const iconInput = document.createElement('input');
    iconInput.type = 'file';
    iconInput.accept = 'image/png';
    iconInput.style.display = 'none';
    const iconButton = document.createElement('button');
    iconButton.type = 'button';
    iconButton.textContent = 'Choose PNG';
    const iconFileLabel = document.createElement('span');
    iconFileLabel.className = 'world-icon-replacer-file';
    iconFileLabel.textContent = detail.has_icon || world.has_icon ? 'Current world icon' : 'No custom icon';
    iconButton.addEventListener('click', () => iconInput.click());
    iconInput.addEventListener('change', async () => {
      const file = iconInput.files && iconInput.files[0];
      if (!file) return;
      const fileName = String(file.name || '');
      const lowerFileName = fileName.toLowerCase();
      if ((file.type && file.type !== 'image/png') || (!file.type && !lowerFileName.endsWith('.png'))) {
        setWorldEditorStatus(status, 'World icon must be a PNG file.', 'error');
        iconInput.value = '';
        return;
      }
      try {
        const dataUrl = await normalizeWorldIconFileToDataUrl(file);
        const comma = dataUrl.indexOf(',');
        if (!dataUrl.startsWith('data:image/png') || comma < 0) {
          setWorldEditorStatus(status, 'World icon must be a PNG file.', 'error');
          return;
        }
        pendingWorldIconBase64 = dataUrl.slice(comma + 1);
        iconPreview.src = dataUrl;
        iconFileLabel.textContent = fileName ? `${fileName} (64x64)` : 'Selected PNG (64x64)';
        setWorldEditorStatus(status, 'World icon will be replaced when you save.', 'info');
      } catch (err) {
        setWorldEditorStatus(status, err.message || String(err), 'error');
        iconInput.value = '';
      }
    });
    iconActions.appendChild(iconButton);
    iconActions.appendChild(iconFileLabel);
    iconActions.appendChild(iconInput);
    iconPicker.appendChild(iconPreview);
    iconPicker.appendChild(iconActions);
    identitySection.body.appendChild(createWorldEditorField('World Icon', iconPicker, {
      hintText: 'Select a PNG to replace icon.png for the Minecraft world list.',
    }));
    content.appendChild(identitySection.section);

    const tabs = document.createElement('div');
    tabs.className = 'world-nbt-tabs';
    const simpleTabButton = document.createElement('button');
    simpleTabButton.type = 'button';
    simpleTabButton.className = 'world-nbt-tab';
    simpleTabButton.textContent = 'Simple';
    const advancedTabButton = document.createElement('button');
    advancedTabButton.type = 'button';
    advancedTabButton.className = 'world-nbt-tab';
    advancedTabButton.textContent = 'Advanced';
    tabs.appendChild(simpleTabButton);
    tabs.appendChild(advancedTabButton);
    content.appendChild(tabs);

    const tabPanel = document.createElement('div');
    tabPanel.className = 'world-nbt-tab-panel';
    content.appendChild(tabPanel);

    const editorState = {
      activeTab: initialTab === 'advanced' ? 'advanced' : 'simple',
      currentWorldId: detail.world_id || world.world_id || '',
      detail,
      players: normalizedPlayers,
      playerRecords,
      primaryPlayerId: primaryPlayerRecord.playerId,
      nbtRoot: primaryPlayerRecord.root,
      simple: cloneWorldSimpleState(primaryPlayerRecord.simple),
      advancedText: primaryPlayerRecord.advancedText,
      simpleView: null,
      advancedView: null,
      syncedTitle: String(titleInput.value || primaryPlayerRecord.simple.world_title || '').trim(),
    };

    const updateLead = () => {
      lead.textContent = editorState.activeTab === 'advanced'
        ? 'Advanced mode edits the full world data view as JSON for the world and the primary player. The other player dropdowns keep their own edits when you switch tabs.'
        : 'Simple mode groups the common edits by category, adds beginner-friendly help text, and lets every saved player keep their own dropdown for separate editing.';
    };

    const refreshTabButtons = () => {
      simpleTabButton.classList.toggle('active', editorState.activeTab === 'simple');
      advancedTabButton.classList.toggle('active', editorState.activeTab === 'advanced');
    };

    const getPrimaryPlayerRecord = () => editorState.playerRecords.find((entry) => entry.isPrimary) || editorState.playerRecords[0] || null;

    const updatePrimaryRecordFromRoot = (rootToUse) => {
      const primaryRecord = getPrimaryPlayerRecord();
      const parsedSimple = extractWorldSimpleStateFromRoot(rootToUse);
      const advancedText = formatWorldEditorAdvancedRoot(rootToUse);

      if (primaryRecord) {
        primaryRecord.root = rootToUse;
        primaryRecord.simple = cloneWorldSimpleState(parsedSimple);
        primaryRecord.advancedText = advancedText;
      }

      editorState.nbtRoot = rootToUse;
      editorState.simple = cloneWorldSimpleState(parsedSimple);
      editorState.advancedText = advancedText;
    };

    const syncSharedWorldStateAcrossPlayers = (worldTitle = '') => {
      const primaryRecord = getPrimaryPlayerRecord();
      if (!primaryRecord) return;

      const globalSnapshot = getWorldSimpleGlobalSnapshot(primaryRecord.simple);
      editorState.playerRecords.forEach((record) => {
        if (!record || record.isPrimary) return;
        const mergedSimple = mergeWorldSimpleSnapshots(
          record.simple,
          globalSnapshot,
          getWorldSimplePlayerSnapshot(record.simple)
        );
        applyWorldSimpleStateToRoot(record.root, mergedSimple, worldTitle || titleInput.value);
        record.simple = cloneWorldSimpleState(extractWorldSimpleStateFromRoot(record.root));
        record.advancedText = formatWorldEditorAdvancedRoot(record.root);
      });

      editorState.simple = cloneWorldSimpleState(primaryRecord.simple);
      editorState.advancedText = primaryRecord.advancedText;
    };

    const reconcileTitleInputWithRoot = (rootToUse) => {
      const parsedSimple = extractWorldSimpleStateFromRoot(rootToUse);
      const parsedTitle = String(parsedSimple.world_title || '').trim();
      const typedTitle = String(titleInput.value || '').trim();

      if (!typedTitle || typedTitle === editorState.syncedTitle) {
        if (parsedTitle) titleInput.value = parsedTitle;
      } else {
        applyWorldEditorTitleToRoot(rootToUse, typedTitle);
      }

      updatePrimaryRecordFromRoot(rootToUse);
      editorState.syncedTitle = String(titleInput.value || parsedTitle || editorState.syncedTitle || '').trim();
    };

    const syncFromSimpleTab = () => {
      if (!editorState.simpleView || typeof editorState.simpleView.getState !== 'function') return true;
      try {
        const nextSimpleBundle = editorState.simpleView.getState();
        const globalSnapshot = isWorldEditorObject(nextSimpleBundle && nextSimpleBundle.global)
          ? nextSimpleBundle.global
          : getWorldSimpleGlobalSnapshot(editorState.simple);
        const playerSnapshots = new Map(
          (Array.isArray(nextSimpleBundle && nextSimpleBundle.players) ? nextSimpleBundle.players : [])
            .map((entry) => [String(entry && entry.player_id || '').trim(), entry && entry.simple])
        );

        editorState.playerRecords.forEach((record) => {
          const playerSnapshot = isWorldEditorObject(playerSnapshots.get(record.playerId))
            ? playerSnapshots.get(record.playerId)
            : getWorldSimplePlayerSnapshot(record.simple);
          const mergedSimple = mergeWorldSimpleSnapshots(record.simple, globalSnapshot, playerSnapshot);
          applyWorldSimpleStateToRoot(record.root, mergedSimple, titleInput.value);
          record.simple = cloneWorldSimpleState(extractWorldSimpleStateFromRoot(record.root));
          record.advancedText = formatWorldEditorAdvancedRoot(record.root);
        });

        const primaryRecord = getPrimaryPlayerRecord();
        if (primaryRecord) {
          updatePrimaryRecordFromRoot(primaryRecord.root);
        }

        if (!String(titleInput.value || '').trim() && editorState.simple.world_title) {
          titleInput.value = editorState.simple.world_title;
        }
        editorState.syncedTitle = String(titleInput.value || editorState.simple.world_title || '').trim();
        return true;
      } catch (err) {
        setWorldEditorStatus(status, err.message || String(err), 'error');
        return false;
      }
    };

    const syncFromAdvancedTab = () => {
      if (!editorState.advancedView) return true;
      try {
        const nextRoot = editorState.advancedView.getCurrentRoot();
        const reparsed = parseWorldEditorAdvancedRoot(formatWorldEditorAdvancedRoot(nextRoot));
        reconcileTitleInputWithRoot(reparsed);
        editorState.advancedView.setRoot(reparsed);
        syncSharedWorldStateAcrossPlayers(titleInput.value);
        return true;
      } catch (err) {
        setWorldEditorStatus(status, err.message || String(err), 'error');
        return false;
      }
    };

    const syncFromCurrentTab = () => (
      editorState.activeTab === 'advanced'
        ? syncFromAdvancedTab()
        : syncFromSimpleTab()
    );

    const renderActiveTab = () => {
      updateLead();
      refreshTabButtons();
      tabPanel.innerHTML = '';
      editorState.simpleView = null;
      editorState.advancedView = null;

      if (editorState.activeTab === 'advanced') {
        const advancedView = buildWorldAdvancedEditorView(editorState.advancedText, {
          onSubModeChange: () => {
            try { rebuildModalButtons(); } catch (_e) { /* ignore */ }
          },
        });
        editorState.advancedView = advancedView;
        tabPanel.appendChild(advancedView.content);
      } else {
        const simpleView = buildWorldSimpleEditorView(editorState.simple, {
          ...editorState.detail,
          selected_player_id: editorState.primaryPlayerId,
          player_entries: editorState.playerRecords.map((record) => ({
            player_id: record.playerId,
            label: record.label,
            is_primary: record.isPrimary,
            simple: record.simple,
          })),
        });
        editorState.simpleView = simpleView;
        tabPanel.appendChild(simpleView.content);
      }

      initTooltips();
      try { rebuildModalButtons(); } catch (_e) { /* controls not yet ready */ }
    };

    const switchTab = (nextTab) => {
      if (editorState.activeTab === nextTab) return;
      if (!syncFromCurrentTab()) return;
      editorState.activeTab = nextTab;
      setWorldEditorStatus(status, '');
      renderActiveTab();
    };

    simpleTabButton.addEventListener('click', () => switchTab('simple'));
    advancedTabButton.addEventListener('click', () => switchTab('advanced'));

    let saving = false;

    const buildModalButtons = () => {
      const buttons = [];
      const isAdvancedRaw = editorState.activeTab === 'advanced'
        && editorState.advancedView
        && typeof editorState.advancedView.getActiveSubMode === 'function'
        && editorState.advancedView.getActiveSubMode() === 'raw';

      if (isAdvancedRaw) {
        buttons.push({
          label: 'Format JSON',
          classList: ['mild'],
          closeOnClick: false,
          onClick: () => {
            const advancedView = editorState.advancedView;
            if (!advancedView || !advancedView.textarea) return;
            try {
              const parsed = parseWorldEditorAdvancedRoot(advancedView.textarea.value);
              reconcileTitleInputWithRoot(parsed);
              advancedView.setRoot(parsed);
              setWorldEditorStatus(status, 'Advanced JSON formatted successfully.', 'info');
            } catch (err) {
              setWorldEditorStatus(status, err.message || String(err), 'error');
            }
          },
        });
      }

      buttons.push({
        label: 'Save',
        classList: ['primary'],
        closeOnClick: false,
        onClick: async (_values, modalControls) => {
            if (saving) return;
            if (!syncFromCurrentTab()) return;

            saving = true;
            setWorldEditorStatus(status, 'Saving world editor changes...', 'info');

            const requestedTitle = String(titleInput.value || '').trim()
              || String(editorState.simple.world_title || '').trim()
              || String(editorState.detail.title || editorState.currentWorldId || '').trim();
            const requestedWorldId = String(worldIdInput.value || '').trim() || editorState.currentWorldId;

            applyWorldEditorTitleToRoot(editorState.nbtRoot, requestedTitle);
            updatePrimaryRecordFromRoot(editorState.nbtRoot);
            syncSharedWorldStateAcrossPlayers(requestedTitle);

            try {
              const saveOrder = [...editorState.playerRecords].sort((left, right) => {
                if (!!left.isPrimary === !!right.isPrimary) return 0;
                return left.isPrimary ? 1 : -1;
              });

              for (const record of saveOrder) {
                const saveResult = await api('/api/worlds/nbt/advanced-update', 'POST', {
                  storage_target: worldsState.storageTarget,
                  custom_path: worldsState.customPath,
                  world_id: editorState.currentWorldId,
                  player_id: record.playerId,
                  nbt_json: record.isPrimary ? editorState.advancedText : formatWorldEditorAdvancedRoot(record.root),
                });
                if (!saveResult || !saveResult.ok) {
                  const label = record.label ? `${record.label}: ` : '';
                  setWorldEditorStatus(status, `${label}${(saveResult && saveResult.error) || 'Failed to save world NBT data.'}`, 'error');
                  return;
                }
              }

              let finalWorldId = editorState.currentWorldId;
              if (requestedWorldId !== editorState.currentWorldId) {
                const renameResult = await api('/api/worlds/update', 'POST', {
                  storage_target: worldsState.storageTarget,
                  custom_path: worldsState.customPath,
                  world_id: editorState.currentWorldId,
                  new_world_id: requestedWorldId,
                });
                if (!renameResult || !renameResult.ok) {
                  setWorldEditorStatus(
                    status,
                    `NBT changes were saved, but the world folder rename failed: ${(renameResult && renameResult.error) || 'Unknown error.'}`,
                    'error'
                  );
                  return;
                }
                finalWorldId = renameResult.world_id || requestedWorldId;
                editorState.currentWorldId = finalWorldId;
              }

              if (pendingWorldIconBase64) {
                const iconResult = await api('/api/worlds/icon-update', 'POST', {
                  storage_target: worldsState.storageTarget,
                  custom_path: worldsState.customPath,
                  world_id: finalWorldId,
                  image_data: pendingWorldIconBase64,
                });
                if (!iconResult || !iconResult.ok) {
                  setWorldEditorStatus(
                    status,
                    `World data was saved, but the icon update failed: ${(iconResult && iconResult.error) || 'Unknown error.'}`,
                    'error'
                  );
                  return;
                }
                pendingWorldIconBase64 = null;
              }

              modalControls.close();
              await loadInstalledWorlds();
              showInstalledWorldDetailModal({
                world_id: finalWorldId,
                title: requestedTitle || finalWorldId,
              });
            } catch (err) {
              setWorldEditorStatus(status, err.message || String(err), 'error');
            } finally {
              saving = false;
            }
          },
        });

      buttons.push({ label: 'Close' });
      return buttons;
    };

    const rebuildModalButtons = () => {
      controls.update({ buttons: buildModalButtons() });
    };

    controls.update({
      title: `Edit World: ${detail.title || detail.world_id || 'World'}`,
      customContent: content,
      boxClassList: ['world-nbt-dialog'],
      buttons: buildModalButtons(),
    });

    renderActiveTab();
  } catch (err) {
    loading.innerHTML = `<p style="color:#ff4141;">${err.message || err}</p>`;
  }
};

const openSimpleWorldNbtEditor = (world) => openWorldNbtEditor(world, 'simple');

const openAdvancedWorldNbtEditor = (world) => openWorldNbtEditor(world, 'advanced');

const showInstalledWorldDetailModal = async (world) => {
  const loading = createWorldEditorLoadingContent('Loading world details...');

  const controls = showMessageBox({
    title: world.title || world.world_id || 'World Details',
    customContent: loading,
    boxClassList: ['world-detail-dialog'],
    buttons: [
      {
        label: 'Open Folder',
        classList: ['important'],
        onClick: () => openWorldFolder(world),
      },
      {
        label: 'Edit',
        classList: ['primary'],
        onClick: () => promptEditWorld(world),
      },
      {
        label: 'Export',
        classList: ['mild'],
        closeOnClick: false,
        onClick: () => exportWorld(world),
      },
      {
        label: 'Delete',
        classList: ['danger'],
        onClick: () => deleteWorld(world),
      },
      { label: 'Close' },
    ],
  });

  try {
    const detail = await api('/api/worlds/detail', 'POST', {
      storage_target: worldsState.storageTarget,
      custom_path: worldsState.customPath,
      world_id: world.world_id,
    });
    if (!detail || !detail.ok) {
      loading.innerHTML = `<p style="color:#ff4141;">${(detail && detail.error) || 'Failed to load world details.'}</p>`;
      return;
    }
    controls.update({
      title: detail.title || detail.world_id || 'World Details',
      customContent: renderInstalledWorldDetailContent(detail),
      boxClassList: ['world-detail-dialog'],
    });
  } catch (err) {
    console.error('Failed to load installed world details:', err);
    loading.innerHTML = '<p style="color:#ff4141;">Failed to load world details.</p>';
  }
};

const showAvailableWorldDetailModal = async (world) => {
  const content = document.createElement('div');
  content.className = 'mod-detail-content';

  const loadingEl = createInlineLoadingState('Loading world details...');
  content.appendChild(loadingEl);

  showMessageBox({
    title: world.name || world.title || 'World Details',
    customContent: content,
    buttons: [{ label: 'Close' }],
  });

  try {
    const [detailResult, versionsResult] = await Promise.allSettled([
      api('/api/worlds/detail', 'POST', {
        provider: world.provider || worldsState.provider,
        project_id: world.project_id,
      }),
      api('/api/worlds/versions', 'POST', {
        provider: world.provider || worldsState.provider,
        project_id: world.project_id,
      }),
    ]);

    const detailRes = detailResult.status === 'fulfilled' ? detailResult.value : null;
    const versionsRes = versionsResult.status === 'fulfilled' ? versionsResult.value : null;
    const detailError = detailResult.status === 'rejected'
      ? ((detailResult.reason && detailResult.reason.message) || 'Failed to fetch world details.')
      : ((!detailRes || !detailRes.ok) ? ((detailRes && detailRes.error) || 'Failed to fetch world details.') : '');
    const versionsError = versionsResult.status === 'rejected'
      ? ((versionsResult.reason && versionsResult.reason.message) || 'Failed to fetch world versions.')
      : ((!versionsRes || !versionsRes.ok) ? ((versionsRes && versionsRes.error) || 'Failed to fetch world versions.') : '');

    content.innerHTML = '';

    const description = (detailRes && detailRes.ok && detailRes.body) ? detailRes.body : (world.summary || '');
    if (description) {
      const descSection = document.createElement('div');
      descSection.className = 'mod-detail-description';
      if (description.includes('<') && description.includes('>')) {
        descSection.innerHTML = sanitizeRemoteDetailHtml(description);
      } else {
        descSection.textContent = description;
      }

      descSection.querySelectorAll('a[href]').forEach((anchor) => {
        anchor.setAttribute('target', '_blank');
        anchor.addEventListener('click', (event) => {
          event.preventDefault();
          const rawHref = anchor.getAttribute('href') || '';
          let href = rawHref;
          if (href.startsWith('/')) href = `https://www.curseforge.com${href}`;
          if (href.startsWith('//')) href = `https:${href}`;
          if (href.startsWith('www.')) href = `https://${href}`;
          if (href.startsWith('http://') || href.startsWith('https://')) {
            window.open(href, '_blank');
          }
        });
      });

      content.appendChild(descSection);
    }

    if (detailError) {
      const detailErrorEl = document.createElement('p');
      detailErrorEl.style.cssText = 'color:#ffb36a;margin-top:8px;';
      detailErrorEl.textContent = detailError;
      content.appendChild(detailErrorEl);
    }

    const gallery = (detailRes && detailRes.ok && Array.isArray(detailRes.gallery)) ? detailRes.gallery : [];
    if (gallery.length > 0) {
      const section = document.createElement('div');
      section.className = 'mod-detail-gallery';

      const title = document.createElement('h4');
      title.textContent = 'Screenshots';
      title.style.marginBottom = '8px';
      section.appendChild(title);

      const row = document.createElement('div');
      row.className = 'mod-detail-gallery-row';

      gallery.slice(0, 6).forEach((entry) => {
        const url = typeof entry === 'string' ? entry : (entry.url || entry.thumbnailUrl || '');
        if (!url) return;
        const img = document.createElement('img');
        img.src = url;
        img.className = 'mod-detail-screenshot';
        img.onerror = () => { img.style.display = 'none'; };
        img.title = 'Click to enlarge';
        img.addEventListener('click', () => {
          const lightbox = ensureScreenshotLightbox();
          const lightboxImg = lightbox.querySelector('img');
          if (lightboxImg) lightboxImg.src = url;
          lightbox.classList.add('active');
        });
        row.appendChild(img);
      });

      section.appendChild(row);
      content.appendChild(section);
    }

    if (detailRes && detailRes.ok) {
      const stats = document.createElement('div');
      stats.className = 'mod-detail-stats';
      const downloads = Number(detailRes.downloads || world.download_count || 0);
      const categories = Array.isArray(detailRes.categories) ? detailRes.categories : (world.categories || []);
      stats.innerHTML = `<span>Downloads: ${downloads.toLocaleString()}</span>`;
      if (categories.length > 0) {
        stats.innerHTML += ` <span>Categories: ${categories.join(', ')}</span>`;
      }
      content.appendChild(stats);
    }

    const allVersions = (versionsRes && versionsRes.ok && Array.isArray(versionsRes.versions)) ? versionsRes.versions : [];
    if (versionsError) {
      const versionsErrorEl = document.createElement('p');
      versionsErrorEl.style.color = '#ff4141';
      versionsErrorEl.textContent = versionsError;
      content.appendChild(versionsErrorEl);
    } else if (allVersions.length > 0) {
      const versionSection = document.createElement('div');
      versionSection.className = 'mod-detail-versions';

      const versionTitle = document.createElement('h4');
      versionTitle.textContent = `Versions (${allVersions.length})`;
      versionTitle.style.marginBottom = '8px';
      versionSection.appendChild(versionTitle);

      const filterRow = document.createElement('div');
      filterRow.className = 'mod-detail-version-filters';

      const versionSet = new Set();
      allVersions.forEach((ver) => {
        (ver.game_versions || []).forEach((mcVersion) => versionSet.add(mcVersion));
      });
      const mcVersionFilter = document.createElement('select');
      mcVersionFilter.innerHTML = '<option value="">All MC Versions</option>';
      Array.from(versionSet)
        .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))
        .forEach((mcVersion) => {
          const option = document.createElement('option');
          option.value = mcVersion;
          option.textContent = mcVersion;
          mcVersionFilter.appendChild(option);
        });
      if (
        worldsState.gameVersion &&
        Array.from(mcVersionFilter.options).some((option) => option.value === worldsState.gameVersion)
      ) {
        mcVersionFilter.value = worldsState.gameVersion;
      }
      filterRow.appendChild(mcVersionFilter);
      versionSection.appendChild(filterRow);

      const versionList = document.createElement('div');
      versionList.className = 'mod-detail-version-list';

      const renderVersions = () => {
        const localSelected = mcVersionFilter.value;
        let filtered = allVersions;
        if (localSelected) {
          filtered = filtered.filter((ver) => (ver.game_versions || []).includes(localSelected));
        }
        if (!filtered.length) {
          versionList.innerHTML = '<p style="text-align:center;color:#999;padding:8px;">No versions match filters</p>';
          return;
        }

        let recommendedIdx = filtered.findIndex((ver) => String(ver.version_type || '').toLowerCase() === 'release');
        if (recommendedIdx === -1) recommendedIdx = filtered.findIndex((ver) => String(ver.version_type || '').toLowerCase() === 'beta');
        if (recommendedIdx === -1) recommendedIdx = 0;

        versionList.innerHTML = '';
        filtered.forEach((ver, idx) => {
          const row = document.createElement('div');
          row.className = 'mod-detail-version-row' + (idx === recommendedIdx ? ' recommended' : '');

          const type = String(ver.version_type || 'release').toLowerCase();
          const typeBadge = document.createElement('span');
          typeBadge.className = `mod-version-type-badge mod-version-type-${type}`;
          typeBadge.textContent = type === 'release' ? 'R' : type === 'beta' ? 'B' : 'A';
          typeBadge.title = type.charAt(0).toUpperCase() + type.slice(1);

          const versionName = document.createElement('span');
          versionName.className = 'mod-detail-version-name';
          versionName.textContent = ver.version_number || ver.display_name || ver.file_name || 'Unknown';

          const meta = document.createElement('span');
          meta.className = 'mod-detail-version-meta';
          meta.textContent = (ver.game_versions || []).slice(0, 3).join(', ');

          const downloadBtn = document.createElement('button');
          downloadBtn.className = 'primary';
          downloadBtn.textContent = 'Download';
          downloadBtn.style.fontSize = '11px';
          downloadBtn.style.padding = '3px 8px';
          downloadBtn.addEventListener('click', () => {
            installWorld(world, ver, downloadBtn);
          });

          row.appendChild(typeBadge);
          row.appendChild(versionName);
          row.appendChild(meta);
          row.appendChild(downloadBtn);
          versionList.appendChild(row);
        });
      };

      mcVersionFilter.addEventListener('change', renderVersions);
      renderVersions();

      versionSection.appendChild(versionList);
      content.appendChild(versionSection);
    } else {
      const noVersions = document.createElement('p');
      noVersions.style.color = '#999';
      noVersions.textContent = 'No downloadable versions were found for this world.';
      content.appendChild(noVersions);
    }
  } catch (err) {
    console.error('Failed to load available world details:', err);
    content.innerHTML = '<p style="color:#ff4141;">Failed to render world details.</p>';
  }
};

export const refreshWorldsStorageContext = async () => {
  await Promise.all([
    populateWorldStorageOptions(),
    populateWorldVersionDropdown(),
  ]);

  if (worldsState.storageTarget === 'default') {
    await loadInstalledWorlds();
  } else {
    renderWorldVersionDropdown();
    renderInstalledWorlds();
  }
};

export const refreshWorldsPageState = async () => {
  const storageSelect = getEl('worlds-storage-select');
  const providerSelect = getEl('worlds-provider-select');
  const versionSelect = getEl('worlds-version-select');
  const categorySelect = getEl('worlds-category-select');
  const sortSelect = getEl('worlds-sort-select');
  const searchInput = getEl('worlds-search');

  if (storageSelect) storageSelect.value = worldsState.storageTarget || 'default';
  if (providerSelect) providerSelect.value = worldsState.provider || 'curseforge';
  if (versionSelect) versionSelect.value = worldsState.gameVersion || '';
  if (categorySelect) categorySelect.value = worldsState.category || '';
  if (sortSelect) sortSelect.value = worldsState.sortBy || 'relevance';
  if (searchInput) searchInput.value = worldsState.searchQuery || '';

  updateWorldsProviderDisplay();
  syncWorldsCustomControls();
  await refreshWorldsStorageContext();
  const searchOk = await searchWorlds();
  return searchOk && !worldsState.installedError;
};

export const initWorldsPage = () => {
  const storageSelect = getEl('worlds-storage-select');
  if (storageSelect) {
    storageSelect.addEventListener('change', () => {
      worldsState.storageTarget = normalizeWorldStorageTarget(storageSelect.value);
      syncWorldsCustomControls();
      loadInstalledWorlds();
    });
  }

  const providerSelect = getEl('worlds-provider-select');
  if (providerSelect) {
    providerSelect.addEventListener('change', () => {
      worldsState.provider = providerSelect.value || 'curseforge';
      worldsState.currentPage = 1;
      updateWorldsProviderDisplay();
      searchWorlds();
    });
  }

  const versionSelect = getEl('worlds-version-select');
  if (versionSelect) {
    versionSelect.addEventListener('change', () => {
      worldsState.gameVersion = versionSelect.value || '';
      worldsState.currentPage = 1;
      renderInstalledWorlds();
      searchWorlds();
    });
  }

  const categorySelect = getEl('worlds-category-select');
  if (categorySelect) {
    categorySelect.addEventListener('change', () => {
      worldsState.category = categorySelect.value || '';
      worldsState.currentPage = 1;
      searchWorlds();
    });
  }

  const sortSelect = getEl('worlds-sort-select');
  if (sortSelect) {
    sortSelect.addEventListener('change', () => {
      worldsState.sortBy = sortSelect.value || 'relevance';
      worldsState.currentPage = 1;
      searchWorlds();
    });
  }

  const searchInput = getEl('worlds-search');
  if (searchInput) {
    let searchTimeout;
    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        worldsState.searchQuery = searchInput.value.trim();
        worldsState.currentPage = 1;
        renderInstalledWorlds();
        searchWorlds();
      }, 400);
    });
  }

  const refreshBtn = getEl('worlds-refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      worldsState.currentPage = 1;
      refreshWorldsPageState();
    });
  }

  const importBtn = getEl('worlds-import-btn');
  if (importBtn) {
    importBtn.addEventListener('click', () => {
      importWorldFlow();
    });
  }

  const bulkToggleBtn = getEl('worlds-bulk-toggle-btn');
  if (bulkToggleBtn) {
    bulkToggleBtn.addEventListener('click', () => {
      setWorldsBulkMode(!state.worldsBulkState.enabled);
    });
  }

  const bulkDeleteBtn = getEl('worlds-bulk-delete-btn');
  if (bulkDeleteBtn) {
    bulkDeleteBtn.addEventListener('click', () => {
      bulkDeleteSelectedWorlds();
    });
  }

  const selectFolderBtn = getEl('worlds-select-storage-folder-btn');
  if (selectFolderBtn) {
    selectFolderBtn.addEventListener('click', async () => {
      selectFolderBtn.disabled = true;
      try {
        const res = await api('/api/storage-directory/select', 'POST', {
          current_path: worldsState.customPath,
          save_to_settings: false,
        });
        if (res && res.cancelled) return;
        if (!res || res.ok !== true) {
          showMessageBox({
            title: 'Folder Selection Error',
            message: (res && (res.error || res.message)) || 'Failed to select a custom world storage directory.',
            buttons: [{ label: 'OK' }],
          });
          return;
        }
        worldsState.customPath = String(res.path || '').trim();
        syncWorldsCustomControls();
        if (worldsState.storageTarget === 'custom') {
          await loadInstalledWorlds();
        }
      } catch (err) {
        showMessageBox({
          title: 'Folder Selection Error',
          message: `Failed to select a custom world storage directory.<br><br>${err.message || err}`,
          buttons: [{ label: 'OK' }],
        });
      } finally {
        selectFolderBtn.disabled = false;
      }
    });
  }

  initWorldsViewToggle();
  updateWorldsProviderDisplay();
  syncWorldsCustomControls();
};
