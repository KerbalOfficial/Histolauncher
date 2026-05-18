import { state } from './state.js';
import {
  getEl,
  bindKeyboardActivation,
  openSharedImageLightbox,
  wireCardActionArrowNavigation,
  imageAttachErrorPlaceholder,
} from './dom-utils.js';
import { api } from './api.js';
import {
  hideLoadingOverlay,
  setLoadingOverlayText,
  showLoadingOverlay,
  showMessageBox,
} from './modal.js';
import { t } from './i18n.js';
import { formatBytes, normalizeFavoriteVersions } from './string-utils.js';
import { createEmptyState, createInlineLoadingState } from './ui-states.js';

const SCREENSHOT_MIME_TYPES = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.bmp': 'image/bmp',
};

let _autoSaveSetting = () => {
  throw new Error('screenshots.js: autoSaveSetting was not configured. Call setAutoSaveSetting() first.');
};

export const setAutoSaveSetting = (fn) => {
  _autoSaveSetting = fn;
};

const settingsProfilePayload = (patch = {}) => ({
  ...patch,
  _profile_id: state.profilesState.activeProfile || 'default',
});

let screenshotsState = {
  storageTarget: 'all',
  customPath: '',
  searchQuery: '',
  screenshots: [],
  filteredScreenshots: [],
  storageOptions: [],
  storageLabel: 'All',
  storagePath: '',
  loading: false,
  error: null,
};

const normalizeScreenshotStorageTarget = (value) => {
  const raw = String(value || 'all').trim();
  if (raw.toLowerCase().startsWith('version:')) {
    return `version:${raw.split(':', 2)[1] || ''}`;
  }
  const normalized = raw.toLowerCase();
  if (normalized === 'all' || normalized === 'global' || normalized === 'custom' || normalized === 'default') {
    return normalized;
  }
  return 'all';
};

const getScreenshotDisplayName = (screenshot) => String(
  (screenshot && (screenshot.display_name || screenshot.title || screenshot.file_name)) || t('screenshots.itemFallback')
).trim() || t('screenshots.itemFallback');

const getScreenshotBulkKey = (screenshot) => String((screenshot && screenshot.screenshot_id) || '').trim();

const getFavoriteScreenshots = () => {
  const favorites = normalizeFavoriteVersions(state.settingsState.favorite_screenshots);
  state.settingsState.favorite_screenshots = favorites;
  return favorites;
};

const getScreenshotOperationPayload = (screenshot) => {
  const storageTarget = normalizeScreenshotStorageTarget((screenshot && screenshot.storage_target) || screenshotsState.storageTarget);
  return {
    storage_target: storageTarget,
    relative_path: String((screenshot && screenshot.relative_path) || '').trim(),
    custom_path: storageTarget === 'custom' ? screenshotsState.customPath : '',
  };
};

const formatScreenshotDateTime = (value) => {
  const ts = Number(value || 0);
  if (!Number.isFinite(ts) || ts <= 0) return t('common.unknown');
  try {
    return new Date(ts).toLocaleString();
  } catch (_) {
    return t('common.unknown');
  }
};

const normalizeScreenshotSearchText = (value) => {
  let text = String(value || '').toLowerCase();
  try {
    text = decodeURIComponent(text);
  } catch (_) {
  }
  return text
    .replace(/\+/g, ' ')
    .replace(/[%_\-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
};

const openScreenshotLightbox = (screenshot, { showKeyboardCursor = false } = {}) => {
  const imageUrl = String((screenshot && screenshot.image_url) || '').trim();
  if (!imageUrl) return;
  openSharedImageLightbox({
    src: imageUrl,
    alt: getScreenshotDisplayName(screenshot),
    closeAriaLabel: t('screenshots.actions.closeImagePreview'),
    showKeyboardCursor,
  });
};

const updateScreenshotsWarning = (message = '') => {
  const warn = getEl('screenshots-section-warning');
  if (!warn) return;
  if (message) {
    warn.textContent = message;
    warn.classList.remove('hidden');
  } else {
    warn.textContent = '';
    warn.classList.add('hidden');
  }
};

const syncScreenshotsCustomControls = () => {
  const item = getEl('screenshots-custom-filter-item');
  const pathLabel = getEl('screenshots-custom-path');
  if (item) item.classList.toggle('hidden', screenshotsState.storageTarget !== 'custom');
  if (pathLabel) pathLabel.textContent = screenshotsState.customPath || t('common.none');
};

export const updateScreenshotsBulkActionsUI = () => {
  const toggleBtn = getEl('screenshots-bulk-toggle-btn');
  const deleteBtn = getEl('screenshots-bulk-delete-btn');
  const count = state.screenshotsBulkState.selected.size;

  if (toggleBtn) {
    toggleBtn.textContent = state.screenshotsBulkState.enabled ? t('common.cancelBulk') : t('common.bulkSelect');
    toggleBtn.className = state.screenshotsBulkState.enabled ? 'primary' : 'mild';
  }

  if (deleteBtn) {
    deleteBtn.classList.toggle('hidden', !state.screenshotsBulkState.enabled);
    deleteBtn.textContent = t('screenshots.bulkDelete.deleteSelectedCount', { count });
    deleteBtn.disabled = count === 0;
  }
};

const pruneScreenshotsBulkSelection = () => {
  if (!state.screenshotsBulkState.enabled) return;
  const installed = new Set((screenshotsState.screenshots || []).map((screenshot) => getScreenshotBulkKey(screenshot)).filter(Boolean));
  const next = new Set();
  state.screenshotsBulkState.selected.forEach((key) => {
    if (installed.has(key)) next.add(key);
  });
  state.screenshotsBulkState.selected = next;
};

const setScreenshotsBulkMode = (enabled) => {
  state.screenshotsBulkState.enabled = !!enabled;
  if (!state.screenshotsBulkState.enabled) {
    state.screenshotsBulkState.selected = new Set();
  }
  updateScreenshotsBulkActionsUI();
  renderScreenshots();
};

const toggleScreenshotBulkSelection = (screenshot) => {
  if (!state.screenshotsBulkState.enabled || !screenshot) return;
  const key = getScreenshotBulkKey(screenshot);
  if (!key) return;
  if (state.screenshotsBulkState.selected.has(key)) {
    state.screenshotsBulkState.selected.delete(key);
  } else {
    state.screenshotsBulkState.selected.add(key);
  }
  updateScreenshotsBulkActionsUI();
  renderScreenshots();
};

const applyScreenshotsViewMode = () => {
  const mode = state.settingsState.screenshots_view || 'grid';
  const list = getEl('screenshots-images-list');
  if (list) list.classList.toggle('list-view', mode === 'list');

  const gridBtn = getEl('screenshots-view-grid-btn');
  const listBtn = getEl('screenshots-view-list-btn');
  if (gridBtn) gridBtn.classList.toggle('active', mode === 'grid');
  if (listBtn) listBtn.classList.toggle('active', mode === 'list');
};

const initScreenshotsViewToggle = () => {
  const gridBtn = getEl('screenshots-view-grid-btn');
  const listBtn = getEl('screenshots-view-list-btn');

  if (gridBtn) {
    gridBtn.addEventListener('click', () => {
      if (state.settingsState.screenshots_view !== 'grid') {
        _autoSaveSetting('screenshots_view', 'grid');
        applyScreenshotsViewMode();
      }
    });
  }

  if (listBtn) {
    listBtn.addEventListener('click', () => {
      if (state.settingsState.screenshots_view !== 'list') {
        _autoSaveSetting('screenshots_view', 'list');
        applyScreenshotsViewMode();
      }
    });
  }

  applyScreenshotsViewMode();
};

const buildScreenshotCardSummary = (screenshot) => {
  const explicit = String(screenshot.description || screenshot.summary || '').trim();
  const takenText = formatScreenshotDateTime(screenshot.created_at || screenshot.modified_at);
  const parts = [];
  if (explicit) parts.push(explicit);
  if (takenText !== t('common.unknown')) {
    parts.push(takenText);
  }
  return parts.join(t('common.listSeparator')) || String(screenshot.file_name || getScreenshotDisplayName(screenshot));
};

const buildScreenshotSearchText = (screenshot) => normalizeScreenshotSearchText([
  screenshot.display_name,
  screenshot.file_name,
  screenshot.description,
  screenshot.summary,
  screenshot.storage_label,
  screenshot.relative_dir,
].join(' '));

const applyScreenshotsClientFilters = () => {
  const needle = normalizeScreenshotSearchText(screenshotsState.searchQuery);
  const favorites = new Set(getFavoriteScreenshots());
  const filtered = !needle
    ? [...(screenshotsState.screenshots || [])]
    : (screenshotsState.screenshots || []).filter((screenshot) => buildScreenshotSearchText(screenshot).includes(needle));

  filtered.sort((left, right) => {
    const leftFav = favorites.has(getScreenshotBulkKey(left)) ? 1 : 0;
    const rightFav = favorites.has(getScreenshotBulkKey(right)) ? 1 : 0;
    if (leftFav !== rightFav) return rightFav - leftFav;

    const leftModified = Number(left && left.modified_at) || 0;
    const rightModified = Number(right && right.modified_at) || 0;
    if (leftModified !== rightModified) return rightModified - leftModified;

    return getScreenshotDisplayName(left).localeCompare(getScreenshotDisplayName(right), undefined, { sensitivity: 'base' });
  });

  screenshotsState.filteredScreenshots = filtered;
};

const persistFavoriteScreenshots = async (favorites, { showError = true } = {}) => {
  state.settingsState.favorite_screenshots = [...favorites];
  try {
    await api('/api/settings', 'POST', settingsProfilePayload({
      favorite_screenshots: favorites.join(', '),
    }));
    return true;
  } catch (err) {
    if (showError) {
      showMessageBox({
        title: t('screenshots.favorite.saveFailedTitle'),
        message: t('screenshots.favorite.saveFailed', {
          error: (err && err.message) || err || t('common.unknownError'),
        }),
        buttons: [{ label: t('common.ok') }],
      });
    } else {
      console.warn('Failed to persist screenshot favorites:', err);
    }
    return false;
  }
};

const syncFavoriteScreenshotsAfterDelete = async (keysToRemove) => {
  const keySet = new Set((keysToRemove || []).filter(Boolean));
  if (!keySet.size) return;
  const current = getFavoriteScreenshots();
  const next = current.filter((key) => !keySet.has(key));
  if (next.length === current.length) return;
  await persistFavoriteScreenshots(next, { showError: false });
};

const toggleFavoriteScreenshot = async (screenshot) => {
  const key = getScreenshotBulkKey(screenshot);
  if (!key) return;

  const previousFavorites = [...getFavoriteScreenshots()];
  const isFavorite = previousFavorites.includes(key);
  const nextFavorites = isFavorite
    ? previousFavorites.filter((entry) => entry !== key)
    : [...previousFavorites, key];

  state.settingsState.favorite_screenshots = nextFavorites;
  applyScreenshotsClientFilters();
  renderScreenshots();

  const ok = await persistFavoriteScreenshots(nextFavorites, { showError: true });
  if (!ok) {
    state.settingsState.favorite_screenshots = previousFavorites;
    applyScreenshotsClientFilters();
    renderScreenshots();
  }
};

const populateScreenshotStorageOptions = async () => {
  const select = getEl('screenshots-storage-select');
  if (!select) return;

  const previousValue = normalizeScreenshotStorageTarget(screenshotsState.storageTarget || select.value || 'all');
  select.innerHTML = `<option value="all">${t('common.all')}</option>`;

  try {
    const res = await api('/api/screenshots/storage-options', 'POST', {
      custom_path: screenshotsState.customPath,
    });
    if (!res || !res.ok) {
      screenshotsState.storageOptions = [];
      select.value = previousValue;
      return;
    }

    const options = Array.isArray(res.options) ? res.options : [];
    screenshotsState.storageOptions = options;
    select.innerHTML = '';

    options.forEach((optionData) => {
      const option = document.createElement('option');
      option.value = optionData.value || 'all';
      option.textContent = optionData.label || option.value || t('common.all');
      select.appendChild(option);
    });

    if (Array.from(select.options).some((option) => option.value === previousValue)) {
      select.value = previousValue;
      screenshotsState.storageTarget = previousValue;
    } else {
      select.value = 'all';
      screenshotsState.storageTarget = 'all';
    }
  } catch (err) {
    console.error('Failed to load screenshot storage options:', err);
    select.value = previousValue;
  }
};

const createHoverIconButton = ({
  defaultIcon,
  hoverIcon,
  alt,
  ariaLabel,
  title,
  onClick,
}) => {
  const button = document.createElement('div');
  button.className = 'icon-button';
  bindKeyboardActivation(button, { ariaLabel });
  if (title) button.title = title;

  const image = document.createElement('img');
  image.alt = alt;
  image.src = defaultIcon;
  imageAttachErrorPlaceholder(image, 'assets/images/placeholder.png');
  button.appendChild(image);

  if (hoverIcon && hoverIcon !== defaultIcon) {
    button.addEventListener('mouseenter', () => {
      image.src = hoverIcon;
    });
    button.addEventListener('mouseleave', () => {
      image.src = defaultIcon;
    });
  }

  button.addEventListener('click', onClick);
  return button;
};

const showRenameScreenshotModal = (screenshot) => {
  const currentName = getScreenshotDisplayName(screenshot);
  const extension = String((screenshot && screenshot.extension) || '').trim();

  const content = document.createElement('div');

  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.textContent = t('screenshots.rename.prompt', { name: currentName });

  const input = document.createElement('input');
  input.type = 'text';
  input.maxLength = 240;
  input.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;';
  input.value = currentName;

  const hint = document.createElement('p');
  hint.style.cssText = 'margin:8px 0 0 0;font-size:12px;color:var(--color-text-muted);';
  hint.textContent = t('screenshots.rename.keepExtension', {
    extension: extension || t('common.unknown'),
  });

  content.appendChild(label);
  content.appendChild(input);
  content.appendChild(hint);

  showMessageBox({
    title: t('screenshots.rename.title', { name: currentName }),
    customContent: content,
    buttons: [
      {
        label: t('common.save'),
        classList: ['primary'],
        onClick: async () => {
          const newName = String(input.value || '').trim();
          if (!newName) {
            showMessageBox({
              title: t('screenshots.rename.invalidTitle'),
              message: t('screenshots.rename.invalidMessage'),
              buttons: [{ label: t('common.ok'), onClick: () => showRenameScreenshotModal(screenshot) }],
            });
            return;
          }

          const res = await api('/api/screenshots/update', 'POST', {
            ...getScreenshotOperationPayload(screenshot),
            new_name: newName,
          });
          if (!res || !res.ok) {
            showMessageBox({
              title: t('screenshots.rename.failedTitle'),
              message: (res && res.error) || t('screenshots.rename.failedMessage'),
              buttons: [{ label: t('common.ok'), onClick: () => showRenameScreenshotModal(screenshot) }],
            });
            return;
          }

          await loadInstalledScreenshots();
        },
      },
      { label: t('common.cancel') },
    ],
  });
};

const deleteScreenshot = async (screenshot, { skipConfirm = false } = {}) => {
  const screenshotName = getScreenshotDisplayName(screenshot);
  const screenshotKey = getScreenshotBulkKey(screenshot);

  const runDelete = async () => {
    const res = await api('/api/screenshots/delete', 'POST', getScreenshotOperationPayload(screenshot));
    if (!res || !res.ok) {
      showMessageBox({
        title: t('screenshots.delete.failedTitle'),
        message: (res && res.error) || t('screenshots.delete.failedMessage'),
        buttons: [{ label: t('common.ok') }],
      });
      return;
    }

    await syncFavoriteScreenshotsAfterDelete([screenshotKey]);
    await loadInstalledScreenshots();
  };

  if (skipConfirm || state.isShiftDown) {
    await runDelete();
    return;
  }

  showMessageBox({
    title: t('screenshots.delete.title'),
    message: t('screenshots.delete.confirmMessage', { name: screenshotName }),
    buttons: [
      { label: t('common.delete'), classList: ['danger'], onClick: runDelete },
      { label: t('common.cancel') },
    ],
  });
};

const openScreenshotInEditor = async (screenshot) => {
  const res = await api('/api/screenshots/open', 'POST', getScreenshotOperationPayload(screenshot));
  if (!res || !res.ok) {
    showMessageBox({
      title: t('screenshots.edit.failedTitle'),
      message: (res && res.error) || t('screenshots.edit.failedMessage'),
      buttons: [{ label: t('common.ok') }],
    });
  }
};

const saveScreenshotAs = async (screenshot) => {
  const imageUrl = String((screenshot && screenshot.image_url) || '').trim();
  if (!imageUrl) {
    showMessageBox({
      title: t('screenshots.saveAs.failedTitle'),
      message: t('screenshots.saveAs.failedMessage', { error: t('screenshots.saveAs.missingFile') }),
      buttons: [{ label: t('common.ok') }],
    });
    return;
  }

  try {
    const response = await fetch(imageUrl);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const blob = await response.blob();
    const extension = String((screenshot && screenshot.extension) || '').trim().toLowerCase();
    const mimeType = blob.type || SCREENSHOT_MIME_TYPES[extension] || 'application/octet-stream';
    const fileName = String((screenshot && screenshot.file_name) || `${getScreenshotDisplayName(screenshot)}${extension || ''}`).trim();

    if (window.showSaveFilePicker) {
      try {
        const pickerOptions = { suggestedName: fileName };
        if (mimeType && extension) {
          pickerOptions.types = [{
            description: t('screenshots.saveAs.fileTypeDescription'),
            accept: { [mimeType]: [extension] },
          }];
        }
        const fileHandle = await window.showSaveFilePicker(pickerOptions);
        const writable = await fileHandle.createWritable();
        await writable.write(blob);
        await writable.close();
        return;
      } catch (saveErr) {
        if (saveErr && saveErr.name === 'AbortError') {
          return;
        }
      }
    }

    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = fileName;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
    } finally {
      URL.revokeObjectURL(url);
    }
  } catch (err) {
    showMessageBox({
      title: t('screenshots.saveAs.failedTitle'),
      message: t('screenshots.saveAs.failedMessage', {
        error: (err && err.message) || err || t('common.unknownError'),
      }),
      buttons: [{ label: t('common.ok') }],
    });
  }
};

const bulkDeleteSelectedScreenshots = async ({ skipConfirm = false } = {}) => {
  const selectedKeys = Array.from(state.screenshotsBulkState.selected);
  if (!selectedKeys.length) {
    showMessageBox({
      title: t('screenshots.bulkDelete.title'),
      message: t('screenshots.bulkDelete.noSelected'),
      buttons: [{ label: t('common.ok') }],
    });
    return;
  }

  const selectedKeySet = new Set(selectedKeys);
  const items = (screenshotsState.screenshots || []).filter((screenshot) => selectedKeySet.has(getScreenshotBulkKey(screenshot)));

  const runDelete = async () => {
    let cancelRequested = false;
    let processed = 0;
    let deleted = 0;
    const failures = [];

    showLoadingOverlay(t('screenshots.bulkDelete.deletingProgress', { current: 0, total: items.length }), {
      buttons: [
        {
          label: t('common.cancel'),
          classList: ['danger'],
          closeOnClick: false,
          onClick: (_values, controls) => {
            if (cancelRequested) return;
            cancelRequested = true;
            controls.update({
              message: t('screenshots.bulkDelete.cancelling'),
              buttons: [],
            });
          },
        },
      ],
    });

    for (const screenshot of items) {
      if (cancelRequested) break;
      try {
        const res = await api('/api/screenshots/delete', 'POST', getScreenshotOperationPayload(screenshot));
        if (res && res.ok) {
          deleted += 1;
        } else {
          failures.push(`${getScreenshotDisplayName(screenshot)}: ${(res && res.error) || t('common.unknownError')}`);
        }
      } catch (err) {
        failures.push(`${getScreenshotDisplayName(screenshot)}: ${(err && err.message) || t('versions.bulkDelete.requestFailed')}`);
      }
      processed += 1;
      setLoadingOverlayText(t('screenshots.bulkDelete.deletingProgress', { current: processed, total: items.length }));
    }

    hideLoadingOverlay();
    await syncFavoriteScreenshotsAfterDelete(selectedKeys);
    setScreenshotsBulkMode(false);
    await loadInstalledScreenshots();

    if (cancelRequested) {
      showMessageBox({
        title: t('screenshots.bulkDelete.cancelledTitle'),
        message: t(
          failures.length ? 'screenshots.bulkDelete.cancelledWithFailures' : 'screenshots.bulkDelete.cancelledMessage',
          { deleted, failures: failures.length }
        ),
        buttons: [{ label: t('common.ok') }],
      });
      return;
    }

    if (!failures.length) {
      showMessageBox({
        title: t('screenshots.bulkDelete.completeTitle'),
        message: t('screenshots.bulkDelete.completeMessage', { deleted }),
        buttons: [{ label: t('common.ok') }],
      });
      return;
    }

    const preview = failures.slice(0, 8).join('<br>');
    const more = failures.length > 8 ? `<br>${t('versions.bulkDelete.andMore', { count: failures.length - 8 })}` : '';
    showMessageBox({
      title: t('screenshots.bulkDelete.finishedWithErrorsTitle'),
      message: t('screenshots.bulkDelete.finishedWithErrorsMessage', {
        deleted,
        failures: `${preview}${more}`,
      }),
      buttons: [{ label: t('common.ok') }],
    });
  };

  if (skipConfirm || state.isShiftDown) {
    await runDelete();
    return;
  }

  showMessageBox({
    title: t('screenshots.bulkDelete.title'),
    message: t('screenshots.bulkDelete.confirmMessage', { count: items.length }),
    buttons: [
      { label: t('common.delete'), classList: ['danger'], onClick: runDelete },
      { label: t('common.cancel') },
    ],
  });
};

const createScreenshotCard = (screenshot) => {
  const card = document.createElement('div');
  card.className = 'version-card screenshot-card section-installed';

  const screenshotName = getScreenshotDisplayName(screenshot);
  const screenshotKey = getScreenshotBulkKey(screenshot);
  const favoriteSet = new Set(getFavoriteScreenshots());
  const isFavorite = favoriteSet.has(screenshotKey);
  const isBulkSelected = state.screenshotsBulkState.enabled && screenshotKey
    && state.screenshotsBulkState.selected.has(screenshotKey);

  if (isFavorite) card.classList.add('favorite');
  if (state.screenshotsBulkState.enabled) {
    card.classList.add('bulk-select-active');
    if (isBulkSelected) card.classList.add('bulk-selected');
  }

  bindKeyboardActivation(card, {
    ariaLabel: state.screenshotsBulkState.enabled
      ? t('screenshots.actions.toggleSelection', { name: screenshotName })
      : t('screenshots.actions.openImage', { name: screenshotName }),
  });

  const image = document.createElement('img');
  image.className = 'version-image';
  image.alt = screenshotName;
  image.src = screenshot.image_url || 'assets/images/screenshots.png';
  imageAttachErrorPlaceholder(image, 'assets/images/screenshots.png');

  const info = document.createElement('div');
  info.className = 'version-info';

  const headerRow = document.createElement('div');
  headerRow.className = 'version-header-row';

  const display = document.createElement('div');
  display.className = 'version-display';
  display.textContent = screenshotName;

  const iconRow = document.createElement('div');
  iconRow.className = 'version-actions-icons';

  const favoriteBtn = document.createElement('div');
  favoriteBtn.className = 'icon-button';
  bindKeyboardActivation(favoriteBtn, {
    ariaLabel: t('screenshots.actions.toggleFavorite', { name: screenshotName }),
  });
  favoriteBtn.setAttribute('aria-pressed', isFavorite ? 'true' : 'false');
  favoriteBtn.title = t('screenshots.actions.toggleFavorite', { name: screenshotName });

  const favoriteImg = document.createElement('img');
  favoriteImg.alt = t('screenshots.favoriteAlt');
  favoriteImg.src = isFavorite ? 'assets/images/filled_favorite.png' : 'assets/images/unfilled_favorite.png';
  imageAttachErrorPlaceholder(favoriteImg, 'assets/images/placeholder.png');
  favoriteBtn.appendChild(favoriteImg);

  favoriteBtn.addEventListener('mouseenter', () => {
    if (!getFavoriteScreenshots().includes(screenshotKey)) {
      favoriteImg.src = 'assets/images/filled_favorite.png';
    }
  });
  favoriteBtn.addEventListener('mouseleave', () => {
    favoriteImg.src = getFavoriteScreenshots().includes(screenshotKey)
      ? 'assets/images/filled_favorite.png'
      : 'assets/images/unfilled_favorite.png';
  });
  favoriteBtn.addEventListener('click', async (event) => {
    event.stopPropagation();
    if (state.screenshotsBulkState.enabled) {
      toggleScreenshotBulkSelection(screenshot);
      return;
    }
    await toggleFavoriteScreenshot(screenshot);
  });

  const renameBtn = createHoverIconButton({
    defaultIcon: 'assets/images/unfilled_pencil.png',
    hoverIcon: 'assets/images/filled_pencil.png',
    alt: t('screenshots.actions.renameImage', { name: screenshotName }),
    ariaLabel: t('screenshots.actions.renameImage', { name: screenshotName }),
    title: t('screenshots.actions.renameImage', { name: screenshotName }),
    onClick: (event) => {
      event.stopPropagation();
      if (state.screenshotsBulkState.enabled) {
        toggleScreenshotBulkSelection(screenshot);
        return;
      }
      showRenameScreenshotModal(screenshot);
    },
  });

  const deleteBtn = createHoverIconButton({
    defaultIcon: 'assets/images/unfilled_delete.png',
    hoverIcon: 'assets/images/filled_delete.png',
    alt: t('screenshots.actions.deleteImage', { name: screenshotName }),
    ariaLabel: t('screenshots.actions.deleteImage', { name: screenshotName }),
    title: t('screenshots.actions.deleteImage', { name: screenshotName }),
    onClick: async (event) => {
      event.stopPropagation();
      if (state.screenshotsBulkState.enabled) {
        toggleScreenshotBulkSelection(screenshot);
        return;
      }
      await deleteScreenshot(screenshot, { skipConfirm: !!event.shiftKey || state.isShiftDown });
    },
  });

  iconRow.appendChild(favoriteBtn);
  iconRow.appendChild(renameBtn);
  iconRow.appendChild(deleteBtn);

  const folder = document.createElement('div');
  folder.className = 'version-folder';
  folder.textContent = buildScreenshotCardSummary(screenshot);

  headerRow.appendChild(display);
  headerRow.appendChild(iconRow);
  info.appendChild(headerRow);
  info.appendChild(folder);

  const badgeRow = document.createElement('div');
  badgeRow.className = 'version-badge-row';

  const storageLabel = String(screenshot.storage_label || '').trim();
  if (storageLabel) {
    const storageBadge = document.createElement('span');
    storageBadge.className = 'version-badge lite';
    storageBadge.textContent = storageLabel.toUpperCase();
    badgeRow.appendChild(storageBadge);
  }

  const sizeLabel = formatBytes(Number(screenshot.size_bytes || 0));
  if (sizeLabel) {
    const sizeBadge = document.createElement('span');
    sizeBadge.className = 'version-badge size';
    sizeBadge.textContent = sizeLabel.toUpperCase();
    badgeRow.appendChild(sizeBadge);
  }

  const actions = document.createElement('div');
  actions.className = 'version-actions';

  const saveBtn = document.createElement('button');
  saveBtn.className = 'primary';
  saveBtn.textContent = t('screenshots.actions.saveAs');
  saveBtn.addEventListener('click', async (event) => {
    event.stopPropagation();
    if (state.screenshotsBulkState.enabled) {
      toggleScreenshotBulkSelection(screenshot);
      return;
    }
    saveBtn.disabled = true;
    try {
      await saveScreenshotAs(screenshot);
    } finally {
      saveBtn.disabled = false;
    }
  });

  const openBtn = document.createElement('button');
  openBtn.textContent = t('screenshots.actions.editImageButton');
  openBtn.addEventListener('click', async (event) => {
    event.stopPropagation();
    if (state.screenshotsBulkState.enabled) {
      toggleScreenshotBulkSelection(screenshot);
      return;
    }
    openBtn.disabled = true;
    try {
      await openScreenshotInEditor(screenshot);
    } finally {
      openBtn.disabled = false;
    }
  });

  actions.appendChild(saveBtn);
  actions.appendChild(openBtn);

  card.appendChild(image);
  card.appendChild(info);
  card.appendChild(badgeRow);
  card.appendChild(actions);

  if (state.screenshotsBulkState.enabled) {
    const checkbox = document.createElement('div');
    checkbox.className = 'bulk-select-checkbox';
    checkbox.textContent = isBulkSelected ? '✔' : '';
    card.appendChild(checkbox);
  }

  card.addEventListener('click', (event) => {
    if (event.target.closest('button, select, input, .icon-button')) return;
    if (state.screenshotsBulkState.enabled) {
      toggleScreenshotBulkSelection(screenshot);
      return;
    }
    openScreenshotLightbox(screenshot, {
      showKeyboardCursor: event.detail === 0,
    });
  });

  wireCardActionArrowNavigation(card);
  return card;
};

const renderScreenshots = () => {
  const list = getEl('screenshots-images-list');
  const subtitle = getEl('screenshots-images-subtitle');
  if (!list) return;

  list.innerHTML = '';
  updateScreenshotsBulkActionsUI();

  const count = Array.isArray(screenshotsState.filteredScreenshots)
    ? screenshotsState.filteredScreenshots.length
    : 0;

  if (subtitle) {
    subtitle.textContent = t('screenshots.imagesSubtitle', {
      count,
      storage: screenshotsState.storageLabel || t('common.all'),
    });
  }

  if (screenshotsState.loading) {
    list.appendChild(createInlineLoadingState(t('screenshots.list.loading'), { centered: true }));
    applyScreenshotsViewMode();
    return;
  }

  if (screenshotsState.error) {
    list.appendChild(createEmptyState(screenshotsState.error, { isError: true }));
    applyScreenshotsViewMode();
    return;
  }

  if (!count) {
    list.appendChild(createEmptyState(t('screenshots.list.emptyInstalled')));
    applyScreenshotsViewMode();
    return;
  }

  screenshotsState.filteredScreenshots.forEach((screenshot) => {
    list.appendChild(createScreenshotCard(screenshot));
  });

  applyScreenshotsViewMode();
};

export const loadInstalledScreenshots = async () => {
  screenshotsState.loading = true;
  renderScreenshots();

  try {
    const res = await api('/api/screenshots/installed', 'POST', {
      storage_target: screenshotsState.storageTarget,
      custom_path: screenshotsState.customPath,
    });

    screenshotsState.screenshots = (res && res.ok && Array.isArray(res.screenshots))
      ? res.screenshots
      : [];
    screenshotsState.storageLabel = (res && res.storage_label) || t('common.all');
    screenshotsState.storagePath = (res && res.storage_path) || '';
    screenshotsState.error = (!res || !res.ok)
      ? ((res && res.error) || t('screenshots.list.failedLoadInstalled'))
      : null;
  } catch (err) {
    console.error('Failed to load screenshots:', err);
    screenshotsState.screenshots = [];
    screenshotsState.error = t('screenshots.list.failedLoadInstalled');
  } finally {
    screenshotsState.loading = false;
    pruneScreenshotsBulkSelection();
    applyScreenshotsClientFilters();
    renderScreenshots();
    updateScreenshotsWarning(screenshotsState.error || '');
    return !screenshotsState.error;
  }
};

export const refreshScreenshotsStorageContext = async () => {
  await populateScreenshotStorageOptions();
  syncScreenshotsCustomControls();
  return loadInstalledScreenshots();
};

export const refreshScreenshotsPageState = async () => {
  const storageSelect = getEl('screenshots-storage-select');
  const searchInput = getEl('screenshots-search');

  if (storageSelect) storageSelect.value = screenshotsState.storageTarget || 'all';
  if (searchInput) searchInput.value = screenshotsState.searchQuery || '';

  syncScreenshotsCustomControls();
  updateScreenshotsBulkActionsUI();
  return refreshScreenshotsStorageContext();
};

export const rerenderScreenshotsPage = () => {
  applyScreenshotsClientFilters();
  renderScreenshots();
};

export const initScreenshotsPage = () => {
  const storageSelect = getEl('screenshots-storage-select');
  if (storageSelect) {
    storageSelect.addEventListener('change', () => {
      screenshotsState.storageTarget = normalizeScreenshotStorageTarget(storageSelect.value);
      syncScreenshotsCustomControls();
      loadInstalledScreenshots();
    });
  }

  const searchInput = getEl('screenshots-search');
  if (searchInput) {
    let searchTimeout;
    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        screenshotsState.searchQuery = searchInput.value.trim();
        applyScreenshotsClientFilters();
        renderScreenshots();
      }, 250);
    });
  }

  const refreshBtn = getEl('screenshots-refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      refreshScreenshotsPageState();
    });
  }

  const bulkToggleBtn = getEl('screenshots-bulk-toggle-btn');
  if (bulkToggleBtn) {
    bulkToggleBtn.addEventListener('click', () => {
      setScreenshotsBulkMode(!state.screenshotsBulkState.enabled);
    });
  }

  const bulkDeleteBtn = getEl('screenshots-bulk-delete-btn');
  if (bulkDeleteBtn) {
    bulkDeleteBtn.addEventListener('click', async () => {
      await bulkDeleteSelectedScreenshots({ skipConfirm: state.isShiftDown });
    });
  }

  const selectFolderBtn = getEl('screenshots-select-storage-folder-btn');
  if (selectFolderBtn) {
    selectFolderBtn.addEventListener('click', async () => {
      selectFolderBtn.disabled = true;
      try {
        const res = await api('/api/storage-directory/select', 'POST', {
          current_path: screenshotsState.customPath,
          save_to_settings: false,
        });
        if (res && res.cancelled) return;
        if (!res || res.ok !== true) {
          showMessageBox({
            title: t('worlds.storage.folderSelectionErrorTitle'),
            message: (res && (res.error || res.message)) || t('worlds.storage.failedSelectCustomDirectory'),
            buttons: [{ label: t('common.ok') }],
          });
          return;
        }

        screenshotsState.customPath = String(res.path || '').trim();
        syncScreenshotsCustomControls();
        if (screenshotsState.storageTarget === 'custom' || screenshotsState.storageTarget === 'all') {
          await loadInstalledScreenshots();
        }
      } catch (err) {
        showMessageBox({
          title: t('worlds.storage.folderSelectionErrorTitle'),
          message: t('worlds.storage.failedSelectCustomDirectoryWithError', { error: err.message || err }),
          buttons: [{ label: t('common.ok') }],
        });
      } finally {
        selectFolderBtn.disabled = false;
      }
    });
  }

  initScreenshotsViewToggle();
  syncScreenshotsCustomControls();
  updateScreenshotsBulkActionsUI();
};