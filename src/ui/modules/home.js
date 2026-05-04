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
import { applyAppearanceSettings } from './appearance.js';
import { setLauncherLanguage, t } from './i18n.js';
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

const settingsProfilePayload = (patch = {}) => ({
  ...patch,
  _profile_id: state.profilesState.activeProfile || 'default',
});

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


const normalizeAccountType = (value) => {
  if (value === 'Histolauncher') return 'Histolauncher';
  if (value === 'Microsoft') return 'Microsoft';
  return 'Local';
};

const isOnlineAccountType = (value) => normalizeAccountType(value) !== 'Local';

const normalizeSkinModel = (value) => {
  const model = String(value || '').trim().toLowerCase();
  return model === 'slim' ? 'slim' : 'classic';
};

const skinViewerModel = (model) => normalizeSkinModel(model) === 'slim' ? 'slim' : 'default';


export const renderPlayerBodyPreview = (img, scale = 4, model = 'classic') => {
  if (!img) return null;

  try {
    const textureScale = img.width / 64;
    const baseHeight = Math.round(img.height / textureScale);

    const overlayInflate = Math.max(1, Math.round(scale * 0.25));
    const pad = overlayInflate;
    const cW = 16 * scale + pad * 2;
    const cH = 32 * scale + pad * 2;
    const canvas = document.createElement('canvas');
    canvas.width = cW;
    canvas.height = cH;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    function drawPart(sx, sy, sw, sh, dx, dy, dw, dh) {
      ctx.drawImage(img, sx * textureScale, sy * textureScale, sw * textureScale, sh * textureScale, dx, dy, dw, dh);
    }

    function drawOverlayPart(sx, sy, sw, sh, dx, dy, dw, dh) {
      drawPart(sx, sy, sw, sh, dx - overlayInflate, dy - overlayInflate, dw + overlayInflate * 2, dh + overlayInflate * 2);
    }

    const headX = pad + 4 * scale;
    const headY = pad;
    const bodyX = pad + 4 * scale;
    const bodyY = pad + 8 * scale;
    const isSlim = model === 'slim' && (img.width === img.height);
    const armWidth = isSlim ? 3 : 4;
    const leftArmX = pad + 12 * scale;
    const rightArmX = pad + (isSlim ? 1 * scale : 0 * scale);
    const armY = pad + 8 * scale;
    const leftLegX = pad + 8 * scale;
    const rightLegX = pad + 4 * scale;
    const legY = pad + 20 * scale;

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

    drawOverlayPart(40, 8, 8, 8, headX, headY, 8 * scale, 8 * scale);

    if (baseHeight >= 64) {
      drawOverlayPart(20, 36, 8, 12, bodyX, bodyY, 8 * scale, 12 * scale);
      drawOverlayPart(44, 36, armWidth, 12, rightArmX, armY, armWidth * scale, 12 * scale);
      drawOverlayPart(52, 52, armWidth, 12, leftArmX, armY, armWidth * scale, 12 * scale);
      drawOverlayPart(4, 36, 4, 12, rightLegX, legY, 4 * scale, 12 * scale);
      drawOverlayPart(4, 52, 4, 12, leftLegX, legY, 4 * scale, 12 * scale);
    }

    return canvas.toDataURL('image/png');
  } catch (err) {
    console.warn('Error rendering player body preview:', err);
    return null;
  }
}

export const renderPlayerHeadPreview = (img) => {
  if (!img) return null;

  try {
    const canvas = document.createElement('canvas');
    const overlayInflate = 2;
    canvas.width = 64 + overlayInflate * 2;
    canvas.height = 64 + overlayInflate * 2;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    const textureScale = img.width / 64;
    const headX = 8 * textureScale;
    const headY = 8 * textureScale;
    const headSize = 8 * textureScale;
    const overlayX = 40 * textureScale;
    const overlayY = 8 * textureScale;

    ctx.drawImage(img, headX, headY, headSize, headSize, overlayInflate, overlayInflate, 64, 64);
    ctx.drawImage(img, overlayX, overlayY, headSize, headSize, 0, 0, 64 + overlayInflate * 2, 64 + overlayInflate * 2);

    return canvas.toDataURL('image/png');
  } catch (err) {
    console.warn('Error rendering player head preview:', err);
    return null;
  }
}

export const renderPlayerCapePreview = (img) => {
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

export const renderPlayerBodyPreview3D = (img, scale = 4, model = 'classic') => {
  if (!img) return null;

  try {
    const textureScale = img.width / 64;
    const baseHeight = Math.round(img.height / textureScale);
    const isSlim = model === 'slim' && (img.width === img.height);
    const armWidth = isSlim ? 3 : 4;

    const canvas = document.createElement('canvas');
    canvas.width = 96;
    canvas.height = 144;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    const drawPart = (sourceX, sourceY, sourceWidth, sourceHeight, destX, destY, destWidth, destHeight, shade = 0) => {
      ctx.drawImage(
        img,
        sourceX * textureScale,
        sourceY * textureScale,
        sourceWidth * textureScale,
        sourceHeight * textureScale,
        destX,
        destY,
        destWidth,
        destHeight
      );
      if (shade > 0) {
        ctx.fillStyle = `rgba(0,0,0,${shade})`;
        ctx.fillRect(destX, destY, destWidth, destHeight);
      }
    };

    ctx.fillStyle = 'rgba(0,0,0,0.28)';
    ctx.beginPath();
    ctx.ellipse(48, 134, 28, 7, 0, 0, Math.PI * 2);
    ctx.fill();

    drawPart(4, 20, 4, 12, 32, 86, 16, 44, 0.04);
    drawPart(0, 20, 4, 12, 48, 86, 7, 44, 0.18);

    const leftLegSourceX = baseHeight <= 32 ? 4 : 20;
    const leftLegSourceY = baseHeight <= 32 ? 20 : 52;
    const leftLegSideX = baseHeight <= 32 ? 0 : 16;
    const leftLegSideY = baseHeight <= 32 ? 20 : 52;
    drawPart(leftLegSourceX, leftLegSourceY, 4, 12, 48, 86, 16, 44, 0.06);
    drawPart(leftLegSideX, leftLegSideY, 4, 12, 64, 86, 7, 44, 0.2);

    drawPart(44, 20, armWidth, 12, 16, 46, armWidth * scale, 46, 0.05);
    drawPart(40, 20, 4, 12, 16 + armWidth * scale, 46, 7, 46, 0.18);

    const leftArmSourceX = baseHeight <= 32 ? 44 : 36;
    const leftArmSourceY = baseHeight <= 32 ? 20 : 52;
    const leftArmSideX = baseHeight <= 32 ? 40 : 32;
    const leftArmSideY = baseHeight <= 32 ? 20 : 52;
    drawPart(leftArmSourceX, leftArmSourceY, armWidth, 12, 65, 46, armWidth * scale, 46, 0.08);
    drawPart(leftArmSideX, leftArmSideY, 4, 12, 65 + armWidth * scale, 46, 7, 46, 0.22);

    drawPart(20, 16, 8, 4, 34, 40, 32, 7, 0.08);
    drawPart(20, 20, 8, 12, 30, 47, 32, 45, 0.02);
    drawPart(16, 20, 4, 12, 62, 47, 8, 45, 0.2);

    drawPart(8, 0, 8, 8, 30, 5, 32, 7, 0.08);
    drawPart(8, 8, 8, 8, 24, 12, 32, 32, 0);
    drawPart(0, 8, 8, 8, 56, 12, 10, 32, 0.18);
    drawPart(40, 8, 8, 8, 24, 12, 32, 32, 0);

    if (baseHeight >= 64) {
      drawPart(4, 36, 4, 12, 32, 86, 16, 44, 0);
      drawPart(4, 52, 4, 12, 48, 86, 16, 44, 0.02);
      drawPart(44, 36, armWidth, 12, 16, 46, armWidth * scale, 46, 0);
      drawPart(52, 52, armWidth, 12, 65, 46, armWidth * scale, 46, 0.03);
      drawPart(20, 36, 8, 12, 30, 47, 32, 45, 0);
    }

    return canvas.toDataURL('image/png');
  } catch (err) {
    console.warn('Error rendering 3D player body preview:', err);
    return null;
  }
}

export const renderPlayerCapePreview3D = (img) => {
  if (!img) return null;

  try {
    const textureScale = img.width / 64;
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 112;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    const drawPart = (sourceX, sourceY, sourceWidth, sourceHeight, destX, destY, destWidth, destHeight, shade = 0) => {
      ctx.drawImage(
        img,
        sourceX * textureScale,
        sourceY * textureScale,
        sourceWidth * textureScale,
        sourceHeight * textureScale,
        destX,
        destY,
        destWidth,
        destHeight
      );
      if (shade > 0) {
        ctx.fillStyle = `rgba(0,0,0,${shade})`;
        ctx.fillRect(destX, destY, destWidth, destHeight);
      }
    };

    ctx.fillStyle = 'rgba(0,0,0,0.24)';
    ctx.beginPath();
    ctx.ellipse(32, 101, 22, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    drawPart(1, 0, 10, 1, 12, 5, 42, 6, 0.08);
    drawPart(1, 1, 10, 16, 8, 11, 46, 88, 0.04);
    drawPart(11, 1, 1, 16, 54, 11, 6, 88, 0.22);

    return canvas.toDataURL('image/png');
  } catch (err) {
    console.warn('Error rendering 3D player cape preview:', err);
    return null;
  }
}

let _skinViewer3D = null;

const disposeSkinViewer3D = () => {
  if (_skinViewer3D) {
    try { _skinViewer3D.dispose(); } catch (err) { /* ignore */ }
    _skinViewer3D = null;
  }
};

const isValidSkinTextureSize = (w, h) => {
  if (w < 64 || h < 32 || (w % 64) !== 0) return false;
  const isLegacy = w === (h * 2) && (h % 32) === 0;
  const isModern = w === h && (h % 64) === 0;
  return isLegacy || isModern;
};

const isValidCapeTextureSize = (w, h) => {
  if (w < 64 || h < 32) return false;
  return w === (h * 2) && (w % 64) === 0;
};

const probeImage = (url) => new Promise((resolve) => {
  if (!url) { resolve(null); return; }
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => resolve(img);
  img.onerror = () => resolve(null);
  img.src = url;
});

export const updateSettingsPlayerPreview = () => {
  const bodyPreviewImg = getEl('settings-player-body-preview');
  const capePreviewImg = getEl('settings-player-cape-preview');
  const previewRow = getEl('settings-player-preview-row');
  const previewModeInput = getEl('settings-player-preview-3d');
  const previewModeRow = previewModeInput ? previewModeInput.closest('.row') : null;
  const canvas3d = getEl('settings-player-3d-canvas');
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

  const hideCanvas3D = () => {
    if (canvas3d) canvas3d.style.display = 'none';
    disposeSkinViewer3D();
  };

  const syncPreviewRowVisibility = () => {
    const hasBody = bodyPreviewImg.style.display !== 'none';
    const hasCape = capePreviewImg.style.display !== 'none';
    const has3D = canvas3d && canvas3d.style.display !== 'none';
    previewRow.style.display = (hasBody || hasCape || has3D) ? 'flex' : 'none';
    if (previewModeRow) {
      previewModeRow.style.display = previewRow.style.display === 'none' ? 'none' : 'flex';
    }
  };

  const isValidSkinTexture = (img) => img
    && isValidSkinTextureSize(Number(img.naturalWidth || img.width || 0), Number(img.naturalHeight || img.height || 0));

  const isValidCapeTexture = (img) => img
    && isValidCapeTextureSize(Number(img.naturalWidth || img.width || 0), Number(img.naturalHeight || img.height || 0));

  const acctType = normalizeAccountType(state.settingsState.account_type);
  const idOrName = state.settingsState.uuid || state.settingsState.username;
  const previewMode = state.settingsState.player_preview_mode === '3d' ? '3d' : '2d';
  const hasActiveCape = (() => {
    if (acctType !== 'Microsoft') return true;
    const activeCape = state.settingsState.active_cape;
    if (!activeCape) return false;
    if (typeof activeCape === 'string') return String(activeCape).trim().length > 0;
    if (typeof activeCape === 'object') {
      return String(activeCape.id || activeCape.url || activeCape.minecraft_texture_hash || '').trim().length > 0;
    }
    return false;
  })();
  const activeSkinModel = normalizeSkinModel(
    state.settingsState.active_skin && state.settingsState.active_skin.variant
  );

  hidePreviewImage(bodyPreviewImg);
  hidePreviewImage(capePreviewImg);
  hideCanvas3D();
  previewRow.style.display = 'none';
  if (previewModeRow) previewModeRow.style.display = 'none';

  if (!isOnlineAccountType(acctType) || !idOrName) return;

  const skinUrl = getTextureUrl('skin', idOrName);
  const capeUrl = hasActiveCape ? getTextureUrl('cape', idOrName) : '';

  if (previewMode === '3d' && canvas3d && typeof window !== 'undefined' && window.skinview3d) {
    (async () => {
      const [skinImg, capeImg] = await Promise.all([probeImage(skinUrl), probeImage(capeUrl)]);
      if (requestId !== state.settingsPreviewRequestId) return;
      const hasSkin = isValidSkinTexture(skinImg);
      const hasCape = isValidCapeTexture(capeImg);
      if (!hasSkin && !hasCape) {
        hideCanvas3D();
        syncPreviewRowVisibility();
        return;
      }
      try {
        disposeSkinViewer3D();
        canvas3d.style.display = '';
        const w = 220, h = 320;
        canvas3d.width = w;
        canvas3d.height = h;
        const viewer = new window.skinview3d.SkinViewer({
          canvas: canvas3d,
          width: w,
          height: h,
        });
        viewer.animation = new window.skinview3d.IdleAnimation();
        viewer.zoom = 0.85;
        viewer.fov = 20;
        if (viewer.controls) {
          viewer.controls.enableRotate = true;
          viewer.controls.enableZoom = true;
          viewer.controls.enablePan = false;
        }
        if (hasSkin) {
          await viewer.loadSkin(skinImg, { model: skinViewerModel(activeSkinModel) });
        }
        if (hasCape) {
          await viewer.loadCape(capeImg);
        } else {
          viewer.loadCape(null);
        }
        if (requestId !== state.settingsPreviewRequestId) {
          try { viewer.dispose(); } catch (e) { /* ignore */ }
          return;
        }
        _skinViewer3D = viewer;
        syncPreviewRowVisibility();
      } catch (err) {
        console.warn('Failed initializing 3D skin viewer:', err);
        hideCanvas3D();
        syncPreviewRowVisibility();
      }
    })();
    return;
  }

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
        bodyPreviewImg.width = 64;
        bodyPreviewImg.height = 128;
        const dataUrl = renderPlayerBodyPreview(skinImg, 4, activeSkinModel);
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
    skinImg.src = skinUrl;
  } catch (err) {
    console.warn('Error loading skin for preview:', err);
    hidePreviewImage(bodyPreviewImg);
    syncPreviewRowVisibility();
  }

  if (!capeUrl) {
    hidePreviewImage(capePreviewImg);
    syncPreviewRowVisibility();
    return;
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
        capePreviewImg.width = 50;
        capePreviewImg.height = 80;
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
    capeImg.src = capeUrl;
  } catch (err) {
    console.warn('Error loading cape for preview:', err);
    hidePreviewImage(capePreviewImg);
    syncPreviewRowVisibility();
  }
}

export const updateSettingsAccountSettingsButtonVisibility = () => {
  const accountSettingsRow = getEl('settings-account-settings-row');
  const accountSettingsBtn = getEl('settings-account-settings-btn');
  const accountSettingsInfo = accountSettingsRow ? accountSettingsRow.querySelector('.info-bubble') : null;
  if (!accountSettingsRow) return;

  const accountType = normalizeAccountType(state.settingsState.account_type);
  const showRow = accountType === 'Histolauncher' || accountType === 'Microsoft';
  toggleClass(accountSettingsRow, 'hidden', !showRow);

  if (accountSettingsBtn) {
    const labelKey = accountType === 'Microsoft'
      ? 'settings.account.skinEditor'
      : 'settings.account.accountSettings';
    accountSettingsBtn.textContent = t(labelKey);
    accountSettingsBtn.dataset.i18n = labelKey;
    accountSettingsBtn.title = accountType === 'Microsoft'
      ? t('settings.account.skinEditorTooltip')
      : t('settings.account.accountSettingsTooltip');
  }

  if (accountSettingsInfo) {
    const tooltipKey = accountType === 'Microsoft'
      ? 'settings.account.skinEditorTooltip'
      : 'settings.account.accountSettingsTooltip';
    accountSettingsInfo.dataset.i18nTooltip = tooltipKey;
    accountSettingsInfo.dataset.tooltip = t(tooltipKey);
  }
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
      await api('/api/settings', 'POST', settingsProfilePayload({ account_type: 'Local', uuid: '' }));
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
  frameWrap.style.border = '4px solid var(--color-border-strong)';
  frameWrap.style.background = 'var(--color-surface-card)';
  frameWrap.style.overflow = 'hidden';
  frameWrap.style.boxSizing = 'border-box';

  const loadingState = document.createElement('div');
  loadingState.style.height = '100%';
  loadingState.style.display = 'flex';
  loadingState.style.alignItems = 'center';
  loadingState.style.justifyContent = 'center';
  loadingState.style.padding = '20px';
  loadingState.style.textAlign = 'center';
  loadingState.textContent = t('settings.account.histolauncher.loadingAccountSettings');
  frameWrap.appendChild(loadingState);

  showMessageBox({
    title: t('settings.account.accountSettings'),
    customContent: frameWrap,
    buttons: [
      {
        label: t('common.close'),
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
  iframe.title = t('settings.account.histolauncher.accountSettingsFrameTitle');
  iframe.loading = 'lazy';
  iframe.referrerPolicy = 'strict-origin-when-cross-origin';
  iframe.sandbox = 'allow-scripts allow-same-origin allow-forms';
  iframe.style.width = '100%';
  iframe.style.height = '100%';
  iframe.style.border = '0';
  iframe.style.display = 'block';
  iframe.style.background = 'var(--color-surface-black)';
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
  const acctType = normalizeAccountType(state.settingsState.account_type);

  // Username error message
  let usernameTooltip = '';
  if (errors.username) {
    const len = username.length;
    if (len === 0) {
      usernameTooltip = t('settings.validation.username.empty');
    } else if (len < 3) {
      usernameTooltip = t('settings.validation.username.tooShort', { length: len });
    } else if (len > 16) {
      usernameTooltip = t('settings.validation.username.tooLong', { length: len });
    }
  }

  // RAM error message
  let ramTooltip = '';
  if (errors.min_ram || errors.max_ram) {
    const minRamStr = (state.settingsState.min_ram || '').toUpperCase();
    const maxRamStr = (state.settingsState.max_ram || '').toUpperCase();

    if (errors.max_ram) {
      if (!validateRAMFormat(maxRamStr)) {
        ramTooltip = t('settings.validation.ram.invalidFormat', { example: '4096M' });
      } else {
        const maxVal = parseRAMValue(maxRamStr);
        if (maxVal < 1) {
          ramTooltip = t('settings.validation.ram.maxTooLow');
        } else if (minRamStr && validateRAMFormat(minRamStr)) {
          const minVal = parseRAMValue(minRamStr);
          if (minVal > maxVal) {
            ramTooltip = t('settings.validation.ram.maxGreaterThanMin', { min: minRamStr, max: maxRamStr });
          }
        }
      }
    } else if (errors.min_ram) {
      ramTooltip = t('settings.validation.ram.invalidFormat', { example: '256M' });
    }
  }

  const selectedVData = state.selectedVersion
    ? state.versionsList.find((v) => `${v.category}/${v.folder}` === state.selectedVersion)
    : null;

  // Version row
  const versionText = state.selectedVersionDisplay
    ? makeInfoRowHTML('assets/images/library.png', t('home.info.version'), state.selectedVersionDisplay)
    : makeInfoRowHTML('assets/images/library.png', t('home.info.version'), t('home.info.noneSelected'));
  setHTML('info-version', versionText);

  // Account row
  const usernameHTML = errors.username
    ? makeInfoRowErrorHTML(t('home.info.account'), username, acctType, usernameTooltip)
    : makeInfoRowHTML('assets/images/settings.gif', t('home.info.account'), username, acctType);
  setHTML('info-username', usernameHTML);

  // RAM row
  const minRam = (state.settingsState.min_ram || '2048M').toUpperCase();
  const maxRam = (state.settingsState.max_ram || '4096M').toUpperCase();
  const ramHTML = errors.min_ram || errors.max_ram
    ? makeInfoRowErrorHTML(t('home.info.ramLimit'), `${minRam}B - ${maxRam}B`, null, ramTooltip)
    : makeInfoRowHTML('assets/images/settings.gif', t('home.info.ramLimit'), `${minRam}B - ${maxRam}B`);
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
    storageParens = t('home.info.storage.overridden');
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

  let storageValue = t('home.info.storage.global');
  if (effectiveStorageMode === 'version') {
    storageValue = t('home.info.storage.version');
  } else if (effectiveStorageMode === 'custom') {
    const customLabel = t('home.info.storage.custom');
    storageValue = effectiveStoragePath ? `${customLabel} (${effectiveStoragePath})` : t('common.none');
  }

  const storageHTML =
    !hasStorageOverride && effectiveStorageMode === 'custom' && errors.storage_directory
      ? makeInfoRowErrorHTML(t('home.info.storageDirectory'), storageValue, storageParens, getCustomStorageDirectoryError())
      : makeInfoRowHTML('assets/images/folder.png', t('home.info.storageDirectory'), storageValue, storageParens);
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

  let javaRuntimeValue = t('settings.launcher.java.defaultPath');
  if (rawJavaPath && rawJavaPath !== JAVA_RUNTIME_PATH) {
    if (rawJavaPath === JAVA_RUNTIME_AUTO) {
      javaRuntimeValue = t('settings.launcher.java.auto');
    } else if (state.javaRuntimesLoaded) {
      const match = state.javaRuntimes.find((rt) => String(rt.path || '').trim() === rawJavaPath);
      javaRuntimeValue = match ? (formatJavaRuntimeShort(match) || t('settings.launcher.java.runtimeFallback')) : t('settings.launcher.java.missingShort');
    } else if (state.javaRuntimesLoadAttempted) {
      javaRuntimeValue = t('home.info.java.custom');
    } else {
      javaRuntimeValue = t('home.info.java.detecting');
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
  const javaRuntimeHTML = makeInfoRowHTML('assets/images/java_icon.png', t('home.info.javaRuntime'), javaRuntimeValue);
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
        infoCategoryEl.innerHTML = makeInfoRowHTML('assets/images/library.png', t('home.info.category'), vData.category);
        infoCategoryEl.classList.remove('hidden');
      }

      const sizeBytes = vData.total_size_bytes || (vData.raw && vData.raw.total_size_bytes) || 0;
      const assetsType = (vData.raw && vData.raw.full_assets === false) ? 'Lite' : 'Full';
      if (infoSizeEl) {
        if (sizeBytes > 0) {
          infoSizeEl.innerHTML = makeInfoRowHTML('assets/images/cobblestone.png', t('home.info.size'), formatBytes(sizeBytes), assetsType);
        } else {
          infoSizeEl.innerHTML = makeInfoRowHTML('assets/images/cobblestone.png', t('home.info.assets'), assetsType);
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
            t('home.info.loaders'),
            parts.length > 0 ? parts.join(', ') : t('common.none')
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

  const showOnlineAvatar = isOnlineAccountType(acctType) && !!state.settingsState.uuid;
  if (topbarProfilePic) {
    if (showOnlineAvatar) {
      topbarProfilePic.style.display = 'block';
      try {
        const skinImg = new Image();
        skinImg.onload = () => {
          if (!isValidSkinTextureSize(
            Number(skinImg.naturalWidth || skinImg.width || 0),
            Number(skinImg.naturalHeight || skinImg.height || 0)
          )) {
            topbarProfilePic.src = '/assets/images/unknown.png';
            return;
          }
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
  await setLauncherLanguage(state.settingsState.launcher_language || 'en');
  applyAppearanceSettings(state.settingsState);

  if (!state.settingsState.addons_view) {
    state.settingsState.addons_view = 'list';
  }

  state.settingsState.favorite_versions = normalizeFavoriteVersions(
    state.settingsState.favorite_versions
  );

  state.settingsState.account_type = normalizeAccountType(state.settingsState.account_type);

  if (isOnlineAccountType(state.settingsState.account_type)) {
    try {
      const currentUser = await api('/api/account/current', 'GET');
      if (currentUser.ok && currentUser.authenticated) {
        state.settingsState.account_type = normalizeAccountType(currentUser.account_type || state.settingsState.account_type);
        state.settingsState.username = currentUser.username;
        state.settingsState.uuid = currentUser.uuid;
        if (currentUser.texture_revision) {
          state.settingsState.texture_revision = currentUser.texture_revision;
        }
        if (currentUser.active_skin) {
          state.settingsState.active_skin = currentUser.active_skin;
        } else {
          delete state.settingsState.active_skin;
        }
        if (currentUser.active_cape) {
          state.settingsState.active_cape = currentUser.active_cape;
        } else {
          delete state.settingsState.active_cape;
        }
        if (state.settingsState.account_type === 'Histolauncher') {
          state.histolauncherUsername = currentUser.username;
        }
      } else {
        const unauthorized = !!currentUser.unauthorized;
        if (unauthorized) {
          console.warn('[Account] Session verification failed (unauthorized):', currentUser.error);
          state.settingsState.account_type = 'Local';
          state.settingsState.username = data.username || 'Player';
          state.settingsState.uuid = null;
          await api('/api/account/disconnect', 'POST', {});
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

    const isOnlineAccount = isOnlineAccountType(state.settingsState.account_type);
    usernameInput.disabled = isOnlineAccount;

    if (usernameRow) {
      usernameRow.style.display = isOnlineAccount ? 'none' : 'block';
    }
  }

  const minRamInput = getEl('settings-min-ram');
  if (minRamInput) minRamInput.value = state.settingsState.min_ram || '32M';

  const maxRamInput = getEl('settings-max-ram');
  if (maxRamInput) maxRamInput.value = state.settingsState.max_ram || '4096M';

  const resolutionWidthInput = getEl('settings-resolution-width');
  if (resolutionWidthInput) resolutionWidthInput.value = state.settingsState.game_resolution_width || '854';

  const resolutionHeightInput = getEl('settings-resolution-height');
  if (resolutionHeightInput) resolutionHeightInput.value = state.settingsState.game_resolution_height || '480';

  const fullscreenInput = getEl('settings-game-fullscreen');
  if (fullscreenInput) fullscreenInput.checked = isTruthySetting(state.settingsState.game_fullscreen);

  const demoModeInput = getEl('settings-demo-mode');
  if (demoModeInput) demoModeInput.checked = isTruthySetting(state.settingsState.game_demo_mode);

  const extraJvmInput = getEl('settings-extra-jvm-args');
  if (extraJvmInput) extraJvmInput.value = state.settingsState.extra_jvm_args || '';

  const themeSelect = getEl('settings-launcher-theme');
  if (themeSelect) themeSelect.value = state.settingsState.launcher_theme || 'dark';

  const validUiSizes = ['small', 'normal', 'large', 'extra-large'];
  const launcherUiSize = validUiSizes.includes(String(state.settingsState.launcher_ui_size || '').trim().toLowerCase())
    ? String(state.settingsState.launcher_ui_size).trim().toLowerCase()
    : 'normal';
  state.settingsState.launcher_ui_size = launcherUiSize;
  const uiSizeSelect = getEl('settings-launcher-ui-size');
  if (uiSizeSelect) uiSizeSelect.value = launcherUiSize;

  const languageSelect = getEl('settings-launcher-language');
  if (languageSelect) languageSelect.value = state.settingsState.launcher_language || 'en';

  const densitySelect = getEl('settings-layout-density');
  if (densitySelect) densitySelect.value = state.settingsState.layout_density === 'compact' ? 'compact' : 'comfortable';

  const compactSidebarInput = getEl('settings-compact-sidebar');
  if (compactSidebarInput) compactSidebarInput.checked = isTruthySetting(state.settingsState.compact_sidebar);

  const playerPreview3dInput = getEl('settings-player-preview-3d');
  if (playerPreview3dInput) playerPreview3dInput.checked = state.settingsState.player_preview_mode === '3d';

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

  const showThirdPartyEl = getEl('settings-show-third-party-versions');
  if (showThirdPartyEl) showThirdPartyEl.checked = isTruthySetting(state.settingsState.show_third_party_versions);

  const discordRpcEl = getEl('settings-discord-rpc');
  if (discordRpcEl) discordRpcEl.checked = !('discord_rpc_enabled' in state.settingsState) || isTruthySetting(state.settingsState.discord_rpc_enabled);

  const desktopNotificationsEl = getEl('settings-desktop-notifications');
  if (desktopNotificationsEl) desktopNotificationsEl.checked = !('desktop_notifications_enabled' in state.settingsState) || isTruthySetting(state.settingsState.desktop_notifications_enabled);

  const allowAllOverrideClasspathEl = getEl('settings-allow-override-classpath-all-modloaders');
  if (allowAllOverrideClasspathEl) {
    allowAllOverrideClasspathEl.checked = isTruthySetting(state.settingsState.allow_override_classpath_all_modloaders);
  }

  const accountSelect = getEl('settings-account-type');
  const connectBtn = getEl('connect-account-btn');
  const disconnectBtn = getEl('disconnect-account-btn');
  const acctType = normalizeAccountType(state.settingsState.account_type);

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
  autoOpt.textContent = t('settings.launcher.java.auto');
  select.appendChild(autoOpt);

  const pathOpt = document.createElement('option');
  pathOpt.value = JAVA_RUNTIME_PATH;
  pathOpt.textContent = t('settings.launcher.java.defaultPath');
  select.appendChild(pathOpt);

  state.javaRuntimes.forEach((rt) => {
    const opt = document.createElement('option');
    opt.value = rt.path || '';
    opt.textContent = rt.display || rt.path || t('settings.launcher.java.runtimeFallback');
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
    missingOpt.textContent = t('settings.launcher.java.missing', { path: selectedRaw });
    select.appendChild(missingOpt);
  }

  const installOpt = document.createElement('option');
  installOpt.value = JAVA_RUNTIME_INSTALL_OPTION;
  installOpt.textContent = t('settings.launcher.java.install');
  installOpt.style.fontStyle = 'italic';
  installOpt.style.color = 'var(--color-text-disabled)';
  select.appendChild(installOpt);

  let selectedValue = selectedRaw || JAVA_RUNTIME_PATH;
  if (selectedValue !== JAVA_RUNTIME_AUTO && selectedValue !== JAVA_RUNTIME_PATH) {
    selectedValue = selectedRaw;
  }
  select.value = selectedValue;

  return true;
};
