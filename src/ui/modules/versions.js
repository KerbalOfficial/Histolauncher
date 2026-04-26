// ui/modules/versions.js

import { state } from './state.js';
import {
  $$,
  getEl,
  bindKeyboardActivation,
  wireCardActionArrowNavigation,
  imageAttachErrorPlaceholder,
  isShiftDelete,
} from './dom-utils.js';
import { getLoaderUi, LOADER_UI_ORDER } from './config.js';
import { api } from './api.js';
import {
  showMessageBox,
  showLoadingOverlay,
  hideLoadingOverlay,
  setLoadingOverlayText,
} from './modal.js';
import { refreshActionOverflowMenus } from './action-overflow.js';
import {
  applyVersionImageWithFallback,
  bumpTextureRevision,
  detachVersionImageFallbackHandler,
} from './textures.js';
import { invalidateInitialCache } from './cache.js';
import { buildCategoryListFromVersions, formatCategoryName } from './versions-data.js';
import {
  cancelInstallForVersionKey,
  pauseInstallForVersionKey,
  resumeInstallForVersionKey,
  handleInstallClick,
  updateVersionInListByKey,
  findVersionByInstallKey,
  updateCardProgressUI,
  startPollingForInstall,
} from './install.js';

const _deps = {};
for (const k of ['formatSizeBadge', 'init', 'normalizeVersionStorageOverrideMode', 'renderAllVersionSections', 'updateHomeInfo']) {
  Object.defineProperty(_deps, k, {
    configurable: true,
    enumerable: true,
    get() { throw new Error(`versions.js: dep "${k}" was not configured. Call setVersionsDeps() first.`); },
  });
}

export const setVersionsDeps = (deps) => {
  for (const k of Object.keys(deps)) {
    Object.defineProperty(_deps, k, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: deps[k],
    });
  }
};

// ---------------- Version card creation ----------------

const createFavoriteButton = (v, fullId) => {
  const favBtn = document.createElement('div');
  favBtn.className = 'icon-button';

  const favImg = document.createElement('img');
  favImg.alt = 'favorite';

  const fullKey = fullId;

  if (fullKey !== null && fullKey !== undefined) {
    const favs = state.settingsState.favorite_versions || [];
    const isFavInitial = favs.includes(fullKey);
    bindKeyboardActivation(favBtn, {
      ariaLabel: `Toggle favorite for ${String(v && v.display ? v.display : fullKey)}`,
    });
    favBtn.setAttribute('aria-pressed', isFavInitial ? 'true' : 'false');

    favImg.src = isFavInitial
      ? 'assets/images/filled_favorite.png'
      : 'assets/images/unfilled_favorite.png';

    favBtn.addEventListener('mouseenter', () => {
      const listFav = state.settingsState.favorite_versions || [];
      if (!listFav.includes(fullKey)) {
        favImg.src = 'assets/images/filled_favorite.png';
      }
    });

    favBtn.addEventListener('mouseleave', () => {
      const listFav = state.settingsState.favorite_versions || [];
      favImg.src = listFav.includes(fullKey)
        ? 'assets/images/filled_favorite.png'
        : 'assets/images/unfilled_favorite.png';
    });

    favBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const listFav = state.settingsState.favorite_versions || [];
      const isFav = listFav.includes(fullKey);

      state.settingsState.favorite_versions = isFav
        ? listFav.filter((x) => x !== fullKey)
        : [...listFav, fullKey];

      favImg.src = isFav
        ? 'assets/images/unfilled_favorite.png'
        : 'assets/images/filled_favorite.png';

      favBtn.setAttribute('aria-pressed', isFav ? 'false' : 'true');

      await api('/api/settings', 'POST', {
        favorite_versions: state.settingsState.favorite_versions.join(', '),
      });
      _deps.renderAllVersionSections();
    });
  } else {
    favImg.src = 'assets/images/filled_favorite.png';
  }

  imageAttachErrorPlaceholder(favImg, 'assets/images/placeholder.png');
  favBtn.appendChild(favImg);

  return favBtn;
};

const showVersionEditModal = (v, draftState = null) => {
  const raw = (v && v.raw && typeof v.raw === 'object') ? v.raw : {};
  const initialDisplayName = String(
    draftState && typeof draftState.displayName === 'string'
      ? draftState.displayName
      : (raw.display_name_override || '')
  ).trim();
  const initialStorageMode = _deps.normalizeVersionStorageOverrideMode(
    draftState && typeof draftState.storageMode === 'string'
      ? draftState.storageMode
      : (raw.storage_override_mode || v.storage_override_mode)
  );
  const initialStoragePath = String(
    draftState && typeof draftState.storagePath === 'string'
      ? draftState.storagePath
      : (raw.storage_override_path || v.storage_override_path || '')
  ).trim();

  let selectedStoragePath = initialStoragePath;
  let imageBase64 =
    draftState && typeof draftState.imageBase64 === 'string'
      ? draftState.imageBase64
      : null;
  let uploadedPreviewDataUrl =
    draftState && typeof draftState.imagePreviewDataUrl === 'string'
      ? draftState.imagePreviewDataUrl
      : '';

  const content = document.createElement('div');
  content.style.cssText = 'display:grid;gap:10px;text-align:left;';

  const makeField = (labelText, controlEl) => {
    const wrap = document.createElement('div');
    wrap.style.marginBottom = '10px';

    const normalizedLabel = String(labelText || '').trim();
    if (normalizedLabel) {
      const label = document.createElement('span');
      label.textContent = normalizedLabel;
      label.style.cssText = 'display:block;font-size:12px;color:#9ca3af;margin-bottom:4px;';
      wrap.appendChild(label);
    }
    wrap.appendChild(controlEl);
    return wrap;
  };

  const createInput = (placeholder = '') => {
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = placeholder;
    input.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;';
    return input;
  };

  const displayNameInput = createInput('Default (none)');
  displayNameInput.maxLength = 128;
  displayNameInput.value = initialDisplayName;

  const storageModeSelect = document.createElement('select');
  storageModeSelect.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;';

  const modeDefaultOption = document.createElement('option');
  modeDefaultOption.value = 'default';
  modeDefaultOption.textContent = 'Default (use Settings rule)';

  const modeGlobalOption = document.createElement('option');
  modeGlobalOption.value = 'global';
  modeGlobalOption.textContent = 'Global';

  const modeVersionOption = document.createElement('option');
  modeVersionOption.value = 'version';
  modeVersionOption.textContent = 'Version';

  const modeCustomOption = document.createElement('option');
  modeCustomOption.value = 'custom';
  modeCustomOption.textContent = 'Custom (version-specific folder)';

  storageModeSelect.appendChild(modeDefaultOption);
  storageModeSelect.appendChild(modeGlobalOption);
  storageModeSelect.appendChild(modeVersionOption);
  storageModeSelect.appendChild(modeCustomOption);
  storageModeSelect.value = initialStorageMode;

  const customStorageControls = document.createElement('div');
  customStorageControls.style.cssText =
    'display:flex;align-items:center;gap:8px;min-width:0;text-align:left;';

  const selectStorageFolderBtn = document.createElement('button');
  selectStorageFolderBtn.type = 'button';
  selectStorageFolderBtn.textContent = 'Select folder';

  const storagePathLabel = document.createElement('span');
  storagePathLabel.id = "settings-storage-path";

  const renderStoragePathLabel = () => {
    const text = String(selectedStoragePath || '').trim();
    if (text) {
      storagePathLabel.textContent = text;
      storagePathLabel.style.color = '#cbd5e1';
      storagePathLabel.style.fontStyle = 'normal';
    } else {
      storagePathLabel.textContent = 'None';
      storagePathLabel.style.color = '#9ca3af';
      storagePathLabel.style.fontStyle = 'italic';
    }
  };

  renderStoragePathLabel();
  customStorageControls.appendChild(selectStorageFolderBtn);
  customStorageControls.appendChild(storagePathLabel);

  const imgWrap = document.createElement('div');
  imgWrap.style.marginBottom = '10px';
  const imgLabel = document.createElement('label');
  imgLabel.style.cssText = 'display:block;font-size:12px;color:#9ca3af;margin-bottom:4px;';
  imgLabel.textContent = 'Version image file (optional, PNG/JPG)';
  imgWrap.appendChild(imgLabel);

  const imgRow = document.createElement('div');
  imgRow.style.cssText = 'display:grid;gap:8px;justify-items:center;width:100%;';

  const previewFrame = document.createElement('div');
  previewFrame.style.cssText = 'width:min(100%, 260px);aspect-ratio:16 / 9;border:1px solid #1f2937;display:flex;align-items:center;justify-content:center;background:#111;overflow:hidden;';

  const imgPreview = document.createElement('img');
  imgPreview.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block;background:#111;';

  const imgInput = document.createElement('input');
  imgInput.type = 'file';
  imgInput.accept = 'image/png,image/jpeg';
  imgInput.style.display = 'none';

  const imgPickBtn = document.createElement('button');
  imgPickBtn.type = 'button';
  imgPickBtn.textContent = 'Choose file';

  const imgPickLabel = document.createElement('div');
  imgPickLabel.style.cssText =
    'font-size:12px;color:#9ca3af;max-width:min(100%, 260px);overflow-wrap:anywhere;text-align:center;font-style:italic;';
  imgPickLabel.textContent = 'No file chosen';

  const renderImgPickLabel = () => {
    const file = imgInput.files && imgInput.files[0];
    if (file && file.name) {
      imgPickLabel.textContent = file.name;
      imgPickLabel.style.color = '#cbd5e1';
      imgPickLabel.style.fontStyle = 'normal';
    } else {
      imgPickLabel.textContent = 'No file chosen';
      imgPickLabel.style.color = '#9ca3af';
      imgPickLabel.style.fontStyle = 'italic';
    }
  };

  imgPickBtn.addEventListener('click', () => {
    imgInput.click();
  });

  let targetImageRatio = 16 / 9;

  const getSafeTargetRatio = () => {
    return Number.isFinite(targetImageRatio) && targetImageRatio > 0.2 && targetImageRatio < 10
      ? targetImageRatio
      : (16 / 9);
  };

  const readImageDataUrl = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const result = e && e.target ? e.target.result : null;
        if (typeof result === 'string') {
          resolve(result);
        } else {
          reject(new Error('Failed to read image data'));
        }
      };
      reader.onerror = () => reject(new Error('Failed to read image file'));
      reader.readAsDataURL(file);
    });
  };

  const loadImageElement = (dataUrl) => {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('Invalid image file'));
      img.src = dataUrl;
    });
  };

  const resizeImageToDisplayRatio = async (file) => {
    const sourceDataUrl = await readImageDataUrl(file);
    const sourceImg = await loadImageElement(sourceDataUrl);

    const srcW = Number(sourceImg.naturalWidth || sourceImg.width || 0);
    const srcH = Number(sourceImg.naturalHeight || sourceImg.height || 0);
    if (srcW <= 0 || srcH <= 0) {
      throw new Error('Could not read image dimensions');
    }

    const ratio = getSafeTargetRatio();
    const maxOutputWidth = 1280;
    const outW = Math.max(1, Math.min(maxOutputWidth, srcW));
    const outH = Math.max(1, Math.round(outW / ratio));

    const canvas = document.createElement('canvas');
    canvas.width = outW;
    canvas.height = outH;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('Canvas context unavailable');
    }
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';

    // Keep the whole source image visible while fitting the target display ratio.
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, outW, outH);

    const drawScale = Math.min(outW / srcW, outH / srcH);
    const drawW = Math.max(1, Math.round(srcW * drawScale));
    const drawH = Math.max(1, Math.round(srcH * drawScale));
    const drawX = Math.floor((outW - drawW) / 2);
    const drawY = Math.floor((outH - drawH) / 2);
    ctx.drawImage(sourceImg, 0, 0, srcW, srcH, drawX, drawY, drawW, drawH);

    return canvas.toDataURL('image/png');
  };

  const updatePreviewAspect = () => {
    const ratio = getSafeTargetRatio();
    previewFrame.style.aspectRatio = `${ratio}`;
  };

  const refreshPreview = () => {
    updatePreviewAspect();

    if (uploadedPreviewDataUrl) {
      detachVersionImageFallbackHandler(imgPreview);
      imgPreview.src = uploadedPreviewDataUrl;
      return;
    }

    applyVersionImageWithFallback(imgPreview, {
      imageUrl: '',
      category: v.category,
      folder: v.folder,
      placeholder: 'assets/images/version_placeholder.png',
    });
  };

  imgPreview.addEventListener('load', () => {
    const nw = Number(imgPreview.naturalWidth || 0);
    const nh = Number(imgPreview.naturalHeight || 0);
    if (nw > 0 && nh > 0) {
      targetImageRatio = nw / nh;
      updatePreviewAspect();
    }
  });

  refreshPreview();

  imgInput.addEventListener('change', async () => {
    renderImgPickLabel();
    const file = imgInput.files && imgInput.files[0];
    if (!file) {
      imageBase64 = null;
      uploadedPreviewDataUrl = '';
      errorText.textContent = '';
      refreshPreview();
      return;
    }

    errorText.textContent = '';
    try {
      const resizedDataUrl = await resizeImageToDisplayRatio(file);
      const commaAt = resizedDataUrl.indexOf(',');
      imageBase64 = commaAt >= 0 ? resizedDataUrl.slice(commaAt + 1) : null;
      uploadedPreviewDataUrl = resizedDataUrl;
      detachVersionImageFallbackHandler(imgPreview);
      imgPreview.src = resizedDataUrl;
    } catch (err) {
      imageBase64 = null;
      uploadedPreviewDataUrl = '';
      refreshPreview();
      errorText.textContent = (err && err.message) || 'Failed to process selected image.';
    }
  });

  selectStorageFolderBtn.addEventListener('click', async () => {
    selectStorageFolderBtn.disabled = true;
    errorText.textContent = '';
    try {
      const res = await api('/api/storage-directory/select', 'POST', {
        current_path: selectedStoragePath,
        save_to_settings: false,
      });

      if (res && res.cancelled) {
        return;
      }

      if (!res || res.ok !== true) {
        errorText.textContent =
          (res && (res.error || res.message)) ||
          'Failed to select a custom storage directory.';
        return;
      }

      selectedStoragePath = String(res.path || '').trim();
      renderStoragePathLabel();
    } catch (err) {
      errorText.textContent =
        (err && err.message) || 'Failed to open folder picker.';
    } finally {
      selectStorageFolderBtn.disabled = false;
    }
  });

  previewFrame.appendChild(imgPreview);
  imgRow.appendChild(previewFrame);
  imgRow.appendChild(imgPickBtn);
  imgRow.appendChild(imgPickLabel);
  imgRow.appendChild(imgInput);
  imgWrap.appendChild(imgRow);

  const errorText = document.createElement('div');
  errorText.style.cssText = 'min-height:16px;font-size:12px;color:#f87171;';

  const syncStoragePathState = () => {
    const mode = _deps.normalizeVersionStorageOverrideMode(storageModeSelect.value);
    const customSelected = mode === 'custom';
    customStorageControls.style.display = customSelected ? 'flex' : 'none';

    if (!customSelected) {
      errorText.textContent = '';
    }
  };

  storageModeSelect.addEventListener('change', syncStoragePathState);
  syncStoragePathState();

  const captureDraftState = () => ({
    displayName: String(displayNameInput.value || '').trim(),
    storageMode: _deps.normalizeVersionStorageOverrideMode(storageModeSelect.value),
    storagePath: String(selectedStoragePath || '').trim(),
    imageBase64: imageBase64 || null,
    imagePreviewDataUrl: uploadedPreviewDataUrl || '',
  });

  content.appendChild(makeField('Display name', displayNameInput));
  content.appendChild(makeField('Storage directory', storageModeSelect));
  content.appendChild(makeField('', customStorageControls));
  content.appendChild(imgWrap);
  content.appendChild(errorText);

  showMessageBox({
    title: `Edit Version - ${v.category}/${v.folder}`,
    customContent: content,
    buttons: [
      {
        label: 'Save',
        classList: ['primary'],
        closeOnClick: false,
        onClick: async (_values, controls) => {
          const nextDisplayName = String(displayNameInput.value || '').trim();
          const nextStorageMode = _deps.normalizeVersionStorageOverrideMode(storageModeSelect.value);
          let nextStoragePath = String(selectedStoragePath || '').trim();

          errorText.textContent = '';

          if (nextStorageMode === 'custom') {
            if (!nextStoragePath) {
              errorText.textContent = 'A custom storage folder is required when Custom mode is selected.';
              return;
            }

            const validation = await api('/api/storage-directory/validate', 'POST', {
              path: nextStoragePath,
            });

            if (!validation || validation.ok !== true) {
              errorText.textContent =
                (validation && (validation.error || validation.message)) ||
                'The selected custom storage folder is invalid.';
              return;
            }

            nextStoragePath = String(validation.path || nextStoragePath).trim();
            selectedStoragePath = nextStoragePath;
            renderStoragePathLabel();
          } else {
            nextStoragePath = '';
          }

          const res = await api('/api/version/edit', 'POST', {
            category: v.category,
            folder: v.folder,
            display_name: nextDisplayName,
            image_data: imageBase64 || null,
            storage_override_mode: nextStorageMode,
            storage_override_path: nextStoragePath,
          });

          if (!res || res.ok !== true) {
            errorText.textContent =
              (res && (res.error || res.message)) ||
              'Failed to save version settings.';
            return;
          }

          bumpTextureRevision();
          controls.close();
          await _deps.init();
        },
      },
      {
        label: 'Reset all',
        classList: ['danger'],
        closeOnClick: false,
        onClick: () => {
          const snapshot = captureDraftState();

          showMessageBox({
            title: 'Reset All Version Settings',
            message:
              'This will reset the display name, custom image, and storage directory override to default values. Continue?',
            buttons: [
              {
                label: 'Reset All',
                classList: ['danger'],
                closeOnClick: false,
                onClick: async (_values, controls) => {
                  const res = await api('/api/version/edit', 'POST', {
                    category: v.category,
                    folder: v.folder,
                    reset_all: true,
                  });

                  if (!res || res.ok !== true) {
                    controls.close();
                    showMessageBox({
                      title: 'Reset Failed',
                      message:
                        (res && (res.error || res.message)) ||
                        'Failed to reset version settings.',
                      buttons: [
                        {
                          label: 'Back',
                          onClick: () => showVersionEditModal(v, snapshot),
                        },
                      ],
                    });
                    return;
                  }

                  bumpTextureRevision();
                  controls.close();
                  await _deps.init();
                },
              },
              {
                label: 'Cancel',
                onClick: () => showVersionEditModal(v, snapshot),
              },
            ],
          });
        },
      },
      { label: 'Cancel' },
    ],
  });
};

const createEditButton = (v) => {
  const editBtn = document.createElement('div');
  editBtn.className = 'icon-button';
  bindKeyboardActivation(editBtn, {
    ariaLabel: `Edit version ${String(v && v.display ? v.display : `${v.category}/${v.folder}`)}`,
  });

  const editImg = document.createElement('img');
  editImg.alt = 'edit';
  editImg.src = 'assets/images/unfilled_pencil.png';
  imageAttachErrorPlaceholder(editImg, 'assets/images/placeholder.png');
  editBtn.appendChild(editImg);

  editBtn.addEventListener('mouseenter', () => {
    editImg.src = 'assets/images/filled_pencil.png';
  });
  editBtn.addEventListener('mouseleave', () => {
    editImg.src = 'assets/images/unfilled_pencil.png';
  });

  editBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    showVersionEditModal(v);
  });

  return editBtn;
};

export const pruneVersionsBulkSelection = () => {
  if (!state.versionsBulkState.enabled) return;
  const installedKeys = new Set(
    state.versionsList
      .filter((item) => item.installed && !item.installing)
      .map((item) => `${item.category}/${item.folder}`)
  );

  const next = new Set();
  state.versionsBulkState.selected.forEach((key) => {
    if (installedKeys.has(key)) next.add(key);
  });
  state.versionsBulkState.selected = next;
};

export const updateVersionsBulkActionsUI = () => {
  const toggleBtn = getEl('versions-bulk-toggle-btn');
  const deleteBtn = getEl('versions-bulk-delete-btn');
  const count = state.versionsBulkState.selected.size;

  if (toggleBtn) {
    toggleBtn.textContent = state.versionsBulkState.enabled ? 'Cancel Bulk' : 'Bulk Select';
    toggleBtn.className = state.versionsBulkState.enabled ? 'primary' : 'mild';
  }

  if (deleteBtn) {
    deleteBtn.classList.toggle('hidden', !state.versionsBulkState.enabled);
    deleteBtn.textContent = `Delete Selected (${count})`;
    deleteBtn.disabled = count === 0;
  }

  refreshActionOverflowMenus();
};

export const setVersionsBulkMode = (enabled) => {
  const shouldEnable = !!enabled;
  state.versionsBulkState.enabled = shouldEnable;
  if (!shouldEnable) {
    state.versionsBulkState.selected = new Set();
  }
  updateVersionsBulkActionsUI();
  applyBulkModeToInstalledCards();
};

const applyBulkModeToInstalledCards = () => {
  const enabled = state.versionsBulkState.enabled;
  $$('.version-card.section-installed').forEach((card) => {
    const fullId = card.getAttribute('data-full-id') || '';
    let checkbox = card.querySelector(':scope > input.bulk-select-checkbox');

    if (enabled) {
      const isSelected = state.versionsBulkState.selected.has(fullId);
      card.classList.add('bulk-select-active');
      card.classList.toggle('bulk-selected', isSelected);

      if (!checkbox) {
        checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'bulk-select-checkbox';
        checkbox.title = 'Select version for bulk actions';
        checkbox.setAttribute('tabindex', '-1');
        checkbox.addEventListener('click', (e) => {
          e.stopPropagation();
        });
        checkbox.addEventListener('change', (e) => {
          e.stopPropagation();
          toggleVersionBulkSelection(fullId);
        });
        card.insertBefore(checkbox, card.firstChild);
      }
      checkbox.checked = isSelected;
    } else {
      card.classList.remove('bulk-select-active');
      card.classList.remove('bulk-selected');
      if (checkbox) checkbox.remove();
    }
  });
};

const toggleVersionBulkSelection = (versionKey) => {
  if (!state.versionsBulkState.enabled || !versionKey) return;
  if (state.versionsBulkState.selected.has(versionKey)) {
    state.versionsBulkState.selected.delete(versionKey);
  } else {
    state.versionsBulkState.selected.add(versionKey);
  }
  updateVersionsBulkActionsUI();

  const card = document.querySelector(
    `.version-card.section-installed[data-full-id="${CSS.escape(versionKey)}"]`
  );
  if (card) {
    const isSelected = state.versionsBulkState.selected.has(versionKey);
    card.classList.toggle('bulk-selected', isSelected);
    const checkbox = card.querySelector(':scope > input.bulk-select-checkbox');
    if (checkbox) checkbox.checked = isSelected;
  }
};

const deleteVersion = async (v) => {
  const res = await api('/api/delete', 'POST', {
    category: v.category,
    folder: v.folder,
  });

  if (res && res.ok) {
    const deletedFullId = `${v.category}/${v.folder}`;
    state.versionsList = state.versionsList.filter(
      (item) => `${item.category}/${item.folder}` !== deletedFullId
    );

    state.categoriesList = buildCategoryListFromVersions(state.versionsList);

    if (state.selectedVersion === deletedFullId) {
      state.selectedVersion = null;
      state.selectedVersionDisplay = null;
    }

    state.versionsBulkState.selected.delete(deletedFullId);
    _deps.renderAllVersionSections();
    _deps.updateHomeInfo();
    return true;
  }

  showMessageBox({
    title: 'Error',
    message: (res && res.error) || 'Failed to delete version.',
    buttons: [{ label: 'OK' }],
  });
  return false;
};

export const bulkDeleteSelectedVersions = async ({ skipConfirm = false } = {}) => {
  const keys = Array.from(state.versionsBulkState.selected);
  if (!keys.length) {
    showMessageBox({
      title: 'Bulk Delete Versions',
      message: 'No installed versions',
      buttons: [{ label: 'OK' }],
    });
    return;
  }

  const runDelete = async () => {
    let cancelRequested = false;
    let processed = 0;
    showLoadingOverlay(`Deleting selected versions... (0/${keys.length})`, {
      buttons: [
        {
          label: 'Cancel',
          classList: ['danger'],
          closeOnClick: false,
          onClick: (_values, controls) => {
            if (cancelRequested) return;
            cancelRequested = true;
            controls.update({
              message: 'Cancelling bulk delete after the current version finishes...',
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
      const splitAt = key.indexOf('/');
      if (splitAt <= 0 || splitAt >= key.length - 1) {
        failures.push(`${key} (invalid key)`);
        processed += 1;
        setLoadingOverlayText(`Deleting selected versions... (${processed}/${keys.length})`);
        continue;
      }

      const category = key.slice(0, splitAt);
      const folder = key.slice(splitAt + 1);

      try {
        const res = await api('/api/delete', 'POST', { category, folder });
        if (res && res.ok) {
          deleted += 1;
        } else {
          failures.push(`${key}: ${(res && res.error) || 'unknown error'}`);
        }
      } catch (err) {
        failures.push(`${key}: ${(err && err.message) || 'request failed'}`);
      }
      processed += 1;
      setLoadingOverlayText(`Deleting selected versions... (${processed}/${keys.length})`);
    }

    hideLoadingOverlay();
    setVersionsBulkMode(false);
    await _deps.init();

    if (cancelRequested) {
      showMessageBox({
        title: 'Bulk Delete Cancelled',
        message: `Deleted ${deleted} version${deleted !== 1 ? 's' : ''} before cancellation.${failures.length ? `<br><br>Failures: ${failures.length}` : ''}`,
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    if (!failures.length) {
      showMessageBox({
        title: 'Bulk Delete Complete',
        message: `Deleted ${deleted} version${deleted !== 1 ? 's' : ''}.`,
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    const preview = failures.slice(0, 8).join('<br>');
    const more = failures.length > 8 ? `<br>...and ${failures.length - 8} more.` : '';
    showMessageBox({
      title: 'Bulk Delete Finished With Errors',
      message: `Deleted ${deleted} version${deleted !== 1 ? 's' : ''}.<br><br>Failures:<br>${preview}${more}`,
      buttons: [{ label: 'OK' }],
    });
  };

  if (skipConfirm || state.isShiftDown) {
    await runDelete();
    return;
  }

  showMessageBox({
    title: 'Bulk Delete Versions',
    message: `Delete ${keys.length} selected version${keys.length !== 1 ? 's' : ''}?<br><i>This cannot be undone!</i>`,
    buttons: [
      {
        label: 'Delete',
        classList: ['danger'],
        onClick: runDelete,
      },
      { label: 'Cancel' },
    ],
  });
};

const createDeleteButton = (v) => {
  const delBtn = document.createElement('div');
  delBtn.className = 'icon-button';
  bindKeyboardActivation(delBtn, {
    ariaLabel: `Delete version ${String(v && v.display ? v.display : `${v.category}/${v.folder}`)}`,
  });

  const delImg = document.createElement('img');
  delImg.alt = 'delete';
  delImg.src = 'assets/images/unfilled_delete.png';
  imageAttachErrorPlaceholder(delImg, 'assets/images/placeholder.png');
  delBtn.appendChild(delImg);

  delBtn.addEventListener('mouseenter', () => {
    delImg.src = 'assets/images/filled_delete.png';
  });
  delBtn.addEventListener('mouseleave', () => {
    delImg.src = 'assets/images/unfilled_delete.png';
  });

  delBtn.addEventListener('click', (e) => {
    e.stopPropagation();

    if (state.versionsBulkState.enabled) {
      toggleVersionBulkSelection(`${v.category}/${v.folder}`);
      return;
    }

    if (isShiftDelete(e)) {
      deleteVersion(v);
      return;
    }

    showMessageBox({
      title: 'Delete Version',
      message: `Are you sure you want to permanently delete ${v.category}/${v.folder}?<br><i>This cannot be undone!</i>`,
      buttons: [
        {
          label: 'Yes',
          classList: ['danger'],
          onClick: () => deleteVersion(v),
        },
        { label: 'No' },
      ],
    });
  });

  return delBtn;
};

// ============ MOD LOADER UI ============

const createAddLoaderButton = (v) => {
  const loaderBtn = document.createElement('div');
  loaderBtn.className = 'icon-button';
  bindKeyboardActivation(loaderBtn, {
    ariaLabel: `Manage loaders for ${String(v && v.display ? v.display : `${v.category}/${v.folder}`)}`,
  });

  const loaderImg = document.createElement('img');
  loaderImg.alt = 'add loader';
  loaderImg.src = 'assets/images/unfilled_plus.png';
  imageAttachErrorPlaceholder(loaderImg, 'assets/images/placeholder.png');
  loaderBtn.appendChild(loaderImg);

  loaderBtn.addEventListener('mouseenter', () => {
    loaderImg.src = 'assets/images/filled_plus.png';
  });
  loaderBtn.addEventListener('mouseleave', () => {
    loaderImg.src = 'assets/images/unfilled_plus.png';
  });

  loaderBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    showLoadingOverlay();
    try {
      await showLoaderManagementModal(v);
    } finally {
      hideLoadingOverlay();
    }
  });

  return loaderBtn;
};

const showLoaderManagementModal = async (v) => {
  // Fetch available and installed loaders
  try {
    const loaderData = await api(`/api/loaders/${v.category.toLowerCase()}/${v.folder}`);
    if (!loaderData || !loaderData.ok) {
      showMessageBox({
        title: 'Error',
        message: 'Failed to load loaders information.',
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    const installed = loaderData.installed || {};
    const available = loaderData.available || {};
    const availableLoaderTypes = LOADER_UI_ORDER.filter(
      (loaderType) => Array.isArray(available[loaderType]) && available[loaderType].length > 0
    );

    // Create enhanced UI with loader cards
    let html = `
      <div style="max-height: 500px; overflow-y: auto; padding: 10px;">
        <div style="margin-bottom: 20px;">
          <h4 style="color: #fff; margin-top: 0; margin-bottom: 10px; font-size: 12px; letter-spacing: 1px;">
            Installed Loaders
          </h4>
          <div style="display: grid; gap: 8px;" id="installed-loaders-container">
    `;

    const installedLoaderTypes = LOADER_UI_ORDER.filter(
      (loaderType) => Array.isArray(installed[loaderType]) && installed[loaderType].length > 0
    );

    if (installedLoaderTypes.length === 0) {
      html += `<p style="color:#999;font-size:12px;font-style:italic;">No loaders installed</p>`;
    } else {
      installedLoaderTypes.forEach((loaderType) => {
        const loaderUi = getLoaderUi(loaderType);
        installed[loaderType].forEach((loader) => {
          html += `
            <div style="background:#222;border-left:3px solid ${loaderUi.accent};padding:7px 10px;display:flex;justify-content:space-between;align-items:center;gap:12px;min-height:38px;">
              <div style="min-width:0;line-height:1.15;text-align:left;">
                <div style="color:${loaderUi.accent};font-weight:bold;margin:0 0 2px 0;font-size:14px;letter-spacing:0;">${loaderUi.name}</div>
                <span style="color:#aaa; font-size: 12px;">${loader.version}</span>
                <span style="color:#666; font-size: 11px;"> - ${loader.size_display || 'Unknown size'}</span>
              </div>
              <button type="button" class="loader-delete-btn" style="width: 24px; height: 24px; cursor: pointer; background: transparent; border: none; padding: 0; display: flex; align-items: center; justify-content: center;" data-loader-type="${loaderType}" data-loader-version="${loader.version}" aria-label="Delete ${loaderUi.name} ${loader.version}" title="Delete ${loaderUi.name} ${loader.version}">
                <img src="assets/images/unfilled_delete.png" alt="delete" style="width: 100%; height: 100%;">
              </button>
            </div>
          `;
        });
      });
    }

    html += `
          </div>
        </div>

        <div>
          <h4 style="color: #fff; margin-top: 0; margin-bottom: 10px; font-size: 12px; letter-spacing: 1px;">
            Add New Loader
          </h4>
          <div style="display:grid;gap:8px;">
            ${availableLoaderTypes.length === 0 ? `
              <p style="color:#999;font-size:12px;font-style:italic;">No additional loaders available for this version</p>
            ` : availableLoaderTypes.map((loaderType) => {
              const loaderUi = getLoaderUi(loaderType);
              return `
                <button type="button" class="${loaderUi.buttonClass}" data-action="install-${loaderType}">
                  <div style="font-size:15px;font-weight:bold;margin-bottom:4px;">${loaderUi.name}</div>
                  <div style="font-size:9px;opacity:75%;"><b>${loaderUi.description}</b><br><i>${loaderUi.subtitle}</i></div>
                </button>
              `;
            }).join('')}
          </div>
        </div>
      </div>
    `;

    showMessageBox({
      title: `Mod Loaders - ${v.display}`,
      message: html,
      buttons: [{ label: 'Close' }],
    });

    // Add click handlers after modal is shown
    setTimeout(() => {
      // Add delete button handlers
      const deleteButtons = document.querySelectorAll('.loader-delete-btn');
      deleteButtons.forEach(btn => {
        const loaderType = btn.getAttribute('data-loader-type');
        const loaderVersion = btn.getAttribute('data-loader-version');
        const imgEl = btn.querySelector('img');

        btn.addEventListener('mouseenter', () => {
          imgEl.src = 'assets/images/filled_delete.png';
        });
        btn.addEventListener('mouseleave', () => {
          imgEl.src = 'assets/images/unfilled_delete.png';
        });
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          deleteLoaderVersion(v, loaderType, loaderVersion, { skipConfirm: isShiftDelete(e) });
        });
      });

      availableLoaderTypes.forEach((loaderType) => {
        const card = document.querySelector(`[data-action="install-${loaderType}"]`);
        if (!card) return;
        card.addEventListener('click', (e) => {
          e.preventDefault();
          showLoaderVersionSelector(v, loaderType);
        });
      });
    }, 100);
  } catch (err) {
    console.error('Failed to fetch loaders:', err);
    showMessageBox({
      title: 'Error',
      message: 'Failed to load loaders information.',
      buttons: [{ label: 'OK' }],
    });
  }
};

const showLoaderVersionSelector = async (v, loaderType) => {
  const loaderName = getLoaderUi(loaderType).name;
  try {
    const loaderData = await api(`/api/loaders/${v.category.toLowerCase()}/${v.folder}`);
    if (!loaderData || !loaderData.ok) {
      showMessageBox({
        title: 'Error',
        message: `Failed to fetch available ${loaderName} versions.`,
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    const available = loaderData.available || {};
    const allVersions = available[loaderType] || [];
    const totalAvailable = (loaderData.total_available || {})[loaderType] || allVersions.length;

    if (!allVersions || allVersions.length === 0) {
      showMessageBox({
        title: `Install ${loaderName}`,
        message: `No ${loaderName} versions available for ${v.display}.`,
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    // Pagination state
    let displayedCount = 15;
    let selectedLoaderVersion = allVersions[0]?.version || '';

    const renderVersionList = (versions, selected) => {
      let html = `<div style="display: grid; gap: 8px; max-height: 400px; overflow-y: auto; padding: 10px 0;">`;

      versions.forEach((ver, idx) => {
        const isRecommended = idx === 0;
        const isSelected = ver.version === selected;

        var btnClass = '';
        var metaLabel = ' ';

        if (isRecommended && isSelected) {
          btnClass = 'primary'
          metaLabel += '<i>(Selected, <b>Recommended</b>)</i>';
        } else if (isRecommended) {
          metaLabel += '<i>(<b>Recommended</b>)</i>';
        } else if (isSelected) {
          btnClass = 'important'
          metaLabel += '<i>(Selected)</i>';
        };

        html += `
          <button type="button" class="version-btn ${btnClass}" data-version="${ver.version}" aria-pressed="${isSelected ? 'true' : 'false'}">
            <div><b>${ver.version}</b>${metaLabel}</div>
          </button>
        `;
      });

      html += '</div>';
      return html;
    };

    const buildMessage = () => {
      const displayedVersions = allVersions.slice(0, displayedCount);
      const hasMore = displayedCount < totalAvailable;

      let msg = `
        <div>
          <p style="margin-top: 0; color: #aaa; font-size: 12px; margin-bottom: 12px;">
            Select a ${loaderName} version for <b>${v.display}</b>
          </p>
          ${renderVersionList(displayedVersions, selectedLoaderVersion)}
          <p style="margin-top: 8px; margin-bottom: 8px; color: #666; font-size: 11px;">
            Showing ${displayedVersions.length} of ${totalAvailable} versions
          </p>
      `;

      if (hasMore) {
        msg += `<button id="load-more-btn" type="button" class="default" style="width: 100%; padding: 8px; margin-top: 4px;">Load More...</button>`;
      }

      msg += `</div>`;
      return msg;
    };

    const refreshModal = () => {
      const msgboxText = document.getElementById('msgbox-text');
      if (!msgboxText) {
        return;
      }

      msgboxText.innerHTML = buildMessage();
      attachHandlers();

      const installBtn = document.querySelector('#msgbox-buttons button');
      if (installBtn) {
        installBtn.textContent = `Install ${selectedLoaderVersion || allVersions[0]?.version || 'Selected Version'}`;
      }
    };

    const versionButtons = [
      {
        label: `Install ${selectedLoaderVersion || allVersions[0]?.version || 'Selected Version'}`,
        classList: ['primary'],
        onClick: () => installLoaderVersion(v, loaderType, selectedLoaderVersion || allVersions[0].version),
      },
      { label: 'Cancel' },
    ];

    const title = `Install ${loaderName} - Select Version`;

    showMessageBox({
      title: title,
      message: buildMessage(),
      buttons: versionButtons,
    });

    const installBtn = document.querySelector('#msgbox-buttons button');
    if (installBtn) {
      installBtn.textContent = `Install ${selectedLoaderVersion || allVersions[0]?.version || 'Selected Version'}`;
    }

    const attachHandlers = () => {
      const versionBtns = document.querySelectorAll('.version-btn');
      versionBtns.forEach(btn => {
        btn.addEventListener('click', () => {
          const ver = btn.getAttribute('data-version');
          if (!ver) {
            return;
          }
          selectedLoaderVersion = ver;
          refreshModal();
        });
      });

      const loadMoreBtn = document.getElementById('load-more-btn');
      if (loadMoreBtn) {
        loadMoreBtn.addEventListener('click', () => {
          displayedCount += 15;
          refreshModal();
        });
      }
    };

    setTimeout(() => {
      attachHandlers();
    }, 100);

  } catch (err) {
    console.error(`Failed to fetch ${loaderType} versions:`, err);
    showMessageBox({
      title: 'Error',
      message: `Failed to fetch available ${loaderName} versions.`,
      buttons: [{ label: 'OK' }],
    });
  }
};

const installLoaderVersion = async (v, loaderType, loaderVersion) => {
  const loaderUi = getLoaderUi(loaderType);
  const loaderName = loaderUi.name;
  const fullId = `${v.category}/${v.folder}`;

  const msgboxOverlay = getEl('msgbox-overlay');
  if (msgboxOverlay) msgboxOverlay.classList.add('hidden');

  const modloaderVersionKey = `${v.category.toLowerCase()}/${v.folder}/modloader-${loaderType}-${loaderVersion}`;
  const installKey = encodeURIComponent(modloaderVersionKey);

  const modloaderEntry = {
    display: `${loaderName} ${loaderVersion}`,
    category: v.category,
    folder: v.folder,
    installed: false,
    installing: true,
    is_remote: false,
    source: 'modloader',
    image_url: loaderUi.image,
    _cardFullId: modloaderVersionKey,
    _installKey: installKey,
    _progressText: 'Starting...',
    _progressOverall: 0,
    _loaderType: loaderType,
    _loaderVersion: loaderVersion,
    _parentVersion: fullId,
  };

  if (!state.versionsList.find(x => x._installKey === installKey)) {
    state.versionsList.push(modloaderEntry);
  }

  _deps.renderAllVersionSections();

  try {
    const installResult = await api('/api/install-loader', 'POST', {
      category: v.category,
      folder: v.folder,
      loader_type: loaderType,
      loader_version: loaderVersion,
    });

    if (installResult && installResult.ok) {
      const installKeyForTracking = installResult.install_key || modloaderVersionKey;
      const encodedInstallKey = encodeURIComponent(installKeyForTracking);

      state.versionsList = state.versionsList.map(x =>
        x._installKey === installKey ? { ...x, _installKey: encodedInstallKey } : x
      );

      _deps.renderAllVersionSections();

      const pollModloaderProgress = () => {
        let vMeta = findVersionByInstallKey(encodedInstallKey);
        if (!vMeta) return;

        const eventSource = new EventSource(`/api/stream/install/${encodedInstallKey}`);

        const cleanup = () => {
          eventSource.close();
          delete state.activeInstallPollers[encodedInstallKey];
        };
        state.activeInstallPollers[encodedInstallKey] = cleanup;

        eventSource.onmessage = async (event) => {
          try {
            const s = JSON.parse(event.data);
            if (!s) return;

            vMeta = findVersionByInstallKey(encodedInstallKey);
            if (!vMeta) {
              cleanup();
              return;
            }

            const pct = s.overall_percent || 0;
            const status = s.status;
            let keepPolling = true;

            if (status === 'downloading' || status === 'installing' || status === 'running' || status === 'starting') {
              vMeta.paused = false;
              const bytesDone = s.bytes_done || 0;
              const bytesTotal = s.bytes_total || 0;
              const wholePct = Math.round(pct);
              let text = '';

              if (bytesTotal > 0) {
                const mbDone = Math.round(bytesDone / (1024 * 1024));
                const mbTotal = Math.round(bytesTotal / (1024 * 1024));
                text = `${wholePct}% (${mbDone} MB / ${mbTotal} MB)`;
              } else {
                text = `${wholePct}%`;
              }

              updateVersionInListByKey(encodedInstallKey, (x) => ({
                ...x,
                paused: false,
                _progressText: text,
                _progressOverall: pct,
              }));

              updateCardProgressUI(vMeta, pct, text, {
                paused: false,
                statusLabel: 'INSTALLING',
                keepInstalling: true,
              });
            } else if (status === 'paused') {
              vMeta.paused = true;
              const text = `${pct}% (paused)`;

              updateVersionInListByKey(encodedInstallKey, (x) => ({
                ...x,
                paused: true,
                _progressText: text,
                _progressOverall: pct,
              }));

              updateCardProgressUI(vMeta, pct, text, {
                paused: true,
                statusLabel: 'PAUSED',
                keepInstalling: true,
              });
            } else if (status === 'installed' || pct >= 100) {
              keepPolling = false;
              updateCardProgressUI(vMeta, 100, 'Installed', { keepInstalling: false });

              state.versionsList = state.versionsList.filter((x) => x._installKey !== encodedInstallKey);
              await _deps.init();
            } else if (status === 'failed' || status === 'error') {
              const errorMsg = s.message || 'Unknown error';
              keepPolling = false;

              state.versionsList = state.versionsList.filter((x) => x._installKey !== encodedInstallKey);
              await _deps.init();
              showMessageBox({
                title: `${loaderName} Install Failed`,
                message: errorMsg,
                buttons: [{ label: 'OK' }],
              });
            } else if (status === 'cancelled') {
              keepPolling = false;
              state.versionsList = state.versionsList.filter((x) => x._installKey !== encodedInstallKey);
              await _deps.init();
            }

            if (!keepPolling) {
              cleanup();
            }
          } catch (error) {
            console.warn('modloader install stream update failed', error);
          }
        };

        eventSource.onerror = (e) => {
          // auto reconnects
        };
      };

      // Start polling for modloader progress
      pollModloaderProgress();
    } else {
      const errorMsg = installResult?.error || 'Unknown error';

      // Mark as failed in the list
      state.versionsList = state.versionsList.map(x =>
        x._installKey === installKey ? { ...x, installing: false, _progressText: `Failed: ${errorMsg}` } : x
      );
      _deps.renderAllVersionSections();
    }
  } catch (err) {
    console.error(`Loader installation error:`, err);

    // Mark as failed in the list
    state.versionsList = state.versionsList.map(x =>
      x._installKey === installKey ? { ...x, installing: false, _progressText: `Failed: ${err.message}` } : x
    );
    _deps.renderAllVersionSections();
  }
};

const deleteLoaderVersion = (v, loaderType, loaderVersion, options = {}) => {
  const loaderName = getLoaderUi(loaderType).name;
  const skipConfirm = !!options.skipConfirm;

  const runDelete = async () => {
    try {
      const deleteResult = await api('/api/delete-loader', 'POST', {
        category: v.category,
        folder: v.folder,
        loader_type: loaderType,
        loader_version: loaderVersion,
      });

      if (deleteResult && deleteResult.ok) {
        invalidateInitialCache();
        setTimeout(() => {
          showLoaderManagementModal(v);
        }, 500);
      } else {
        showMessageBox({
          title: 'Delete Loader Failed',
          message: (deleteResult && deleteResult.error) || 'Unknown error',
          buttons: [{ label: 'OK' }],
        });
      }
    } catch (err) {
      console.error('Loader deletion error:', err);
      showMessageBox({
        title: 'Delete Loader Failed',
        message: (err && err.message) || 'Unexpected loader deletion error.',
        buttons: [{ label: 'OK' }],
      });
    }
  };

  if (skipConfirm || state.isShiftDown) {
    runDelete();
    return;
  }

  showMessageBox({
    title: 'Delete Loader',
    message: `Are you sure you want to delete ${loaderName} ${loaderVersion}?`,
    buttons: [
      { label: 'Cancel' },
      {
        label: 'Delete',
        classList: ['danger'],
        onClick: runDelete,
      }
    ],
  });
};

const createBadgeRow = (v, sectionType) => {
  const badgeRow = document.createElement('div');
  badgeRow.className = 'version-badge-row';

  const badgeMain = document.createElement('span');
  badgeMain.className =
      'version-badge ' +
      (sectionType === 'installed'
          ? (v.raw && v.raw.is_imported === true ? 'imported' : 'installed')
          : 'available');

  if (sectionType === 'installing' && v.paused) {
      badgeMain.textContent = 'PAUSED';
      badgeMain.classList.add('paused');
  } else {
      badgeMain.textContent =
          sectionType === 'installed'
              ? (v.raw && v.raw.is_imported === true ? 'IMPORTED' : 'INSTALLED')
              : sectionType === 'installing'
              ? 'INSTALLING'
              : 'AVAILABLE';
  }
  badgeRow.appendChild(badgeMain);

  if (v.is_remote && sectionType === 'available') {
      const badgeSource = document.createElement('span');
      badgeSource.className =
          'version-badge ' +
          (v.source === 'mojang' ? 'official' : 'nonofficial');
    badgeSource.textContent =
      v.source === 'mojang'
        ? 'MOJANG'
        : v.source === 'omniarchive'
        ? 'OMNIARCHIVE'
        : 'PROXY';
      badgeRow.appendChild(badgeSource);
  }

  if ((sectionType === 'installed' && v.raw && v.raw.full_assets === false)||(sectionType === 'installing' && v.full_install === false)) {
      const badgeLite = document.createElement('span');
      badgeLite.className = 'version-badge lite';
      badgeLite.textContent = 'LITE';
      badgeRow.appendChild(badgeLite);
  }

  const sizeLabel = _deps.formatSizeBadge(v);
  if (sizeLabel) {
      const badgeSize = document.createElement('span');
      badgeSize.className = 'version-badge size';
      badgeSize.textContent = sizeLabel;
      badgeRow.appendChild(badgeSize);
  }

  return badgeRow;
};

const createAvailableActions = (v, card) => {
  const actions = document.createElement('div');
  actions.className = 'version-actions';

  const installBtn = document.createElement('button');
  const isLowDataMode = state.settingsState.low_data_mode === "1";
  const isRedownload = !!(v.redownload_available || v.installed_local);
  installBtn.textContent = isRedownload ? 'Redownload' : (isLowDataMode ? 'Quick Download' : 'Download');
  installBtn.className = isRedownload ? 'mild' : (isLowDataMode ? 'important' : 'primary');

  installBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const fullDownload = isRedownload || isLowDataMode === false || state.settingsState.low_data_mode !== "1";
      await handleInstallClick(v, card, installBtn, fullDownload, { forceRedownload: isRedownload });
  });

  actions.appendChild(installBtn);
  return actions;
};

const createInstallingActions = (v) => {
  const actions = document.createElement('div');
  actions.className = 'version-actions';

  const pauseBtn = document.createElement('button');
  pauseBtn.className = 'pause-resume-btn mild';
  pauseBtn.textContent = v.paused ? 'Resume' : 'Pause';
  pauseBtn.classList.remove(v.paused ? 'mild' : 'primary');
  pauseBtn.classList.add(v.paused ? 'primary' : 'mild');

  pauseBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!v._installKey) return;

    try {
      const st = await api(`/api/status/${v._installKey}`);
      const cur = ((st && st.status) || '').toLowerCase();
      if (cur === 'paused') {
        // Resuming
        await resumeInstallForVersionKey(v._installKey);
        // Update UI immediately
        updateVersionInListByKey(v._installKey, (x) => ({
          ...x,
          paused: false,
          _progressText: 'Resuming...',
        }));
        _deps.renderAllVersionSections();
      } else {
        // Pausing
        await pauseInstallForVersionKey(v._installKey);
        // Update UI immediately
        updateVersionInListByKey(v._installKey, (x) => ({
          ...x,
          paused: true,
          _progressText: 'Paused',
        }));
        _deps.renderAllVersionSections();
      }
      // Trigger immediate poll after pause/resume
      setTimeout(() => {
        const vMeta = findVersionByInstallKey(v._installKey);
        if (vMeta) {
          // Delete old poller completely before restarting
          if (state.activeInstallPollers[v._installKey]) {
            if (typeof state.activeInstallPollers[v._installKey] === 'function') {
              state.activeInstallPollers[v._installKey]();
            } else {
              clearTimeout(state.activeInstallPollers[v._installKey]);
            }
            delete state.activeInstallPollers[v._installKey];
          }
          // Re-run polling immediately
          startPollingForInstall(v._installKey, vMeta);
        }
      }, 100);
    } catch (err) {
      console.warn('pause/resume action failed', err);
    }
  });

  actions.appendChild(pauseBtn);

  const cancelBtn = document.createElement('button');
  cancelBtn.textContent = 'Cancel';

  cancelBtn.addEventListener('click', (e) => {
    e.stopPropagation();

    showMessageBox({
      title: 'Cancel Download',
      message: `Do you want to cancel downloading ${v.category}/${v.folder}?`,
      buttons: [
        {
          label: 'Yes',
          classList: ['danger'],
          onClick: async () => {
            if (!v._installKey) return;
            await cancelInstallForVersionKey(v._installKey);
            // Trigger immediate poll after cancel
            setTimeout(() => {
              const vMeta = findVersionByInstallKey(v._installKey);
              if (vMeta) {
                _deps.renderAllVersionSections();
              }
            }, 100);
          },
        },
        { label: 'No' },
      ],
    });
  });

  actions.appendChild(cancelBtn);
  return actions;
};

const createProgressElements = (card, v) => {
  const progressBar = document.createElement('div');
  progressBar.className = 'version-progress';

  const fill = document.createElement('div');
  fill.className = 'version-progress-fill';
  progressBar.appendChild(fill);

  const progressText = document.createElement('div');
  progressText.className = 'version-progress-text';
  progressText.textContent = v._progressText || '';
  card.appendChild(progressBar);
  card.appendChild(progressText);

  card._progressFill = fill;
  card._progressTextEl = progressText;

  if (typeof v._progressOverall === 'number') {
    fill.style.width = `${v._progressOverall}%`;
  }
};

export const createVersionCard = (v, sectionType) => {
  const fullId = `${v.category}/${v.folder}`;
  const cardFullId = v._cardFullId || fullId;

  const card = document.createElement('div');
  card.className = 'version-card';
  card.classList.add(`section-${sectionType}`);
  const isInstalledFavorite = sectionType === 'installed'
    && (state.settingsState.favorite_versions || []).includes(fullId);
  const isAvailableRecommended = sectionType === 'available' && !!v.recommended;
  if (isInstalledFavorite || isAvailableRecommended) card.classList.add(isInstalledFavorite ? 'favorite' : (isAvailableRecommended ? 'recent' : ''));
  card.setAttribute('data-full-id', cardFullId);

  if (sectionType === 'installed') {
    bindKeyboardActivation(card, {
      ariaLabel: `Select version ${String(v && v.display ? v.display : fullId)}`,
    });
    card.setAttribute('aria-current', state.selectedVersion === fullId ? 'true' : 'false');
  }

  if (sectionType !== 'installed') {
    card.classList.add('unselectable');
  }

  if (sectionType === 'installed' && state.versionsBulkState.enabled) {
    const isSelected = state.versionsBulkState.selected.has(fullId);
    card.classList.add('bulk-select-active');
    if (isSelected) card.classList.add('bulk-selected');

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'bulk-select-checkbox';
    checkbox.checked = isSelected;
    checkbox.title = 'Select version for bulk actions';
    checkbox.setAttribute('tabindex', '-1');
    checkbox.addEventListener('click', (e) => {
      e.stopPropagation();
    });
    checkbox.addEventListener('change', (e) => {
      e.stopPropagation();
      toggleVersionBulkSelection(fullId);
    });
    card.appendChild(checkbox);
  }

  const img = document.createElement('img');
  img.className = 'version-image';
  img.alt = v.display || '';
  if (v.is_remote) {
    img.src = v.image_url || 'assets/images/version_placeholder.png';
    imageAttachErrorPlaceholder(img, 'assets/images/version_placeholder.png');
  } else {
    applyVersionImageWithFallback(img, {
      imageUrl: v.image_url || '',
      category: v.category,
      folder: v.folder,
      placeholder: 'assets/images/version_placeholder.png',
    });
  }

  const info = document.createElement('div');
  info.className = 'version-info';

  const headerRow = document.createElement('div');
  headerRow.className = 'version-header-row';

  const disp = document.createElement('div');
  disp.className = 'version-display';
  disp.textContent = v.display;

  const folder = document.createElement('div');
  folder.className = 'version-folder';
  folder.textContent = formatCategoryName(v.category);

  const iconsRow = document.createElement('div');
  iconsRow.className = 'version-actions-icons';

  if (sectionType === 'installed') {
    iconsRow.appendChild(createAddLoaderButton(v));
    iconsRow.appendChild(createFavoriteButton(v, fullId));
    iconsRow.appendChild(createEditButton(v));
    iconsRow.appendChild(createDeleteButton(v));
  } else if (sectionType === 'available' && isAvailableRecommended) {
    iconsRow.appendChild(createFavoriteButton(v));
  }

  headerRow.appendChild(disp);
  headerRow.appendChild(iconsRow);

  info.appendChild(headerRow);
  info.appendChild(folder);

  const badgeRow = createBadgeRow(v, sectionType);

  const actions =
    sectionType === 'available'
      ? createAvailableActions(v, card)
      : sectionType === 'installing'
      ? createInstallingActions(v)
      : (() => {
          const a = document.createElement('div');
          a.className = 'version-actions';
          return a;
        })();

  if (sectionType === 'installed') {
    card.addEventListener('click', async () => {
      if (state.versionsBulkState.enabled) {
        toggleVersionBulkSelection(fullId);
        return;
      }

      $$('.version-card').forEach((c) => c.classList.remove('selected'));
      $$('.version-card[aria-current]').forEach((c) =>
        c.setAttribute('aria-current', 'false')
      );
      card.classList.add('selected');
      card.setAttribute('aria-current', 'true');
      state.selectedVersion = fullId;
      state.selectedVersionDisplay = v.display;
      state.settingsState.selected_version = state.selectedVersion;
      _deps.updateHomeInfo();
      await api('/api/settings', 'POST', { selected_version: state.selectedVersion });
    });
  }

  card.appendChild(img);
  card.appendChild(info);
  card.appendChild(badgeRow);
  card.appendChild(actions);
  if (sectionType === 'installing') {
    createProgressElements(card, v);
  }

  wireCardActionArrowNavigation(card);

  return card;
};
