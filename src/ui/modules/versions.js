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
import { t } from './i18n.js';

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

const settingsProfilePayload = (patch = {}) => ({
  ...patch,
  _profile_id: state.profilesState.activeProfile || 'default',
});

const versionCardActionLabel = (actionKey, versionLabel) => t(`versions.actions.${actionKey}Version`, { version: versionLabel });

const getVersionLabel = (v, fallback = '') => String(v && (v.display || `${v.category || ''}/${v.folder || ''}`) || fallback || '').trim();

const getVersionStatusLabel = (status) => {
  const key = String(status || '').trim().toLowerCase();
  if (key === 'imported') return t('versions.status.imported');
  if (key === 'installed') return t('versions.status.installed');
  if (key === 'installing') return t('versions.status.installing');
  if (key === 'paused') return t('versions.status.paused');
  if (key === 'available') return t('versions.status.available');
  if (key === 'lite') return t('versions.status.lite');
  return key ? key.toUpperCase() : '';
};

const getVersionSourceLabel = (source) => {
  const key = String(source || '').trim().toLowerCase();
  if (key === 'mojang') return t('versions.sources.mojang');
  if (key === 'omniarchive') return t('versions.sources.omniarchive');
  if (key === 'proxy') return t('versions.sources.proxy');
  return key ? key.toUpperCase() : t('versions.sources.proxy');
};

const getDownloadButtonLabel = ({ isRedownload = false, isLowDataMode = false } = {}) => {
  if (isRedownload) return t('common.redownload');
  return isLowDataMode ? t('versions.actions.quickDownload') : t('common.download');
};

const getLoaderInstallButtonLabel = (version) => t('versions.loaders.installVersion', { version: version || t('versions.loaders.selectedVersion') });

// ---------------- Version card creation ----------------

const createFavoriteButton = (v, fullId) => {
  const favBtn = document.createElement('div');
  favBtn.className = 'icon-button';

  const favImg = document.createElement('img');
  favImg.alt = t('versions.favoriteAlt');

  const fullKey = fullId;

  if (fullKey !== null && fullKey !== undefined) {
    const favs = state.settingsState.favorite_versions || [];
    const isFavInitial = favs.includes(fullKey);
    bindKeyboardActivation(favBtn, {
      ariaLabel: versionCardActionLabel('toggleFavorite', getVersionLabel(v, fullKey)),
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

      await api('/api/settings', 'POST', settingsProfilePayload({
        favorite_versions: state.settingsState.favorite_versions.join(', '),
      }));
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

  const readDraftOrRaw = (draftKey, rawKey) => String(
    draftState && typeof draftState[draftKey] === 'string'
      ? draftState[draftKey]
      : (raw[rawKey] || v[rawKey] || '')
  ).trim();

  const initialLaunchMinRam = readDraftOrRaw('launchMinRam', 'launch_min_ram');
  const initialLaunchMaxRam = readDraftOrRaw('launchMaxRam', 'launch_max_ram');
  const initialLaunchExtraJvmArgs = readDraftOrRaw('launchExtraJvmArgs', 'launch_extra_jvm_args');
  const initialLaunchJavaPath = readDraftOrRaw('launchJavaPath', 'launch_java_path');
  const initialLaunchResolutionWidth = readDraftOrRaw('launchResolutionWidth', 'launch_resolution_width');
  const initialLaunchResolutionHeight = readDraftOrRaw('launchResolutionHeight', 'launch_resolution_height');
  const initialLaunchFullscreen = readDraftOrRaw('launchFullscreen', 'launch_fullscreen');
  const initialLaunchDemo = readDraftOrRaw('launchDemo', 'launch_demo');

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
      label.style.cssText = 'display:block;font-size:12px;color:var(--color-text-muted);margin-bottom:4px;';
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

  const createCheckbox = (checked = false) => {
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!checked;
    return input;
  };

  const makeInlineCheckbox = (labelText, input) => {
    const label = document.createElement('label');
    label.style.cssText = 'display:flex;align-items:center;gap:8px;color:var(--color-text-secondary-strong);font-size:13px;';
    label.appendChild(input);
    label.appendChild(document.createTextNode(labelText));
    return label;
  };

  const makeLaunchGrid = (...children) => {
    const grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;';
    children.forEach((child) => grid.appendChild(child));
    return grid;
  };

  const displayNameInput = createInput(t('versions.edit.defaultNone'));
  displayNameInput.maxLength = 128;
  displayNameInput.value = initialDisplayName;

  const launchMinRamInput = createInput(t('versions.edit.useGlobal'));
  launchMinRamInput.maxLength = 16;
  launchMinRamInput.value = initialLaunchMinRam;

  const launchMaxRamInput = createInput(t('versions.edit.useGlobal'));
  launchMaxRamInput.maxLength = 16;
  launchMaxRamInput.value = initialLaunchMaxRam;

  const launchExtraJvmArgsInput = createInput(t('versions.edit.useGlobal'));
  launchExtraJvmArgsInput.maxLength = 2048;
  launchExtraJvmArgsInput.value = initialLaunchExtraJvmArgs;

  const launchJavaPathInput = createInput(t('versions.edit.useGlobal'));
  launchJavaPathInput.maxLength = 500;
  launchJavaPathInput.value = initialLaunchJavaPath;

  const launchResolutionWidthInput = createInput(t('versions.edit.useGlobal'));
  launchResolutionWidthInput.maxLength = 5;
  launchResolutionWidthInput.inputMode = 'numeric';
  launchResolutionWidthInput.value = initialLaunchResolutionWidth;

  const launchResolutionHeightInput = createInput(t('versions.edit.useGlobal'));
  launchResolutionHeightInput.maxLength = 5;
  launchResolutionHeightInput.inputMode = 'numeric';
  launchResolutionHeightInput.value = initialLaunchResolutionHeight;

  const launchFullscreenOverrideInput = createCheckbox(initialLaunchFullscreen === '1' || initialLaunchFullscreen === '0');
  const launchFullscreenInput = createCheckbox(initialLaunchFullscreen === '1');
  const launchDemoOverrideInput = createCheckbox(initialLaunchDemo === '1' || initialLaunchDemo === '0');
  const launchDemoInput = createCheckbox(initialLaunchDemo === '1');

  const launchSection = document.createElement('div');
  launchSection.style.cssText = 'display:grid;gap:8px;padding:10px;border:1px solid var(--color-border-muted);background:var(--color-surface-code);';

  const launchTitle = document.createElement('div');
  launchTitle.textContent = t('versions.edit.launchSettings');
  launchTitle.style.cssText = 'font-size:13px;font-weight:700;color:var(--color-text-primary);';

  const launchResolutionRow = document.createElement('div');
  launchResolutionRow.style.cssText = 'display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:8px;align-items:center;';
  const launchResolutionSeparator = document.createElement('span');
  launchResolutionSeparator.textContent = 'x';
  launchResolutionSeparator.style.cssText = 'color:var(--color-text-muted);';
  launchResolutionRow.appendChild(launchResolutionWidthInput);
  launchResolutionRow.appendChild(launchResolutionSeparator);
  launchResolutionRow.appendChild(launchResolutionHeightInput);

  const launchFullscreenRow = document.createElement('div');
  launchFullscreenRow.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:8px;align-items:center;';
  launchFullscreenRow.appendChild(makeInlineCheckbox(t('versions.edit.overrideFullscreen'), launchFullscreenOverrideInput));
  launchFullscreenRow.appendChild(makeInlineCheckbox(t('versions.edit.fullscreen'), launchFullscreenInput));

  const launchDemoRow = document.createElement('div');
  launchDemoRow.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:8px;align-items:center;';
  launchDemoRow.appendChild(makeInlineCheckbox(t('versions.edit.overrideDemoMode'), launchDemoOverrideInput));
  launchDemoRow.appendChild(makeInlineCheckbox(t('versions.edit.demoMode'), launchDemoInput));

  launchSection.appendChild(launchTitle);
  launchSection.appendChild(makeLaunchGrid(
    makeField(t('versions.edit.minimumRamOverride'), launchMinRamInput),
    makeField(t('versions.edit.maximumRamOverride'), launchMaxRamInput)
  ));
  launchSection.appendChild(makeField(t('versions.edit.resolutionOverride'), launchResolutionRow));
  launchSection.appendChild(launchFullscreenRow);
  launchSection.appendChild(launchDemoRow);
  launchSection.appendChild(makeField(t('versions.edit.javaRuntimePathOverride'), launchJavaPathInput));
  launchSection.appendChild(makeField(t('versions.edit.extraJvmArgumentsOverride'), launchExtraJvmArgsInput));

  const storageModeSelect = document.createElement('select');
  storageModeSelect.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;';

  const modeDefaultOption = document.createElement('option');
  modeDefaultOption.value = 'default';
  modeDefaultOption.textContent = t('versions.edit.defaultUseSettingsRule');

  const modeGlobalOption = document.createElement('option');
  modeGlobalOption.value = 'global';
  modeGlobalOption.textContent = t('settings.client.storageGlobal');

  const modeVersionOption = document.createElement('option');
  modeVersionOption.value = 'version';
  modeVersionOption.textContent = t('settings.client.storageVersion');

  const modeCustomOption = document.createElement('option');
  modeCustomOption.value = 'custom';
  modeCustomOption.textContent = t('versions.edit.customVersionFolder');

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
  selectStorageFolderBtn.textContent = t('common.selectFolder');

  const storagePathLabel = document.createElement('span');
  storagePathLabel.id = "settings-storage-path";

  const renderStoragePathLabel = () => {
    const text = String(selectedStoragePath || '').trim();
    if (text) {
      storagePathLabel.textContent = text;
      storagePathLabel.style.color = 'var(--color-text-secondary-strong)';
      storagePathLabel.style.fontStyle = 'normal';
    } else {
      storagePathLabel.textContent = t('common.none');
      storagePathLabel.style.color = 'var(--color-text-muted)';
      storagePathLabel.style.fontStyle = 'italic';
    }
  };

  renderStoragePathLabel();
  customStorageControls.appendChild(selectStorageFolderBtn);
  customStorageControls.appendChild(storagePathLabel);

  const imgWrap = document.createElement('div');
  imgWrap.style.marginBottom = '10px';
  const imgLabel = document.createElement('label');
  imgLabel.style.cssText = 'display:block;font-size:12px;color:var(--color-text-muted);margin-bottom:4px;';
  imgLabel.textContent = t('versions.edit.versionImageFile');
  imgWrap.appendChild(imgLabel);

  const imgRow = document.createElement('div');
  imgRow.style.cssText = 'display:grid;gap:8px;justify-items:center;width:100%;';

  const previewFrame = document.createElement('div');
  previewFrame.style.cssText = 'width:min(100%, 260px);aspect-ratio:16 / 9;border:1px solid var(--color-border-input);display:flex;align-items:center;justify-content:center;background:var(--color-surface-code-block);overflow:hidden;';

  const imgPreview = document.createElement('img');
  imgPreview.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block;background:var(--color-surface-code-block);';

  const imgInput = document.createElement('input');
  imgInput.type = 'file';
  imgInput.accept = 'image/png,image/jpeg';
  imgInput.style.display = 'none';

  const imgPickBtn = document.createElement('button');
  imgPickBtn.type = 'button';
  imgPickBtn.textContent = t('common.chooseFile');

  const imgPickLabel = document.createElement('div');
  imgPickLabel.style.cssText =
    'font-size:12px;color:var(--color-text-muted);max-width:min(100%, 260px);overflow-wrap:anywhere;text-align:center;font-style:italic;';
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
          reject(new Error(t('versions.edit.failedReadImageData')));
        }
      };
      reader.onerror = () => reject(new Error(t('versions.edit.failedReadImageFile')));
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
      errorText.textContent = (err && err.message) || t('versions.edit.failedProcessSelectedImage');
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
          t('versions.edit.failedSelectStorageDirectory');
        return;
      }

      selectedStoragePath = String(res.path || '').trim();
      renderStoragePathLabel();
    } catch (err) {
      errorText.textContent =
        (err && err.message) || t('versions.edit.failedOpenFolderPicker');
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
  errorText.style.cssText = 'min-height:16px;font-size:12px;color:var(--color-error-soft);';

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

  const syncLaunchBooleanStates = () => {
    launchFullscreenInput.disabled = !launchFullscreenOverrideInput.checked;
    launchFullscreenInput.parentElement.style.opacity = launchFullscreenInput.disabled ? '0.55' : '1';
    launchDemoInput.disabled = !launchDemoOverrideInput.checked;
    launchDemoInput.parentElement.style.opacity = launchDemoInput.disabled ? '0.55' : '1';
  };

  launchFullscreenOverrideInput.addEventListener('change', syncLaunchBooleanStates);
  launchDemoOverrideInput.addEventListener('change', syncLaunchBooleanStates);
  syncLaunchBooleanStates();

  [launchMinRamInput, launchMaxRamInput].forEach((input) => {
    input.addEventListener('input', () => {
      input.value = String(input.value || '').replace(/[^0-9KMGTkmgt]/g, '').toUpperCase();
    });
  });

  [launchResolutionWidthInput, launchResolutionHeightInput].forEach((input) => {
    input.addEventListener('input', () => {
      input.value = String(input.value || '').replace(/[^0-9]/g, '').slice(0, 5);
    });
  });

  const captureDraftState = () => ({
    displayName: String(displayNameInput.value || '').trim(),
    storageMode: _deps.normalizeVersionStorageOverrideMode(storageModeSelect.value),
    storagePath: String(selectedStoragePath || '').trim(),
    imageBase64: imageBase64 || null,
    imagePreviewDataUrl: uploadedPreviewDataUrl || '',
    launchMinRam: String(launchMinRamInput.value || '').trim().toUpperCase(),
    launchMaxRam: String(launchMaxRamInput.value || '').trim().toUpperCase(),
    launchExtraJvmArgs: String(launchExtraJvmArgsInput.value || '').trim(),
    launchJavaPath: String(launchJavaPathInput.value || '').trim(),
    launchResolutionWidth: String(launchResolutionWidthInput.value || '').trim(),
    launchResolutionHeight: String(launchResolutionHeightInput.value || '').trim(),
    launchFullscreen: launchFullscreenOverrideInput.checked
      ? (launchFullscreenInput.checked ? '1' : '0')
      : '',
    launchDemo: launchDemoOverrideInput.checked
      ? (launchDemoInput.checked ? '1' : '0')
      : '',
  });

  content.appendChild(makeField(t('versions.edit.displayName'), displayNameInput));
  content.appendChild(makeField(t('versions.edit.storageDirectory'), storageModeSelect));
  content.appendChild(makeField('', customStorageControls));
  content.appendChild(launchSection);
  content.appendChild(imgWrap);
  content.appendChild(errorText);

  showMessageBox({
    title: t('versions.edit.title', { version: `${v.category}/${v.folder}` }),
    customContent: content,
    buttons: [
      {
        label: t('common.save'),
        classList: ['primary'],
        closeOnClick: false,
        onClick: async (_values, controls) => {
          const nextDisplayName = String(displayNameInput.value || '').trim();
          const nextStorageMode = _deps.normalizeVersionStorageOverrideMode(storageModeSelect.value);
          let nextStoragePath = String(selectedStoragePath || '').trim();

          errorText.textContent = '';

          if (nextStorageMode === 'custom') {
            if (!nextStoragePath) {
              errorText.textContent = t('versions.edit.customStorageRequired');
              return;
            }

            const validation = await api('/api/storage-directory/validate', 'POST', {
              path: nextStoragePath,
            });

            if (!validation || validation.ok !== true) {
              errorText.textContent =
                (validation && (validation.error || validation.message)) ||
                t('versions.edit.customStorageInvalid');
              return;
            }

            nextStoragePath = String(validation.path || nextStoragePath).trim();
            selectedStoragePath = nextStoragePath;
            renderStoragePathLabel();
          } else {
            nextStoragePath = '';
          }

          const nextLaunchMinRam = String(launchMinRamInput.value || '').trim().toUpperCase();
          const nextLaunchMaxRam = String(launchMaxRamInput.value || '').trim().toUpperCase();
          const nextLaunchExtraJvmArgs = String(launchExtraJvmArgsInput.value || '').trim();
          const nextLaunchJavaPath = String(launchJavaPathInput.value || '').trim();
          const nextLaunchResolutionWidth = String(launchResolutionWidthInput.value || '').trim();
          const nextLaunchResolutionHeight = String(launchResolutionHeightInput.value || '').trim();
          const nextLaunchFullscreen = launchFullscreenOverrideInput.checked
            ? (launchFullscreenInput.checked ? '1' : '0')
            : 'default';
          const nextLaunchDemo = launchDemoOverrideInput.checked
            ? (launchDemoInput.checked ? '1' : '0')
            : 'default';

          const res = await api('/api/version/edit', 'POST', {
            category: v.category,
            folder: v.folder,
            display_name: nextDisplayName,
            image_data: imageBase64 || null,
            storage_override_mode: nextStorageMode,
            storage_override_path: nextStoragePath,
            launch_min_ram: nextLaunchMinRam,
            launch_max_ram: nextLaunchMaxRam,
            launch_extra_jvm_args: nextLaunchExtraJvmArgs,
            launch_java_path: nextLaunchJavaPath,
            launch_resolution_width: nextLaunchResolutionWidth,
            launch_resolution_height: nextLaunchResolutionHeight,
            launch_fullscreen: nextLaunchFullscreen,
            launch_demo: nextLaunchDemo,
          });

          if (!res || res.ok !== true) {
            errorText.textContent =
              (res && (res.error || res.message)) ||
              t('versions.edit.failedSaveSettings');
            return;
          }

          bumpTextureRevision();
          controls.close();
          await _deps.init();
        },
      },
      {
        label: t('versions.edit.resetAll'),
        classList: ['danger'],
        closeOnClick: false,
        onClick: () => {
          const snapshot = captureDraftState();

          showMessageBox({
            title: t('versions.edit.resetAllTitle'),
            message:
              t('versions.edit.resetAllMessage'),
            buttons: [
              {
                label: t('versions.edit.resetAll'),
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
                      title: t('versions.edit.resetFailedTitle'),
                      message:
                        (res && (res.error || res.message)) ||
                        t('versions.edit.failedResetSettings'),
                      buttons: [
                        {
                          label: t('common.back'),
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
                label: t('common.cancel'),
                onClick: () => showVersionEditModal(v, snapshot),
              },
            ],
          });
        },
      },
      { label: t('common.cancel') },
    ],
  });
};

const createEditButton = (v) => {
  const editBtn = document.createElement('div');
  editBtn.className = 'icon-button';
  bindKeyboardActivation(editBtn, {
    ariaLabel: versionCardActionLabel('edit', getVersionLabel(v)),
  });

  const editImg = document.createElement('img');
  editImg.alt = t('common.edit');
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
    toggleBtn.textContent = state.versionsBulkState.enabled ? t('common.cancelBulk') : t('common.bulkSelect');
    toggleBtn.className = state.versionsBulkState.enabled ? 'primary' : 'mild';
  }

  if (deleteBtn) {
    deleteBtn.classList.toggle('hidden', !state.versionsBulkState.enabled);
    deleteBtn.textContent = t('versions.deleteSelectedCount', { count });
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
        checkbox.title = t('versions.selectForBulkActions');
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
    title: t('common.error'),
    message: (res && res.error) || t('versions.deleteFailed'),
    buttons: [{ label: t('common.ok') }],
  });
  return false;
};

export const bulkDeleteSelectedVersions = async ({ skipConfirm = false } = {}) => {
  const keys = Array.from(state.versionsBulkState.selected);
  if (!keys.length) {
    showMessageBox({
      title: t('versions.bulkDelete.title'),
      message: t('versions.bulkDelete.noInstalledVersions'),
      buttons: [{ label: t('common.ok') }],
    });
    return;
  }

  const runDelete = async () => {
    let cancelRequested = false;
    let processed = 0;
    showLoadingOverlay(t('versions.bulkDelete.deletingProgress', { current: 0, total: keys.length }), {
      buttons: [
        {
          label: t('common.cancel'),
          classList: ['danger'],
          closeOnClick: false,
          onClick: (_values, controls) => {
            if (cancelRequested) return;
            cancelRequested = true;
            controls.update({
              message: t('versions.bulkDelete.cancelling'),
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
        setLoadingOverlayText(t('versions.bulkDelete.deletingProgress', { current: processed, total: keys.length }));
        continue;
      }

      const category = key.slice(0, splitAt);
      const folder = key.slice(splitAt + 1);

      try {
        const res = await api('/api/delete', 'POST', { category, folder });
        if (res && res.ok) {
          deleted += 1;
        } else {
          failures.push(`${key}: ${(res && res.error) || t('common.unknownError')}`);
        }
      } catch (err) {
        failures.push(`${key}: ${(err && err.message) || t('versions.bulkDelete.requestFailed')}`);
      }
      processed += 1;
      setLoadingOverlayText(t('versions.bulkDelete.deletingProgress', { current: processed, total: keys.length }));
    }

    hideLoadingOverlay();
    setVersionsBulkMode(false);
    await _deps.init();

    if (cancelRequested) {
      showMessageBox({
        title: t('versions.bulkDelete.cancelledTitle'),
        message: t(failures.length ? 'versions.bulkDelete.cancelledWithFailures' : 'versions.bulkDelete.cancelledMessage', { deleted, failures: failures.length }),
        buttons: [{ label: t('common.ok') }],
      });
      return;
    }

    if (!failures.length) {
      showMessageBox({
        title: t('versions.bulkDelete.completeTitle'),
        message: t('versions.bulkDelete.completeMessage', { deleted }),
        buttons: [{ label: t('common.ok') }],
      });
      return;
    }

    const preview = failures.slice(0, 8).join('<br>');
    const more = failures.length > 8 ? `<br>${t('versions.bulkDelete.andMore', { count: failures.length - 8 })}` : '';
    showMessageBox({
      title: t('versions.bulkDelete.finishedWithErrorsTitle'),
      message: t('versions.bulkDelete.finishedWithErrorsMessage', { deleted, failures: `${preview}${more}` }),
      buttons: [{ label: t('common.ok') }],
    });
  };

  if (skipConfirm || state.isShiftDown) {
    await runDelete();
    return;
  }

  showMessageBox({
    title: t('versions.bulkDelete.title'),
    message: t('versions.bulkDelete.confirmMessage', { count: keys.length }),
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

const createDeleteButton = (v) => {
  const delBtn = document.createElement('div');
  delBtn.className = 'icon-button';
  bindKeyboardActivation(delBtn, {
    ariaLabel: versionCardActionLabel('delete', getVersionLabel(v)),
  });

  const delImg = document.createElement('img');
  delImg.alt = t('common.delete');
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
      title: t('versions.deleteTitle'),
      message: t('versions.deleteConfirm', { version: `${v.category}/${v.folder}` }),
      buttons: [
        {
          label: t('common.yes'),
          classList: ['danger'],
          onClick: () => deleteVersion(v),
        },
        { label: t('common.no') },
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
    ariaLabel: t('versions.loaders.manageForVersion', { version: getVersionLabel(v) }),
  });

  const loaderImg = document.createElement('img');
  loaderImg.alt = t('versions.loaders.addLoaderAlt');
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
        title: t('common.error'),
        message: t('versions.loaders.failedLoadInformation'),
        buttons: [{ label: t('common.ok') }],
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
          <h4 style="color:var(--color-text-title);margin-top:0;margin-bottom:10px;font-size:12px;letter-spacing:1px;">
            ${t('versions.loaders.installedLoaders')}
          </h4>
          <div style="display: grid; gap: 8px;" id="installed-loaders-container">
    `;

    const installedLoaderTypes = LOADER_UI_ORDER.filter(
      (loaderType) => Array.isArray(installed[loaderType]) && installed[loaderType].length > 0
    );

    if (installedLoaderTypes.length === 0) {
      html += `<p style="color:var(--color-text-muted);font-size:12px;font-style:italic;">${t('versions.loaders.noLoadersInstalled')}</p>`;
    } else {
      installedLoaderTypes.forEach((loaderType) => {
        const loaderUi = getLoaderUi(loaderType);
        installed[loaderType].forEach((loader) => {
          html += `
            <div style="background:var(--color-surface-card);border-left:3px solid ${loaderUi.accent};padding:7px 10px;display:flex;justify-content:space-between;align-items:center;gap:12px;min-height:38px;">
              <div style="min-width:0;line-height:1.15;text-align:left;">
                <div style="color:${loaderUi.accent};font-weight:bold;margin:0 0 2px 0;font-size:14px;letter-spacing:0;">${loaderUi.name}</div>
                <span style="color:var(--color-text-muted); font-size: 12px;">${loader.version}</span>
                <span style="color:var(--color-text-dim); font-size: 11px;"> - ${loader.size_display || t('versions.loaders.unknownSize')}</span>
              </div>
              <button type="button" class="loader-delete-btn" style="width: 24px; height: 24px; cursor: pointer; background: transparent; border: none; padding: 0; display: flex; align-items: center; justify-content: center;" data-loader-type="${loaderType}" data-loader-version="${loader.version}" aria-label="${t('versions.loaders.deleteLoaderVersion', { loader: loaderUi.name, version: loader.version })}" title="${t('versions.loaders.deleteLoaderVersion', { loader: loaderUi.name, version: loader.version })}">
                <img src="assets/images/unfilled_delete.png" alt="${t('common.delete')}" style="width: 100%; height: 100%;">
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
          <h4 style="color:var(--color-text-title);margin-top:0;margin-bottom:10px;font-size:12px;letter-spacing:1px;">
            ${t('versions.loaders.addNewLoader')}
          </h4>
          <div style="display:grid;gap:8px;">
            ${availableLoaderTypes.length === 0 ? `
              <p style="color:var(--color-text-muted);font-size:12px;font-style:italic;">${t('versions.loaders.noAdditionalLoaders')}</p>
            ` : availableLoaderTypes.map((loaderType) => {
              const loaderUi = getLoaderUi(loaderType);
              const loaderDescription = loaderUi.descriptionKey ? t(loaderUi.descriptionKey) : (loaderUi.description || '');
              const loaderSubtitle = loaderUi.subtitleKey ? t(loaderUi.subtitleKey) : (loaderUi.subtitle || '');
              return `
                <button type="button" class="${loaderUi.buttonClass}" data-action="install-${loaderType}">
                  <div style="font-size:15px;font-weight:bold;margin-bottom:4px;">${loaderUi.name}</div>
                  <div style="font-size:9px;opacity:75%;"><b>${loaderDescription}</b><br><i>${loaderSubtitle}</i></div>
                </button>
              `;
            }).join('')}
          </div>
        </div>
      </div>
    `;

    showMessageBox({
      title: t('versions.loaders.modalTitle', { version: v.display }),
      message: html,
      buttons: [{ label: t('common.close') }],
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
      title: t('common.error'),
      message: t('versions.loaders.failedLoadInformation'),
      buttons: [{ label: t('common.ok') }],
    });
  }
};

const showLoaderVersionSelector = async (v, loaderType) => {
  const loaderName = getLoaderUi(loaderType).name;
  try {
    const loaderData = await api(`/api/loaders/${v.category.toLowerCase()}/${v.folder}`);
    if (!loaderData || !loaderData.ok) {
      showMessageBox({
        title: t('common.error'),
        message: t('versions.loaders.failedFetchAvailableVersions', { loader: loaderName }),
        buttons: [{ label: t('common.ok') }],
      });
      return;
    }

    const available = loaderData.available || {};
    const allVersions = available[loaderType] || [];
    const totalAvailable = (loaderData.total_available || {})[loaderType] || allVersions.length;

    if (!allVersions || allVersions.length === 0) {
      showMessageBox({
        title: t('versions.loaders.installLoaderTitle', { loader: loaderName }),
        message: t('versions.loaders.noVersionsAvailableForVersion', { loader: loaderName, version: v.display }),
        buttons: [{ label: t('common.ok') }],
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
          metaLabel += `<i>${t('versions.loaders.selectedRecommended')}</i>`;
        } else if (isRecommended) {
          metaLabel += `<i>${t('versions.loaders.recommended')}</i>`;
        } else if (isSelected) {
          btnClass = 'important'
          metaLabel += `<i>${t('versions.loaders.selected')}</i>`;
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
          <p style="margin-top: 0; color: var(--color-text-muted); font-size: 12px; margin-bottom: 12px;">
            ${t('versions.loaders.selectVersionFor', { loader: loaderName, version: v.display })}
          </p>
          ${renderVersionList(displayedVersions, selectedLoaderVersion)}
          <p style="margin-top: 8px; margin-bottom: 8px; color: var(--color-text-dim); font-size: 11px;">
            ${t('versions.loaders.showingVersions', { count: displayedVersions.length, total: totalAvailable })}
          </p>
      `;

      if (hasMore) {
        msg += `<button id="load-more-btn" type="button" class="default" style="width: 100%; padding: 8px; margin-top: 4px;">${t('versions.loaders.loadMore')}</button>`;
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
        installBtn.textContent = getLoaderInstallButtonLabel(selectedLoaderVersion || allVersions[0]?.version);
      }
    };

    const versionButtons = [
      {
        label: getLoaderInstallButtonLabel(selectedLoaderVersion || allVersions[0]?.version),
        classList: ['primary'],
        onClick: () => installLoaderVersion(v, loaderType, selectedLoaderVersion || allVersions[0].version),
      },
      { label: t('common.cancel') },
    ];

    const title = t('versions.loaders.selectVersionTitle', { loader: loaderName });

    showMessageBox({
      title: title,
      message: buildMessage(),
      buttons: versionButtons,
    });

    const installBtn = document.querySelector('#msgbox-buttons button');
    if (installBtn) {
      installBtn.textContent = getLoaderInstallButtonLabel(selectedLoaderVersion || allVersions[0]?.version);
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
      title: t('common.error'),
      message: t('versions.loaders.failedFetchAvailableVersions', { loader: loaderName }),
      buttons: [{ label: t('common.ok') }],
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
    _progressText: t('versions.install.starting'),
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
                statusLabel: t('versions.status.installing').toUpperCase(),
                keepInstalling: true,
              });
            } else if (status === 'paused') {
              vMeta.paused = true;
              const text = t('versions.install.percentPaused', { percent: pct });

              updateVersionInListByKey(encodedInstallKey, (x) => ({
                ...x,
                paused: true,
                _progressText: text,
                _progressOverall: pct,
              }));

              updateCardProgressUI(vMeta, pct, text, {
                paused: true,
                statusLabel: t('versions.status.paused').toUpperCase(),
                keepInstalling: true,
              });
            } else if (status === 'installed' || pct >= 100) {
              keepPolling = false;
              updateCardProgressUI(vMeta, 100, t('versions.status.installed'), { keepInstalling: false });

              state.versionsList = state.versionsList.filter((x) => x._installKey !== encodedInstallKey);
              await _deps.init();
            } else if (status === 'failed' || status === 'error') {
              const errorMsg = s.message || t('common.unknownError');
              keepPolling = false;

              state.versionsList = state.versionsList.filter((x) => x._installKey !== encodedInstallKey);
              await _deps.init();
              showMessageBox({
                title: t('versions.loaders.installFailedTitle', { loader: loaderName }),
                message: errorMsg,
                buttons: [{ label: t('common.ok') }],
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
      const errorMsg = installResult?.error || t('common.unknownError');

      // Mark as failed in the list
      state.versionsList = state.versionsList.map(x =>
        x._installKey === installKey ? { ...x, installing: false, _progressText: t('versions.install.failedWithMessage', { message: errorMsg }) } : x
      );
      _deps.renderAllVersionSections();
    }
  } catch (err) {
    console.error(`Loader installation error:`, err);

    // Mark as failed in the list
    state.versionsList = state.versionsList.map(x =>
      x._installKey === installKey ? { ...x, installing: false, _progressText: t('versions.install.failedWithMessage', { message: err.message }) } : x
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
          title: t('versions.loaders.deleteFailedTitle'),
          message: (deleteResult && deleteResult.error) || t('common.unknownError'),
          buttons: [{ label: t('common.ok') }],
        });
      }
    } catch (err) {
      console.error('Loader deletion error:', err);
      showMessageBox({
        title: t('versions.loaders.deleteFailedTitle'),
        message: (err && err.message) || t('versions.loaders.unexpectedDeleteError'),
        buttons: [{ label: t('common.ok') }],
      });
    }
  };

  if (skipConfirm || state.isShiftDown) {
    runDelete();
    return;
  }

  showMessageBox({
    title: t('versions.loaders.deleteTitle'),
    message: t('versions.loaders.deleteConfirm', { loader: loaderName, version: loaderVersion }),
    buttons: [
      { label: t('common.cancel') },
      {
        label: t('common.delete'),
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
      badgeMain.textContent = getVersionStatusLabel('paused').toUpperCase();
      badgeMain.classList.add('paused');
  } else {
      badgeMain.textContent =
          sectionType === 'installed'
              ? (v.raw && v.raw.is_imported === true ? getVersionStatusLabel('imported').toUpperCase() : getVersionStatusLabel('installed').toUpperCase())
              : sectionType === 'installing'
              ? getVersionStatusLabel('installing').toUpperCase()
              : getVersionStatusLabel('available').toUpperCase();
  }
  badgeRow.appendChild(badgeMain);

  if (v.is_remote && sectionType === 'available') {
      const badgeSource = document.createElement('span');
      badgeSource.className =
          'version-badge ' +
          (v.source === 'mojang' ? 'official' : 'nonofficial');
    badgeSource.textContent =
      v.source === 'mojang'
        ? getVersionSourceLabel('mojang').toUpperCase()
        : v.source === 'omniarchive'
        ? getVersionSourceLabel('omniarchive').toUpperCase()
        : getVersionSourceLabel('proxy').toUpperCase();
      badgeRow.appendChild(badgeSource);
  }

  if ((sectionType === 'installed' && v.raw && v.raw.full_assets === false)||(sectionType === 'installing' && v.full_install === false)) {
      const badgeLite = document.createElement('span');
      badgeLite.className = 'version-badge lite';
      badgeLite.textContent = getVersionStatusLabel('lite').toUpperCase();
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
  installBtn.textContent = getDownloadButtonLabel({ isRedownload, isLowDataMode });
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
  pauseBtn.textContent = v.paused ? t('common.resume') : t('common.pause');
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
          _progressText: t('versions.install.resuming'),
        }));
        _deps.renderAllVersionSections();
      } else {
        // Pausing
        await pauseInstallForVersionKey(v._installKey);
        // Update UI immediately
        updateVersionInListByKey(v._installKey, (x) => ({
          ...x,
          paused: true,
          _progressText: t('versions.install.paused'),
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
  cancelBtn.textContent = t('common.cancel');

  cancelBtn.addEventListener('click', (e) => {
    e.stopPropagation();

    showMessageBox({
      title: t('versions.install.cancelDownloadTitle'),
      message: t('versions.install.cancelDownloadMessage', { version: `${v.category}/${v.folder}` }),
      buttons: [
        {
          label: t('common.yes'),
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
        { label: t('common.no') },
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
      ariaLabel: t('versions.actions.selectVersion', { version: getVersionLabel(v, fullId) }),
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
    checkbox.title = t('versions.selectForBulkActions');
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
      await api('/api/settings', 'POST', settingsProfilePayload({ selected_version: state.selectedVersion }));
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
