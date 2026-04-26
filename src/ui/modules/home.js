// ui/modules/home.js

import { state } from './state.js';
import {
  getEl,
  setHTML,
  toggleClass,
  imageAttachErrorPlaceholder,
} from './dom-utils.js';
import {
  JAVA_RUNTIME_AUTO,
  JAVA_RUNTIME_INSTALL_OPTION,
  JAVA_RUNTIME_PATH,
  LOADER_UI_ORDER,
  getLoaderUi,
} from './config.js';
import {
  formatBytes,
  makeInfoRowErrorHTML,
  makeInfoRowHTML,
  normalizeFavoriteVersions,
  sanitizeGlobalMessageHtml,
} from './string-utils.js';
import { api } from './api.js';
import {
  showLoadingOverlay,
  hideLoadingOverlay,
  showMessageBox,
} from './modal.js';
import {
  applyVersionImageWithFallback,
  bumpTextureRevision,
  detachVersionImageFallbackHandler,
  getTextureUrl,
} from './textures.js';
import { applyModsViewMode } from './mods.js';
import { applyVersionsViewMode } from './version-controls.js';
import {
  applyProfilesState,
  getCustomStorageDirectoryError,
  getCustomStorageDirectoryPath,
  isTruthySetting,
  normalizeStorageDirectoryMode,
  normalizeVersionStorageOverrideMode,
  refreshCustomStorageDirectoryValidation,
  renderProfilesSelect,
  syncStorageDirectoryUI,
} from './profiles.js';
import {
  parseRAMValue,
  validateRAMFormat,
  validateSettings,
  updateSettingsValidationUI,
} from './launch.js';

const _deps = {};
for (const k of ['autoSaveSetting', 'init']) {
  Object.defineProperty(_deps, k, {
    configurable: true,
    enumerable: true,
    get() {
      throw new Error('home.js dep "' + k + '" not initialized; call setHomeDeps() first');
    },
  });
}

export function setHomeDeps(deps) {
  for (const [k, v] of Object.entries(deps)) {
    Object.defineProperty(_deps, k, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: v,
    });
  }
}


const renderPlayerBodyPreview = (img, scale = 4, model = 'classic') => {
  if (!img) return null;

  try {
    const textureScale = img.width / 64;
    const baseHeight = Math.round(img.height / textureScale);

    const cW = 16 * scale;
    const cH = 32 * scale;
    const canvas = document.createElement('canvas');
    canvas.width = cW;
    canvas.height = cH;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    function drawPart(sx, sy, sw, sh, dx, dy, dw, dh) {
      ctx.drawImage(img, sx * textureScale, sy * textureScale, sw * textureScale, sh * textureScale, dx, dy, dw, dh);
    }

    const headX = 4 * scale;
    const headY = 0;
    const bodyX = 4 * scale;
    const bodyY = 8 * scale;
    const isSlim = model === 'slim' && (img.width === img.height);
    const armWidth = isSlim ? 3 : 4;
    const leftArmX = 12 * scale;
    const rightArmX = isSlim ? 1 * scale : 0 * scale;
    const armY = 8 * scale;
    const leftLegX = 8 * scale;
    const rightLegX = 4 * scale;
    const legY = 20 * scale;

    drawPart(8, 8, 8, 8, headX, headY, 8 * scale, 8 * scale);
    drawPart(20, 20, 8, 12, bodyX, bodyY, 8 * scale, 12 * scale);
    drawPart(44, 20, armWidth, 12, rightArmX, armY, armWidth * scale, 12 * scale);
    drawPart(4, 20, 4, 12, rightLegX, legY, 4 * scale, 12 * scale);

    if (baseHeight <= 32) {
      drawPart(44, 20, armWidth, 12, leftArmX, armY, armWidth * scale, 12 * scale);
      drawPart(4, 20, 4, 12, leftLegX, legY, 4 * scale, 12 * scale);
    } else {
      drawPart(36, 52, armWidth, 12, leftArmX, armY, armWidth * scale, 12 * scale);
      drawPart(20, 52, 4, 12, leftLegX, legY, 4 * scale, 12 * scale);
    }

    drawPart(40, 8, 8, 8, headX, headY, 8 * scale, 8 * scale);

    if (baseHeight >= 64) {
      drawPart(20, 36, 8, 12, bodyX, bodyY, 8 * scale, 12 * scale);
      drawPart(44, 36, armWidth, 12, rightArmX, armY, armWidth * scale, 12 * scale);
      drawPart(52, 52, armWidth, 12, leftArmX, armY, armWidth * scale, 12 * scale);
      drawPart(4, 36, 4, 12, rightLegX, legY, 4 * scale, 12 * scale);
      drawPart(4, 52, 4, 12, leftLegX, legY, 4 * scale, 12 * scale);
    }

    return canvas.toDataURL('image/png');
  } catch (err) {
    console.warn('Error rendering player body preview:', err);
    return null;
  }
}

const renderPlayerHeadPreview = (img) => {
  if (!img) return null;

  try {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    const textureScale = img.width / 64;
    const headX = 8 * textureScale;
    const headY = 8 * textureScale;
    const headSize = 8 * textureScale;
    const overlayX = 40 * textureScale;
    const overlayY = 8 * textureScale;

    ctx.drawImage(img, headX, headY, headSize, headSize, 0, 0, 64, 64);
    ctx.drawImage(img, overlayX, overlayY, headSize, headSize, 0, 0, 64, 64);

    return canvas.toDataURL('image/png');
  } catch (err) {
    console.warn('Error rendering player head preview:', err);
    return null;
  }
}

const renderPlayerCapePreview = (img) => {
  if (!img) return null;

  try{
    const textureScale = img.width / 64;
    const scale = 8;
    const canvas = document.createElement('canvas');
    canvas.width = 10 * scale;
    canvas.height = 16 * scale;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    ctx.drawImage(
      img,
      1 * textureScale,
      1 * textureScale,
      10 * textureScale,
      16 * textureScale,
      0,
      0,
      canvas.width,
      canvas.height
    );

    return canvas.toDataURL('image/png');
  } catch (err) {
    console.warn('Error rendering player cape preview:', err);
    return null;
  }
}

export const updateSettingsPlayerPreview = () => {
  const bodyPreviewImg = getEl('settings-player-body-preview');
  const capePreviewImg = getEl('settings-player-cape-preview');
  const previewRow = getEl('settings-player-preview-row');
  if (!bodyPreviewImg || !capePreviewImg || !previewRow) return;

  const requestId = ++state.settingsPreviewRequestId;

  const hidePreviewImage = (img) => {
    if (!img) return;
    img.style.display = 'none';
    img.removeAttribute('src');
  };

  const showPreviewImage = (img, src) => {
    if (!img || !src) return;
    img.style.display = '';
    img.src = src;
  };

  const syncPreviewRowVisibility = () => {
    const hasBody = bodyPreviewImg.style.display !== 'none';
    const hasCape = capePreviewImg.style.display !== 'none';
    previewRow.style.display = (hasBody || hasCape) ? 'flex' : 'none';
  };

  const isValidSkinTexture = (img) => {
    if (!img) return false;
    const w = Number(img.naturalWidth || img.width || 0);
    const h = Number(img.naturalHeight || img.height || 0);
    if (w < 64 || h < 32 || (w % 64) !== 0) return false;
    const isLegacy = w === (h * 2) && (h % 32) === 0;
    const isModern = w === h && (h % 64) === 0;
    return isLegacy || isModern;
  };

  const isValidCapeTexture = (img) => {
    if (!img) return false;
    const w = Number(img.naturalWidth || img.width || 0);
    const h = Number(img.naturalHeight || img.height || 0);
    if (w < 64 || h < 32) return false;
    return w === (h * 2) && (w % 64) === 0;
  };

  const acctType = state.settingsState.account_type || 'Local';
  const idOrName = state.settingsState.uuid || state.settingsState.username;
  hidePreviewImage(bodyPreviewImg);
  hidePreviewImage(capePreviewImg);
  previewRow.style.display = 'none';

  if (acctType === 'Histolauncher' && idOrName) {
    try {
      const skinImg = new Image();
      skinImg.crossOrigin = 'anonymous';
      skinImg.onload = () => {
        if (requestId !== state.settingsPreviewRequestId) return;
        try {
          if (!isValidSkinTexture(skinImg)) {
            hidePreviewImage(bodyPreviewImg);
            syncPreviewRowVisibility();
            return;
          }
          const dataUrl = renderPlayerBodyPreview(skinImg, 4, 'classic');
          if (dataUrl) {
            showPreviewImage(bodyPreviewImg, dataUrl);
          } else {
            hidePreviewImage(bodyPreviewImg);
          }
        } catch (err) {
          console.warn('Failed rendering body preview:', err);
          hidePreviewImage(bodyPreviewImg);
        }
        syncPreviewRowVisibility();
      };
      skinImg.onerror = () => {
        if (requestId !== state.settingsPreviewRequestId) return;
        hidePreviewImage(bodyPreviewImg);
        syncPreviewRowVisibility();
      };
      skinImg.src = getTextureUrl('skin', idOrName);
    } catch (err) {
      console.warn('Error loading skin for preview:', err);
      hidePreviewImage(bodyPreviewImg);
      syncPreviewRowVisibility();
    }

    try {
      const capeImg = new Image();
      capeImg.crossOrigin = 'anonymous';
      capeImg.onload = () => {
        if (requestId !== state.settingsPreviewRequestId) return;
        try {
          if (!isValidCapeTexture(capeImg)) {
            hidePreviewImage(capePreviewImg);
            syncPreviewRowVisibility();
            return;
          }
          const dataUrl = renderPlayerCapePreview(capeImg);
          if (dataUrl) {
            showPreviewImage(capePreviewImg, dataUrl);
          } else {
            hidePreviewImage(capePreviewImg);
          }
        } catch (err) {
          console.warn('Failed rendering cape preview:', err);
          hidePreviewImage(capePreviewImg);
        }
        syncPreviewRowVisibility();
      };
      capeImg.onerror = () => {
        if (requestId !== state.settingsPreviewRequestId) return;
        hidePreviewImage(capePreviewImg);
        syncPreviewRowVisibility();
      };
      capeImg.src = getTextureUrl('cape', idOrName);
    } catch (err) {
      console.warn('Error loading cape for preview:', err);
      hidePreviewImage(capePreviewImg);
      syncPreviewRowVisibility();
    }
  } else {
    hidePreviewImage(bodyPreviewImg);
    hidePreviewImage(capePreviewImg);
    previewRow.style.display = 'none';
  }
}

export const updateSettingsAccountSettingsButtonVisibility = () => {
  const accountSettingsRow = getEl('settings-account-settings-row');
  if (!accountSettingsRow) return;

  toggleClass(accountSettingsRow, 'hidden', state.settingsState.account_type !== 'Histolauncher');
};

const refreshHistolauncherAccountAssets = async () => {
  if (state.settingsState.account_type !== 'Histolauncher') return;

  try {
    const result = await api('/api/account/refresh-assets', 'POST', {});
    if (result && result.ok && result.authenticated) {
      state.settingsState.username = result.username || state.settingsState.username;
      state.settingsState.uuid = result.uuid || state.settingsState.uuid;
      state.histolauncherUsername = state.settingsState.username || state.histolauncherUsername;
      state.settingsState.texture_revision = result.texture_revision || Date.now();
    } else if (result && result.unauthorized) {
      await api('/api/settings', 'POST', { account_type: 'Local', uuid: '' });
      await _deps.init();
      return;
    } else {
      bumpTextureRevision();
    }
  } catch (err) {
    console.warn('[Account] Failed to refresh assets after closing settings:', err);
    bumpTextureRevision();
  }

  updateSettingsPlayerPreview();
  updateHomeInfo();
};

export const showHistolauncherAccountSettingsModal = () => {
  const frameWrap = document.createElement('div');
  frameWrap.style.width = '84vw';
  frameWrap.style.maxWidth = '960px';
  frameWrap.style.height = '69vh';
  frameWrap.style.maxHeight = '720px';
  frameWrap.style.border = '4px solid #333';
  frameWrap.style.background = '#222';
  frameWrap.style.overflow = 'hidden';
  frameWrap.style.boxSizing = 'border-box';

  const loadingState = document.createElement('div');
  loadingState.style.height = '100%';
  loadingState.style.display = 'flex';
  loadingState.style.alignItems = 'center';
  loadingState.style.justifyContent = 'center';
  loadingState.style.padding = '20px';
  loadingState.style.textAlign = 'center';
  loadingState.textContent = 'Loading account settings...';
  frameWrap.appendChild(loadingState);

  showMessageBox({
    title: 'Account Settings',
    customContent: frameWrap,
    buttons: [
      {
        label: 'Close',
        onClick: async () => {
          showLoadingOverlay();
          try {
            await refreshHistolauncherAccountAssets();
          } finally {
            hideLoadingOverlay();
          }
        },
      },
    ],
  });

  const iframe = document.createElement('iframe');
  iframe.title = 'Histolauncher Account Settings';
  iframe.loading = 'lazy';
  iframe.referrerPolicy = 'strict-origin-when-cross-origin';
  iframe.sandbox = 'allow-scripts allow-same-origin allow-forms';
  iframe.style.width = '100%';
  iframe.style.height = '100%';
  iframe.style.border = '0';
  iframe.style.display = 'block';
  iframe.style.background = '#111';
  iframe.style.visibility = 'hidden';

  iframe.addEventListener('load', () => {
    if (loadingState.parentNode) loadingState.remove();
    iframe.style.visibility = 'visible';
  });

  frameWrap.appendChild(iframe);
  iframe.src = '/account-settings-frame';
};

const setGlobalMessageContent = (el, input) => {
  if (!el) return;
  el.innerHTML = sanitizeGlobalMessageHtml(input);
};

const DEBUG = false;
export const debug = (...args) => { if (DEBUG) console.log.apply(console, args); };
const debugWarn = (...args) => { if (DEBUG) console.warn.apply(console, args); };

const setHomeGlobalMessageHidden = (hidden) => {
  const box = getEl('home-global-message');
  if (!box) return;
  toggleClass(box, 'hidden', !!hidden);
};

const renderHomeGlobalMessage = (payload) => {
  const box = getEl('home-global-message');
  const content = getEl('home-global-message-content');
  const dismissBtn = getEl('home-global-message-dismiss');
  if (!box || !content || !dismissBtn) return;

  const active = !!(payload && payload.active);
  const message = String((payload && payload.message) || '').trim();
  if (!active || !message) {
    content.textContent = '';
    setHomeGlobalMessageHidden(true);
    return;
  }

  const messageType = String((payload && payload.type) || 'message').toLowerCase();
  const normalizedType = ['message', 'warning', 'important'].includes(messageType)
    ? messageType
    : 'message';
  box.classList.remove('global-message-message', 'global-message-warning', 'global-message-important');
  box.classList.add(`global-message-${normalizedType}`);

  dismissBtn.classList.add('hidden');
  dismissBtn.onclick = null;

  const nonDismissible = normalizedType === 'important';
  if (nonDismissible) {
    setGlobalMessageContent(content, message);
    setHomeGlobalMessageHidden(false);
    return;
  }

  setGlobalMessageContent(content, message);
  dismissBtn.classList.remove('hidden');
  dismissBtn.onclick = () => {
    setHomeGlobalMessageHidden(true);
  };
  setHomeGlobalMessageHidden(false);
};

export const refreshHomeGlobalMessage = async () => {
  try {
    const res = await api('/api/account/launcher-message', 'GET');
    if (!res || res.ok !== true) {
      setHomeGlobalMessageHidden(true);
      return;
    }
    renderHomeGlobalMessage(res);
  } catch (e) {
    setHomeGlobalMessageHidden(true);
  }
};

export const updateHomeInfo = () => {
  const errors = validateSettings();
  const username = state.settingsState.username || 'Player';
  const acctType = state.settingsState.account_type || 'Local';

  // Username error message
  let usernameTooltip = '';
  if (errors.username) {
    const len = username.length;
    if (len === 0) {
      usernameTooltip = 'Username cannot be empty';
    } else if (len < 3) {
      usernameTooltip = `Username too short (${len}/3-16 characters)`;
    } else if (len > 16) {
      usernameTooltip = `Username too long (${len}/3-16 characters)`;
    }
  }

  // RAM error message
  let ramTooltip = '';
  if (errors.min_ram || errors.max_ram) {
    const minRamStr = (state.settingsState.min_ram || '').toUpperCase();
    const maxRamStr = (state.settingsState.max_ram || '').toUpperCase();

    if (errors.max_ram) {
      if (!validateRAMFormat(maxRamStr)) {
        ramTooltip = 'Invalid format: use number with optional K, M, G, or T suffix (e.g., 4096M)';
      } else {
        const maxVal = parseRAMValue(maxRamStr);
        if (maxVal < 1) {
          ramTooltip = 'Maximum RAM must be at least 1 byte (value is too low)';
        } else if (minRamStr && validateRAMFormat(minRamStr)) {
          const minVal = parseRAMValue(minRamStr);
          if (minVal > maxVal) {
            ramTooltip = `Maximum RAM must be greater than Minimum RAM (${minRamStr} > ${maxRamStr})`;
          }
        }
      }
    } else if (errors.min_ram) {
      ramTooltip = 'Invalid format: use number with optional K, M, G, or T suffix (e.g., 256M)';
    }
  }

  const selectedVData = state.selectedVersion
    ? state.versionsList.find((v) => `${v.category}/${v.folder}` === state.selectedVersion)
    : null;

  // Version row
  const versionText = state.selectedVersionDisplay
    ? makeInfoRowHTML('assets/images/library.png', 'Version', state.selectedVersionDisplay)
    : makeInfoRowHTML('assets/images/library.png', 'Version', '(none selected)');
  setHTML('info-version', versionText);

  // Account row
  const usernameHTML = errors.username
    ? makeInfoRowErrorHTML('Account', username, acctType, usernameTooltip)
    : makeInfoRowHTML('assets/images/settings.gif', 'Account', username, acctType);
  setHTML('info-username', usernameHTML);

  // RAM row
  const minRam = (state.settingsState.min_ram || '2048M').toUpperCase();
  const maxRam = (state.settingsState.max_ram || '4096M').toUpperCase();
  const ramHTML = errors.min_ram || errors.max_ram
    ? makeInfoRowErrorHTML('RAM Limit', `${minRam}B - ${maxRam}B`, null, ramTooltip)
    : makeInfoRowHTML('assets/images/settings.gif', 'RAM Limit', `${minRam}B - ${maxRam}B`);
  setHTML('info-ram', ramHTML);

  // Storage directory row
  const globalStorageMode = normalizeStorageDirectoryMode(state.settingsState.storage_directory);
  const selectedStorageOverrideMode = selectedVData
    ? normalizeVersionStorageOverrideMode(selectedVData.storage_override_mode)
    : 'default';
  const hasStorageOverride = !!selectedVData && selectedStorageOverrideMode !== 'default';

  let effectiveStorageMode = globalStorageMode;
  let effectiveStoragePath = '';
  let storageParens = null;

  if (hasStorageOverride) {
    storageParens = 'Overriden';
    if (selectedStorageOverrideMode === 'custom') {
      effectiveStorageMode = 'custom';
      effectiveStoragePath = String(selectedVData.storage_override_path || '').trim();
    } else if (selectedStorageOverrideMode === 'global') {
      effectiveStorageMode = 'global';
    } else if (selectedStorageOverrideMode === 'version') {
      effectiveStorageMode = 'version';
    } else {
      effectiveStorageMode = globalStorageMode;
      storageParens = null;
    }
  } else {
    effectiveStorageMode = globalStorageMode;
    if (effectiveStorageMode === 'custom') {
      effectiveStoragePath = getCustomStorageDirectoryPath();
    }
  }

  let storageValue = 'Global';
  if (effectiveStorageMode === 'version') {
    storageValue = 'Version';
  } else if (effectiveStorageMode === 'custom') {
    storageValue = 'Custom (' + effectiveStoragePath + ')' || 'None';
  }

  const storageHTML =
    !hasStorageOverride && effectiveStorageMode === 'custom' && errors.storage_directory
      ? makeInfoRowErrorHTML('Storage Directory', storageValue, storageParens, getCustomStorageDirectoryError())
      : makeInfoRowHTML('assets/images/folder.png', 'Storage Directory', storageValue, storageParens);
  setHTML('info-storage-dir', storageHTML);

  // Java runtime row
  const rawJavaPath = String(state.settingsState.java_path || '').trim();

  const formatJavaRuntimeShort = (rt) => {
    const label = String((rt && rt.label) || '').trim();
    const version = String((rt && rt.version) || '').trim();
    if (label && version) return `${label} (${version})`;

    const display = String((rt && rt.display) || '').trim();
    if (display) return display.split(' - ')[0].trim();

    return '';
  };

  let javaRuntimeValue = 'Default (Java PATH)';
  if (rawJavaPath && rawJavaPath !== JAVA_RUNTIME_PATH) {
    if (rawJavaPath === JAVA_RUNTIME_AUTO) {
      javaRuntimeValue = 'Auto';
    } else if (state.javaRuntimesLoaded) {
      const match = state.javaRuntimes.find((rt) => String(rt.path || '').trim() === rawJavaPath);
      javaRuntimeValue = match ? (formatJavaRuntimeShort(match) || 'Java runtime') : '[Missing]';
    } else if (state.javaRuntimesLoadAttempted) {
      javaRuntimeValue = 'Custom';
    } else {
      javaRuntimeValue = 'Detecting...';
      if (!state.javaRuntimesLoading) {
        state.javaRuntimesLoading = true;
        state.javaRuntimesLoadAttempted = true;
        refreshJavaRuntimeOptions(false)
          .then((ok) => {
            if (ok) state.javaRuntimesLoaded = true;
          })
          .finally(() => {
            state.javaRuntimesLoading = false;
            updateHomeInfo();
          });
      }
    }
  }
  const javaRuntimeHTML = makeInfoRowHTML('assets/images/java_icon.png', 'Java Runtime', javaRuntimeValue);
  setHTML('info-java-runtime', javaRuntimeHTML);

  // --- Version panel: image + details ---
  const homeVersionImg = getEl('home-version-image');
  const infoCategoryEl = getEl('info-version-category');
  const infoSizeEl = getEl('info-version-size');
  const infoLoadersEl = getEl('info-version-loaders');

  if (state.selectedVersion) {
    const vData = selectedVData;

    if (homeVersionImg) {
      if (vData) {
        applyVersionImageWithFallback(homeVersionImg, {
          imageUrl: '',
          category: vData.category,
          folder: vData.folder,
          placeholder: 'assets/images/version_placeholder.png',
        });
      } else {
        detachVersionImageFallbackHandler(homeVersionImg);
        homeVersionImg.src = 'assets/images/version_placeholder.png';
      }
    }

    if (vData) {
      if (infoCategoryEl) {
        infoCategoryEl.innerHTML = makeInfoRowHTML('assets/images/library.png', 'Category', vData.category);
        infoCategoryEl.classList.remove('hidden');
      }

      const sizeBytes = vData.total_size_bytes || (vData.raw && vData.raw.total_size_bytes) || 0;
      const assetsType = (vData.raw && vData.raw.full_assets === false) ? 'Lite' : 'Full';
      if (infoSizeEl) {
        if (sizeBytes > 0) {
          infoSizeEl.innerHTML = makeInfoRowHTML('assets/images/cobblestone.png', 'Size', formatBytes(sizeBytes), assetsType);
        } else {
          infoSizeEl.innerHTML = makeInfoRowHTML('assets/images/cobblestone.png', 'Assets', assetsType);
        }
        infoSizeEl.classList.remove('hidden');
      }

      if (infoLoadersEl) {
        const loaders = (vData.raw && vData.raw.loaders) || null;
        if (loaders) {
          const parts = [];
          LOADER_UI_ORDER.forEach((loaderType) => {
            const loaderUi = getLoaderUi(loaderType);
            (loaders[loaderType] || []).forEach((l) => parts.push(`${loaderUi.name} ${l.version}`));
          });
          infoLoadersEl.innerHTML = makeInfoRowHTML(
            'assets/images/anvil_hammer.png',
            'Loaders',
            parts.length > 0 ? parts.join(', ') : 'None'
          );
          infoLoadersEl.classList.remove('hidden');
        } else {
          infoLoadersEl.classList.add('hidden');
        }
      }
    } else {
      if (infoCategoryEl) infoCategoryEl.classList.add('hidden');
      if (infoSizeEl) infoSizeEl.classList.add('hidden');
      if (infoLoadersEl) infoLoadersEl.classList.add('hidden');
    }
  } else {
    if (homeVersionImg) homeVersionImg.src = 'assets/images/version_placeholder.png';
    if (infoCategoryEl) infoCategoryEl.classList.add('hidden');
    if (infoSizeEl) infoSizeEl.classList.add('hidden');
    if (infoLoadersEl) infoLoadersEl.classList.add('hidden');
  }

  const topbarProfile = getEl('topbar-profile');
  const topbarUsername = getEl('topbar-username');
  const topbarProfilePic = getEl('topbar-profile-pic');

  if (topbarProfile) {
    topbarProfile.style.display = 'flex';
    topbarProfile.style.alignItems = 'center';
    topbarProfile.style.gap = '8px';
  }
  if (topbarUsername) topbarUsername.textContent = username;

  const showHistolauncherAvatar = acctType === 'Histolauncher' && !!state.settingsState.uuid;
  if (topbarProfilePic) {
    if (showHistolauncherAvatar) {
      topbarProfilePic.style.display = 'block';
      try {
        const skinImg = new Image();
        skinImg.onload = () => {
          const headDataUrl = renderPlayerHeadPreview(skinImg);

          if (headDataUrl) topbarProfilePic.src = headDataUrl;
          else topbarProfilePic.src = '/assets/images/unknown.png';
        };
        skinImg.onerror = () => {
          topbarProfilePic.src = '/assets/images/unknown.png';
        };
        skinImg.src = getTextureUrl('skin', state.settingsState.uuid);
      } catch (err) {
        console.warn('Error loading skin for profile picture:', err);
        topbarProfilePic.src = '/assets/images/unknown.png';
      }
      imageAttachErrorPlaceholder(topbarProfilePic, '/assets/images/unknown.png');
    } else {
      topbarProfilePic.style.display = 'none';
      topbarProfilePic.removeAttribute('src');
    }
  }
};

export const initSettings = async (data, profilePayload = null) => {
  if (profilePayload && Array.isArray(profilePayload.profiles)) {
    applyProfilesState(profilePayload.profiles, profilePayload.active_profile);
    renderProfilesSelect();
  }

  state.settingsState = { ...state.settingsState, ...data };

  if (!state.settingsState.addons_view) {
    state.settingsState.addons_view = 'list';
  }

  state.settingsState.favorite_versions = normalizeFavoriteVersions(
    state.settingsState.favorite_versions
  );

  if (state.settingsState.account_type === 'Histolauncher') {
    try {
      const currentUser = await api('/api/account/current', 'GET');
      if (currentUser.ok && currentUser.authenticated) {
        state.settingsState.username = currentUser.username;
        state.settingsState.uuid = currentUser.uuid;
        state.histolauncherUsername = currentUser.username;
      } else {
        const unauthorized = !!currentUser.unauthorized;
        if (unauthorized) {
          console.warn('[Account] Session verification failed (unauthorized):', currentUser.error);
          state.settingsState.account_type = 'Local';
          state.settingsState.username = data.username || 'Player';
          state.settingsState.uuid = null;
          _deps.autoSaveSetting('account_type', 'Local');
        } else {
          console.warn('[Account] Unable to verify session (network issue?), keeping existing login:', currentUser.error);
          state.settingsState.username = data.username || 'Player';
        }
      }
    } catch (e) {
      console.warn('[Account] Error verifying session:', e);
      state.settingsState.username = data.username || 'Player';
    }
  } else {
    state.settingsState.username = data.username || 'Player';
    state.settingsState.uuid = null;
  }

  const usernameInput = getEl('settings-username');
  const usernameRow = getEl('username-row');
  if (usernameInput) {
    usernameInput.value = state.settingsState.username || 'Player';

    const isHistolauncher = state.settingsState.account_type === 'Histolauncher';
    usernameInput.disabled = isHistolauncher;

    if (usernameRow) {
      usernameRow.style.display = isHistolauncher ? 'none' : 'block';
    }
  }

  const minRamInput = getEl('settings-min-ram');
  if (minRamInput) minRamInput.value = state.settingsState.min_ram || '32M';

  const maxRamInput = getEl('settings-max-ram');
  if (maxRamInput) maxRamInput.value = state.settingsState.max_ram || '4096M';

  const extraJvmInput = getEl('settings-extra-jvm-args');
  if (extraJvmInput) extraJvmInput.value = state.settingsState.extra_jvm_args || '';

  const storageSelect = getEl('settings-storage-dir');
  state.settingsState.storage_directory = normalizeStorageDirectoryMode(
    state.settingsState.storage_directory
  );
  state.settingsState.custom_storage_directory = getCustomStorageDirectoryPath();
  if (typeof state.settingsState.custom_storage_directory_valid !== 'boolean') {
    state.settingsState.custom_storage_directory_valid =
      state.settingsState.storage_directory !== 'custom' || !!state.settingsState.custom_storage_directory;
  }
  if (typeof state.settingsState.custom_storage_directory_error !== 'string') {
    state.settingsState.custom_storage_directory_error = '';
  }
  if (storageSelect) {
    storageSelect.value = state.settingsState.storage_directory;
  }
  syncStorageDirectoryUI();

  const proxyEl = getEl('settings-url-proxy');
  if (proxyEl) proxyEl.value = state.settingsState.url_proxy || '';

  const lowDataEl = getEl('settings-low-data');
  if (lowDataEl) lowDataEl.checked = state.settingsState.low_data_mode === "1";

  const fastDownloadEl = getEl('settings-fast-download');
  if (fastDownloadEl) fastDownloadEl.checked = state.settingsState.fast_download === "1";

  const showThirdPartyEl = getEl('settings-show-third-party-versions');
  if (showThirdPartyEl) showThirdPartyEl.checked = isTruthySetting(state.settingsState.show_third_party_versions);

  const allowAllOverrideClasspathEl = getEl('settings-allow-override-classpath-all-modloaders');
  if (allowAllOverrideClasspathEl) {
    allowAllOverrideClasspathEl.checked = isTruthySetting(state.settingsState.allow_override_classpath_all_modloaders);
  }

  const accountSelect = getEl('settings-account-type');
  const connectBtn = getEl('connect-account-btn');
  const disconnectBtn = getEl('disconnect-account-btn');
  const acctType = state.settingsState.account_type || 'Local';

  if (accountSelect) accountSelect.value = acctType;
  if (connectBtn) connectBtn.style.display = 'none';
  if (disconnectBtn) disconnectBtn.style.display = 'none';
  updateSettingsAccountSettingsButtonVisibility();
  updateSettingsPlayerPreview();
  await refreshCustomStorageDirectoryValidation();
  updateHomeInfo();
  updateSettingsValidationUI();
  applyVersionsViewMode();
  applyModsViewMode();
};

export const refreshJavaRuntimeOptions = async (force = false) => {
  const select = getEl('settings-java-runtime');
  if (!select) return false;

  const endpoint = force ? '/api/java-runtimes-refresh' : '/api/java-runtimes';
  const res = await api(endpoint, 'GET');
  if (!res || !res.ok) {
    return false;
  }

  state.javaRuntimes = Array.isArray(res.runtimes) ? res.runtimes : [];

  select.innerHTML = '';

  const autoOpt = document.createElement('option');
  autoOpt.value = JAVA_RUNTIME_AUTO;
  autoOpt.textContent = 'Auto';
  select.appendChild(autoOpt);

  const pathOpt = document.createElement('option');
  pathOpt.value = JAVA_RUNTIME_PATH;
  pathOpt.textContent = 'Default (Java PATH)';
  select.appendChild(pathOpt);

  state.javaRuntimes.forEach((rt) => {
    const opt = document.createElement('option');
    opt.value = rt.path || '';
    opt.textContent = rt.display || rt.path || 'Java runtime';
    select.appendChild(opt);
  });

  const selectedRaw = String(state.settingsState.java_path || res.selected_java_path || '').trim();
  if (
    selectedRaw &&
    selectedRaw !== JAVA_RUNTIME_AUTO &&
    selectedRaw !== JAVA_RUNTIME_PATH &&
    !state.javaRuntimes.some((rt) => rt.path === selectedRaw)
  ) {
    const missingOpt = document.createElement('option');
    missingOpt.value = selectedRaw;
    missingOpt.textContent = `[Missing] ${selectedRaw}`;
    select.appendChild(missingOpt);
  }

  const installOpt = document.createElement('option');
  installOpt.value = JAVA_RUNTIME_INSTALL_OPTION;
  installOpt.textContent = '+ Install Java';
  installOpt.style.fontStyle = 'italic';
  installOpt.style.color = 'rgba(255, 255, 255, 0.5)';
  select.appendChild(installOpt);

  let selectedValue = selectedRaw || JAVA_RUNTIME_PATH;
  if (selectedValue !== JAVA_RUNTIME_AUTO && selectedValue !== JAVA_RUNTIME_PATH) {
    selectedValue = selectedRaw;
  }
  select.value = selectedValue;

  return true;
};
