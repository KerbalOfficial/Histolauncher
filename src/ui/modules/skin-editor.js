// ui/modules/skin-editor.js

import { api } from './api.js';
import {
  bindKeyboardActivation,
  imageAttachErrorPlaceholder,
  wireCardActionArrowNavigation,
} from './dom-utils.js';
import { t } from './i18n.js';
import { showMessageBox } from './modal.js';
import { state } from './state.js';
import {
  bumpTextureRevision,
  getTextureUrl,
} from './textures.js';
import {
  updateHomeInfo,
  updateSettingsPlayerPreview,
} from './home.js';

const NONE_CAPE_ID = '__none__';
const MAX_CLIENT_SKIN_UPLOAD_BYTES = 2 * 1024 * 1024;
const UNKNOWN_SKIN_PREVIEW_URL = 'assets/images/unknown_skin.png';

let activeEditor = null;

const isEditorActive = (editor) => {
  if (activeEditor !== editor) return false;
  const overlay = document.getElementById('msgbox-overlay');
  if (overlay && overlay.classList.contains('hidden')) return false;
  const box = document.getElementById('msgbox-box');
  return !box || box.classList.contains('skin-editor-box');
};

const createEl = (tag, className = '', text = '') => {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text) el.textContent = text;
  return el;
};

const normalizeEntryId = (entry) => String(entry && entry.id || '').trim();
const isDefaultSkinEntry = (entry) => !!(entry && (entry.default || entry.builtin));
const normalizeSkinModel = (model) => String(model || '').trim().toLowerCase() === 'slim' ? 'slim' : 'classic';

const defaultSkinTextureIdentifier = (entry, model = '') => {
  if (!isDefaultSkinEntry(entry)) return '';
  const selectedModel = normalizeSkinModel(model || entry.variant);
  const textureIds = entry.texture_ids && typeof entry.texture_ids === 'object' ? entry.texture_ids : {};
  return String(textureIds[selectedModel] || entry.texture_id || entry.id || '').trim();
};

const hashFromUrl = (url) => {
  try {
    const parsed = new URL(String(url || ''), window.location.origin);
    const last = parsed.pathname.split('/').filter(Boolean).pop() || '';
    return /^[a-f0-9]{32,128}$/i.test(last) ? last : '';
  } catch (err) {
    return '';
  }
};

const textureIdentifierForEntry = (type, entry, profile) => {
  if (type === 'skin' && isDefaultSkinEntry(entry)) {
    return defaultSkinTextureIdentifier(entry);
  }
  if (entry && entry.local && entry.id) return String(entry.id).trim();
  const hash = String(entry && (entry.texture_hash || hashFromUrl(entry.url)) || '').trim();
  if (hash) return hash;
  if (type === 'cape' && entry) return '';
  return String(profile && profile.uuid || state.settingsState.uuid || state.settingsState.username || '').trim();
};

const textureUrlForEntry = (type, entry, profile) => {
  const identifier = textureIdentifierForEntry(type, entry, profile);
  return identifier ? getTextureUrl(type, identifier) : '';
};

const getActiveCapeId = (profile) => normalizeEntryId(profile && profile.active_cape) || '';
const entryHasOwnCapeId = (entry) => !!(entry && Object.prototype.hasOwnProperty.call(entry, 'cape_id'));
const capePayloadId = (capeId) => capeId && capeId !== NONE_CAPE_ID ? capeId : '';
const findCapeById = (profile, capeId) => {
  const cleanId = String(capeId || '').trim();
  if (!cleanId) return null;
  return (Array.isArray(profile && profile.capes) ? profile.capes : [])
    .find((entry) => normalizeEntryId(entry) === cleanId) || null;
};
const getSkinEntryCapeId = (entry, profile) => {
  if (entry && (entry.local || isDefaultSkinEntry(entry)) && entryHasOwnCapeId(entry)) {
    return String(entry.cape_id || '').trim();
  }
  return entry && entry.active ? getActiveCapeId(profile) : '';
};
const getSkinEntryCape = (entry, profile) => findCapeById(profile, getSkinEntryCapeId(entry, profile));

const formDraftKey = (entry) => normalizeEntryId(entry) || '__new__';

const createFormDraft = (editor) => {
  const profile = editor.profile || {};
  const editingSkin = editor.editingSkin || null;
  const editingCapeId = editingSkin && (editingSkin.local || isDefaultSkinEntry(editingSkin)) && entryHasOwnCapeId(editingSkin)
    ? String(editingSkin.cape_id || '').trim()
    : getActiveCapeId(profile);
  return {
    key: formDraftKey(editingSkin),
    name: editingSkin && editingSkin.name || '',
    variant: normalizeSkinModel(editingSkin && editingSkin.variant),
    capeId: editingCapeId || NONE_CAPE_ID,
    skinDataUrl: '',
    fileBase64: '',
    fileName: '',
  };
};

const getFormDraft = (editor) => {
  const key = formDraftKey(editor.editingSkin || null);
  if (!editor.formDraft || editor.formDraft.key !== key) {
    editor.formDraft = createFormDraft(editor);
  }
  return editor.formDraft;
};

const readFileDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result || ''));
  reader.onerror = () => reject(reader.error || new Error('Failed to read file'));
  reader.readAsDataURL(file);
});

const loadImage = (url) => new Promise((resolve) => {
  if (!url) {
    resolve(null);
    return;
  }
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => resolve(img);
  img.onerror = () => resolve(null);
  img.src = url;
});

const captureViewerCameraState = (viewer) => {
  const editor = viewer && viewer._skinEditorOwner;
  const key = viewer && viewer._skinEditorViewerKey;
  const camera = viewer && viewer.camera;
  if (!editor || !key || !camera) return;
  editor.viewerCameraStates = editor.viewerCameraStates || {};
  editor.viewerCameraStates[key] = {
    position: typeof camera.position?.toArray === 'function' ? camera.position.toArray() : null,
    quaternion: typeof camera.quaternion?.toArray === 'function' ? camera.quaternion.toArray() : null,
    target: typeof viewer.controls?.target?.toArray === 'function' ? viewer.controls.target.toArray() : null,
  };
};

const restoreViewerCameraState = (editor, viewer, key) => {
  const state = editor && editor.viewerCameraStates && editor.viewerCameraStates[key];
  const camera = viewer && viewer.camera;
  if (!state || !camera) return;
  try {
    if (state.position && typeof camera.position?.fromArray === 'function') camera.position.fromArray(state.position);
    if (state.quaternion && typeof camera.quaternion?.fromArray === 'function') camera.quaternion.fromArray(state.quaternion);
    if (state.target && typeof viewer.controls?.target?.fromArray === 'function') viewer.controls.target.fromArray(state.target);
    if (viewer.controls && typeof viewer.controls.update === 'function') viewer.controls.update();
  } catch (err) {
    // Camera state is opportunistic; a failed restore should not block the preview.
  }
};

const disposeViewer = (viewer) => {
  if (!viewer) return;
  captureViewerCameraState(viewer);
  try { viewer.dispose(); } catch (err) { /* ignore */ }
};

const disposeEditorViewers = (editor) => {
  if (!editor || !Array.isArray(editor.viewers)) return;
  editor.viewers.forEach(disposeViewer);
  editor.viewers = [];
};

const disposeTargetViewer = (target) => {
  if (!target || !target._skinEditorViewer) return;
  disposeViewer(target._skinEditorViewer);
  target._skinEditorViewer = null;
};

const isValidSkinImage = (img) => {
  const width = Number(img && (img.naturalWidth || img.width) || 0);
  const height = Number(img && (img.naturalHeight || img.height) || 0);
  return (width === 64 && height === 64) || (width === 64 && height === 32);
};

const isValidCapeImage = (img) => {
  const width = Number(img && (img.naturalWidth || img.width) || 0);
  const height = Number(img && (img.naturalHeight || img.height) || 0);
  return width >= 64 && height >= 32 && width === height * 2 && (width % 64) === 0;
};

const skinViewerModel = (model) => model === 'slim' ? 'slim' : 'default';

const renderSkinPlaceholderInto = (target) => {
  if (!target) return;
  disposeTargetViewer(target);
  target.innerHTML = '';
  const img = document.createElement('img');
  img.alt = t('skinEditor.skinPreviewAlt');
  img.src = 'assets/images/unknown.png';
  imageAttachErrorPlaceholder(img, 'assets/images/unknown.png');
  target.appendChild(img);
};

const renderSkinViewerInto = async (editor, target, skinUrl, {
  capeUrl = '',
  model = 'classic',
  width = 128,
  height = 180,
  zoom = 0.82,
  interactive = false,
  viewerKey = 'preview',
} = {}) => {
  if (!target) return;
  const renderToken = editor.renderToken || 0;
  const targetNonce = (target._skinEditorRenderNonce || 0) + 1;
  target._skinEditorRenderNonce = targetNonce;
  disposeTargetViewer(target);
  target.innerHTML = '';
  const cleanSkinUrl = String(skinUrl || '').trim();
  if (!cleanSkinUrl || typeof window === 'undefined' || !window.skinview3d) {
    renderSkinPlaceholderInto(target);
    return;
  }

  const canvas = document.createElement('canvas');
  canvas.className = 'skin-editor-skin-viewer';
  canvas.width = width;
  canvas.height = height;
  target.appendChild(canvas);

  const [skinImg, capeImg] = await Promise.all([
    loadImage(cleanSkinUrl),
    capeUrl ? loadImage(capeUrl) : Promise.resolve(null),
  ]);
  if (!isEditorActive(editor) || renderToken !== editor.renderToken || target._skinEditorRenderNonce !== targetNonce || !target.isConnected) return;
  if (!isValidSkinImage(skinImg)) {
    renderSkinPlaceholderInto(target);
    return;
  }

  try {
    const viewer = new window.skinview3d.SkinViewer({ canvas, width, height });
    target._skinEditorViewer = viewer;
    target._skinEditorViewerKey = viewerKey;
    viewer._skinEditorOwner = editor;
    viewer._skinEditorViewerKey = viewerKey;
    editor.viewers.push(viewer);
    try {
      viewer.background = null;
      if (viewer.renderer && typeof viewer.renderer.setClearColor === 'function') {
        viewer.renderer.setClearColor(0x000000, 0);
      }
    } catch (err) { /* ignore */ }
    viewer.animation = new window.skinview3d.IdleAnimation();
    viewer.zoom = zoom;
    viewer.fov = 20;
    if (viewer.controls) {
      viewer.controls.enableRotate = !!interactive;
      viewer.controls.enableZoom = !!interactive;
      viewer.controls.enablePan = false;
    }
    restoreViewerCameraState(editor, viewer, viewerKey);
    await viewer.loadSkin(skinImg, { model: skinViewerModel(model) });
    if (isValidCapeImage(capeImg)) {
      await viewer.loadCape(capeImg);
    } else {
      viewer.loadCape(null);
    }
    if (!isEditorActive(editor) || renderToken !== editor.renderToken || target._skinEditorRenderNonce !== targetNonce || !target.isConnected) {
      disposeViewer(viewer);
    }
  } catch (err) {
    console.warn('Failed rendering skin editor 3D preview:', err);
    renderSkinPlaceholderInto(target);
  }
};

const renderCapeFacePreview = (img, side = 'front') => {
  if (!img) return null;
  try {
    const textureScale = img.width / 64;
    const scale = 8;
    const canvas = document.createElement('canvas');
    canvas.width = 10 * scale;
    canvas.height = 16 * scale;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    const sourceX = side === 'back' ? 12 : 1;
    ctx.drawImage(
      img,
      sourceX * textureScale,
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
    console.warn('Error rendering cape face preview:', err);
    return null;
  }
};

const drawCapeOnPlayerPreview = (ctx, capeImg, scale, side = 'front', offsetX = 0, offsetY = 0) => {
  if (!ctx || !isValidCapeImage(capeImg)) return;
  const capeScale = capeImg.width / 64;
  const sourceX = side === 'back' ? 12 : 1;
  ctx.drawImage(
    capeImg,
    sourceX * capeScale,
    1 * capeScale,
    10 * capeScale,
    16 * capeScale,
    offsetX + 3 * scale,
    offsetY + 8 * scale,
    10 * scale,
    16 * scale
  );
};

const renderPlayerFrontPreview = (skinImg, capeImg, scale = 4, model = 'classic') => {
  if (!skinImg) return null;
  try {
    const textureScale = skinImg.width / 64;
    const baseHeight = Math.round(skinImg.height / textureScale);
    const overlayInflate = Math.max(1, Math.round(scale * 0.25));
    const pad = overlayInflate;
    const canvas = document.createElement('canvas');
    canvas.width = 16 * scale + pad * 2;
    canvas.height = 32 * scale + pad * 2;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    const drawSkinPart = (sx, sy, sw, sh, dx, dy, dw, dh) => {
      ctx.drawImage(skinImg, sx * textureScale, sy * textureScale, sw * textureScale, sh * textureScale, dx, dy, dw, dh);
    };
    const drawOverlayPart = (sx, sy, sw, sh, dx, dy, dw, dh) => {
      drawSkinPart(sx, sy, sw, sh, dx - overlayInflate, dy - overlayInflate, dw + overlayInflate * 2, dh + overlayInflate * 2);
    };

    drawCapeOnPlayerPreview(ctx, capeImg, scale, 'back', pad, pad);

    const headX = pad + 4 * scale;
    const headY = pad;
    const bodyX = pad + 4 * scale;
    const bodyY = pad + 8 * scale;
    const isSlim = model === 'slim' && (skinImg.width === skinImg.height);
    const armWidth = isSlim ? 3 : 4;
    const leftArmX = pad + 12 * scale;
    const rightArmX = pad + (isSlim ? 1 * scale : 0);
    const armY = pad + 8 * scale;
    const leftLegX = pad + 8 * scale;
    const rightLegX = pad + 4 * scale;
    const legY = pad + 20 * scale;

    drawSkinPart(8, 8, 8, 8, headX, headY, 8 * scale, 8 * scale);
    drawSkinPart(20, 20, 8, 12, bodyX, bodyY, 8 * scale, 12 * scale);
    drawSkinPart(44, 20, armWidth, 12, rightArmX, armY, armWidth * scale, 12 * scale);
    drawSkinPart(4, 20, 4, 12, rightLegX, legY, 4 * scale, 12 * scale);

    if (baseHeight <= 32) {
      drawSkinPart(44, 20, armWidth, 12, leftArmX, armY, armWidth * scale, 12 * scale);
      drawSkinPart(4, 20, 4, 12, leftLegX, legY, 4 * scale, 12 * scale);
    } else {
      drawSkinPart(36, 52, armWidth, 12, leftArmX, armY, armWidth * scale, 12 * scale);
      drawSkinPart(20, 52, 4, 12, leftLegX, legY, 4 * scale, 12 * scale);
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
    console.warn('Error rendering player front preview:', err);
    return null;
  }
};

const renderPlayerBackPreview = (skinImg, capeImg, scale = 4, model = 'classic') => {
  if (!skinImg) return null;
  try {
    const textureScale = skinImg.width / 64;
    const baseHeight = Math.round(skinImg.height / textureScale);
    const isSlim = model === 'slim' && (skinImg.width === skinImg.height);
    const armWidth = isSlim ? 3 : 4;
    const overlayInflate = Math.max(1, Math.round(scale * 0.25));
    const pad = overlayInflate;
    const canvas = document.createElement('canvas');
    canvas.width = 16 * scale + pad * 2;
    canvas.height = 32 * scale + pad * 2;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    const drawSkinPart = (sx, sy, sw, sh, dx, dy, dw, dh) => {
      ctx.drawImage(skinImg, sx * textureScale, sy * textureScale, sw * textureScale, sh * textureScale, dx, dy, dw, dh);
    };
    const drawOverlayPart = (sx, sy, sw, sh, dx, dy, dw, dh) => {
      drawSkinPart(sx, sy, sw, sh, dx - overlayInflate, dy - overlayInflate, dw + overlayInflate * 2, dh + overlayInflate * 2);
    };
    const headX = pad + 4 * scale;
    const headY = pad;
    const bodyX = pad + 4 * scale;
    const bodyY = pad + 8 * scale;
    const leftArmX = pad + (isSlim ? 1 * scale : 0);
    const rightArmX = pad + 12 * scale;
    const armY = pad + 8 * scale;
    const leftLegX = pad + 4 * scale;
    const rightLegX = pad + 8 * scale;
    const legY = pad + 20 * scale;
    const rightArmBackX = isSlim ? 51 : 52;
    const leftArmBackX = baseHeight <= 32 ? 52 : (isSlim ? 43 : 44);
    const leftArmBackY = baseHeight <= 32 ? 20 : 52;
    const leftLegBackX = baseHeight <= 32 ? 12 : 28;
    const leftLegBackY = baseHeight <= 32 ? 20 : 52;

    drawSkinPart(24, 8, 8, 8, headX, headY, 8 * scale, 8 * scale);
    drawSkinPart(32, 20, 8, 12, bodyX, bodyY, 8 * scale, 12 * scale);
    drawSkinPart(leftArmBackX, leftArmBackY, armWidth, 12, leftArmX, armY, armWidth * scale, 12 * scale);
    drawSkinPart(rightArmBackX, 20, armWidth, 12, rightArmX, armY, armWidth * scale, 12 * scale);
    drawSkinPart(leftLegBackX, leftLegBackY, 4, 12, leftLegX, legY, 4 * scale, 12 * scale);
    drawSkinPart(12, 20, 4, 12, rightLegX, legY, 4 * scale, 12 * scale);
    drawOverlayPart(56, 8, 8, 8, headX, headY, 8 * scale, 8 * scale);

    if (baseHeight >= 64) {
      drawOverlayPart(32, 36, 8, 12, bodyX, bodyY, 8 * scale, 12 * scale);
      drawOverlayPart(isSlim ? 59 : 60, 52, armWidth, 12, leftArmX, armY, armWidth * scale, 12 * scale);
      drawOverlayPart(isSlim ? 51 : 52, 36, armWidth, 12, rightArmX, armY, armWidth * scale, 12 * scale);
      drawOverlayPart(12, 52, 4, 12, leftLegX, legY, 4 * scale, 12 * scale);
      drawOverlayPart(12, 36, 4, 12, rightLegX, legY, 4 * scale, 12 * scale);
    }

    drawCapeOnPlayerPreview(ctx, capeImg, scale, 'front', pad, pad);

    return canvas.toDataURL('image/png');
  } catch (err) {
    console.warn('Error rendering player back preview:', err);
    return null;
  }
};

const renderDualPreviewImages = (target, frontSrc, backSrc, alt, className) => {
  target.innerHTML = '';
  const front = document.createElement('img');
  front.className = `${className} skin-editor-preview-front`;
  front.alt = alt || '';
  front.src = frontSrc || 'assets/images/unknown.png';
  imageAttachErrorPlaceholder(front, 'assets/images/unknown.png');
  target.appendChild(front);

  const back = document.createElement('img');
  back.className = `${className} skin-editor-preview-back`;
  back.alt = alt || '';
  back.src = backSrc || frontSrc || 'assets/images/unknown.png';
  imageAttachErrorPlaceholder(back, 'assets/images/unknown.png');
  target.appendChild(back);
};

const renderSkinCardPreviewInto = async (editor, target, skinUrl, {
  capeUrl = '',
  model = 'classic',
  alt = '',
} = {}) => {
  if (!target) return;
  const renderToken = editor.renderToken || 0;
  target.innerHTML = '';
  const [skinImg, capeImg] = await Promise.all([
    loadImage(skinUrl),
    capeUrl ? loadImage(capeUrl) : Promise.resolve(null),
  ]);
  if (!isEditorActive(editor) || renderToken !== editor.renderToken || !target.isConnected) return;
  if (!isValidSkinImage(skinImg)) {
    renderSkinPlaceholderInto(target);
    return;
  }
  renderDualPreviewImages(
    target,
    renderPlayerFrontPreview(skinImg, capeImg, 4, model),
    renderPlayerBackPreview(skinImg, capeImg, 4, model),
    alt || t('skinEditor.skinPreviewAlt'),
    'skin-editor-skin-preview'
  );
};

const renderCapePreviewInto = async (editor, target, url, alt = '') => {
  if (!target) return;
  const renderToken = editor.renderToken || 0;
  target.innerHTML = '';
  const img = await loadImage(url);
  if (!isEditorActive(editor) || renderToken !== editor.renderToken || !target.isConnected) return;
  if (!isValidCapeImage(img)) {
    renderDualPreviewImages(target, '', '', alt || t('skinEditor.cape'), 'skin-editor-cape-image');
    return;
  }
  renderDualPreviewImages(
    target,
    renderCapeFacePreview(img, 'front'),
    renderCapeFacePreview(img, 'back'),
    alt || t('skinEditor.cape'),
    'skin-editor-cape-image'
  );
};

const applyTextureResult = (result) => {
  if (!result || !result.ok) return;
  state.settingsState.account_type = 'Microsoft';
  if (result.username) state.settingsState.username = result.username;
  if (result.uuid) state.settingsState.uuid = result.uuid;
  if (result.texture_revision) {
    state.settingsState.texture_revision = result.texture_revision;
  } else {
    bumpTextureRevision();
  }
  const textureProfile = result.textures || result;
  if (Object.prototype.hasOwnProperty.call(textureProfile, 'active_skin')) {
    if (textureProfile.active_skin) state.settingsState.active_skin = textureProfile.active_skin;
    else delete state.settingsState.active_skin;
  }
  if (Object.prototype.hasOwnProperty.call(textureProfile, 'active_cape')) {
    if (textureProfile.active_cape) state.settingsState.active_cape = textureProfile.active_cape;
    else delete state.settingsState.active_cape;
  }
  updateSettingsPlayerPreview();
  updateHomeInfo();
};

const profileFromResult = (result) => result && (result.textures || {
  username: result.username,
  uuid: result.uuid,
  skins: result.skins,
  capes: result.capes,
  active_skin: result.active_skin,
  active_cape: result.active_cape,
});

const setEditorProfileFromResult = (editor, result) => {
  applyTextureResult(result);
  editor.profile = profileFromResult(result) || editor.profile;
};

const statusEl = (text = '', kind = '') => {
  const el = createEl('div', 'skin-editor-status');
  if (kind) el.classList.add(kind);
  el.textContent = text;
  return el;
};

const setBusy = (editor, busy) => {
  editor.busy = !!busy;
  if (editor.root) {
    editor.root.classList.toggle('is-busy', !!busy);
    editor.root.querySelectorAll('button, input').forEach((el) => {
      if (el.dataset.keepEnabled === '1') return;
      if (el.dataset.locked === '1') {
        el.disabled = true;
        return;
      }
      el.disabled = !!busy;
    });
  }
};

const refreshProfile = async (editor) => {
  setBusy(editor, true);
  editor.message = t('skinEditor.loading');
  editor.messageKind = '';
  renderEditor(editor);
  try {
    const result = await api('/api/account/microsoft/textures', 'GET');
    if (!isEditorActive(editor)) return;
    if (!result || !result.ok) {
      throw new Error(result && result.error || t('skinEditor.errors.loadFailed'));
    }
    setEditorProfileFromResult(editor, result);
    editor.message = '';
    editor.messageKind = '';
  } catch (err) {
    if (!isEditorActive(editor)) return;
    editor.message = err && err.message ? err.message : String(err || t('skinEditor.errors.loadFailed'));
    editor.messageKind = 'error';
  } finally {
    if (!isEditorActive(editor)) return;
    setBusy(editor, false);
    renderEditor(editor);
  }
};

const runTextureAction = async (editor, action) => {
  setBusy(editor, true);
  editor.message = t('skinEditor.saving');
  editor.messageKind = '';
  renderEditor(editor);
  try {
    const result = await action();
    if (!isEditorActive(editor)) return;
    if (!result || !result.ok) {
      throw new Error(result && result.error || t('skinEditor.errors.saveFailed'));
    }
    setEditorProfileFromResult(editor, result);
    editor.message = t('skinEditor.saved');
    editor.messageKind = 'success';
    editor.formDraft = null;
    editor.pendingDeleteSkin = null;
    editor.mode = 'library';
  } catch (err) {
    if (!isEditorActive(editor)) return;
    editor.message = err && err.message ? err.message : String(err || t('skinEditor.errors.saveFailed'));
    editor.messageKind = 'error';
  } finally {
    if (!isEditorActive(editor)) return;
    setBusy(editor, false);
    renderEditor(editor);
  }
};

const createIconButton = (icon, label, { hoverIcon = '', active = false, activeIcon = '' } = {}) => {
  const btn = createEl('button', 'skin-editor-icon-btn');
  btn.type = 'button';
  btn.title = label;
  btn.setAttribute('aria-label', label);
  if (activeIcon) btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  const img = document.createElement('img');
  img.alt = '';
  const normalSrc = active && activeIcon ? activeIcon : icon;
  img.src = normalSrc;
  imageAttachErrorPlaceholder(img, 'assets/images/placeholder.png');
  btn.appendChild(img);
  if (hoverIcon || activeIcon) {
    btn.addEventListener('mouseenter', () => {
      img.src = hoverIcon || activeIcon || normalSrc;
    });
    btn.addEventListener('mouseleave', () => {
      img.src = active && activeIcon ? activeIcon : icon;
    });
  }
  return btn;
};

const createCurrentPanel = (editor) => {
  const profile = editor.profile || {};
  const panel = createEl('section', 'skin-editor-current');
  const header = createEl('div', 'skin-editor-panel-header');
  header.appendChild(createEl('h3', '', t('skinEditor.current')));

  const refreshBtn = createIconButton('assets/images/refresh.png', t('common.refresh'));
  refreshBtn.addEventListener('click', () => refreshProfile(editor));
  header.appendChild(refreshBtn);
  panel.appendChild(header);

  const preview = createEl('div', 'skin-editor-current-preview');
  panel.appendChild(preview);

  const activeSkin = profile.active_skin || null;
  const activeCape = profile.active_cape || null;
  renderSkinViewerInto(editor, preview,
    activeSkin ? textureUrlForEntry('skin', activeSkin, profile) : getTextureUrl('skin', profile.uuid || state.settingsState.uuid),
    {
      capeUrl: activeCape ? textureUrlForEntry('cape', activeCape, profile) : '',
      model: activeSkin && activeSkin.variant || 'classic',
      width: 220,
      height: 320,
      zoom: 0.85,
      interactive: true,
      viewerKey: 'current',
    }
  );

  const meta = createEl('div', 'skin-editor-current-meta');
  meta.appendChild(createEl('strong', '', profile.username || state.settingsState.username || t('settings.account.typeMicrosoft')));
  meta.appendChild(createEl('span', '', activeSkin && activeSkin.name || t('skinEditor.defaultSkin')));
  meta.appendChild(createEl('span', '', activeCape && activeCape.name || t('skinEditor.noCape')));
  panel.appendChild(meta);

  return panel;
};

const createSkinCard = (editor, entry, index) => {
  const profile = editor.profile || {};
  const card = createEl('div', 'skin-editor-card');
  if (entry.active) card.classList.add('active');
  if (isDefaultSkinEntry(entry)) card.classList.add('default');
  if (entry.favorite && !isDefaultSkinEntry(entry)) card.classList.add('favorite');
  bindKeyboardActivation(card, { ariaLabel: t('skinEditor.useSkin', { name: entry.name || `Skin ${index + 1}` }) });

  const preview = createEl('div', 'skin-editor-card-preview');
  card.appendChild(preview);
  const skinCape = getSkinEntryCape(entry, profile);
  renderSkinCardPreviewInto(editor, preview, textureUrlForEntry('skin', entry, profile), {
    capeUrl: skinCape ? textureUrlForEntry('cape', skinCape, profile) : '',
    model: entry.variant || 'classic',
    alt: entry.name || t('skinEditor.skin'),
  });

  const info = createEl('div', 'skin-editor-card-info');
  info.appendChild(createEl('strong', '', entry.name || t('skinEditor.skin')));
  info.appendChild(createEl('span', '', (entry.variant === 'slim') ? t('skinEditor.modelSlim') : t('skinEditor.modelWide')));
  card.appendChild(info);

  const actions = createEl('div', 'skin-editor-card-actions');

  if (!isDefaultSkinEntry(entry)) {
    const favoriteBtn = createIconButton('assets/images/unfilled_favorite.png', entry.favorite
      ? t('skinEditor.unfavoriteSkin', { name: entry.name || t('skinEditor.skin') })
      : t('skinEditor.favoriteSkin', { name: entry.name || t('skinEditor.skin') }), {
        hoverIcon: 'assets/images/filled_favorite.png',
        activeIcon: 'assets/images/filled_favorite.png',
        active: !!entry.favorite,
      });
    favoriteBtn.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      editor.pendingDeleteSkin = null;
      runTextureAction(editor, () => api('/api/account/microsoft/skin/favorite', 'POST', {
        skin_id: entry.id,
        favorite: !entry.favorite,
      }));
    });
    actions.appendChild(favoriteBtn);
  }

  const editBtn = createIconButton('assets/images/unfilled_pencil.png', t('common.edit'), {
    hoverIcon: 'assets/images/filled_pencil.png',
  });
  editBtn.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    editor.mode = 'form';
    editor.editingSkin = entry;
    editor.selectedCapeId = '';
    editor.formDraft = null;
    editor.pendingDeleteSkin = null;
    editor.message = '';
    renderEditor(editor);
  });
  actions.appendChild(editBtn);

  if (entry.local) {
    const deleteBtn = createIconButton('assets/images/unfilled_delete.png', t('skinEditor.deleteSkin', { name: entry.name || t('skinEditor.skin') }), {
      hoverIcon: 'assets/images/filled_delete.png',
    });
    deleteBtn.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      editor.pendingDeleteSkin = entry;
      editor.message = '';
      editor.messageKind = '';
      renderEditor(editor);
    });
    actions.appendChild(deleteBtn);
  }
  card.appendChild(actions);

  card.addEventListener('click', () => {
    if (entry.active || !entry.id) return;
    runTextureAction(editor, () => api('/api/account/microsoft/skin/select', 'POST', {
      skin_id: entry.id,
      variant: normalizeSkinModel(entry.variant),
      cape_id: capePayloadId(getSkinEntryCapeId(entry, profile)),
    }));
  });

  wireCardActionArrowNavigation(card);
  return card;
};

const createDeleteConfirm = (editor) => {
  const entry = editor.pendingDeleteSkin;
  if (!entry) return null;
  const name = entry.name || t('skinEditor.skin');
  const wrap = createEl('div', 'skin-editor-confirm');
  const text = createEl('div', 'skin-editor-confirm-text');
  text.appendChild(createEl('strong', '', t('skinEditor.deleteConfirmTitle')));
  text.appendChild(createEl('span', '', t('skinEditor.deleteConfirm', { name })));
  wrap.appendChild(text);

  const actions = createEl('div', 'skin-editor-confirm-actions');
  const cancelBtn = createEl('button', '', t('common.cancel'));
  cancelBtn.type = 'button';
  cancelBtn.addEventListener('click', () => {
    editor.pendingDeleteSkin = null;
    renderEditor(editor);
  });
  actions.appendChild(cancelBtn);

  const deleteBtn = createEl('button', 'danger', t('common.delete'));
  deleteBtn.type = 'button';
  deleteBtn.addEventListener('click', () => {
    runTextureAction(editor, () => api('/api/account/microsoft/skin/delete', 'POST', { skin_id: entry.id }));
  });
  actions.appendChild(deleteBtn);
  wrap.appendChild(actions);
  return wrap;
};

const createNewSkinCard = (editor) => {
  const card = createEl('div', 'skin-editor-card skin-editor-new-card');
  bindKeyboardActivation(card, { ariaLabel: t('skinEditor.newSkin') });
  const img = document.createElement('img');
  img.alt = '';
  img.src = 'assets/images/unfilled_plus.png';
  imageAttachErrorPlaceholder(img, 'assets/images/placeholder.png');
  card.appendChild(img);
  card.appendChild(createEl('strong', '', t('skinEditor.newSkin')));
  card.addEventListener('mouseenter', () => { img.src = 'assets/images/filled_plus.png'; });
  card.addEventListener('mouseleave', () => { img.src = 'assets/images/unfilled_plus.png'; });
  card.addEventListener('click', () => {
    editor.mode = 'form';
    editor.editingSkin = null;
    editor.selectedCapeId = '';
    editor.formDraft = null;
    editor.pendingDeleteSkin = null;
    editor.message = '';
    renderEditor(editor);
  });

  wireCardActionArrowNavigation(card);
  return card;
};

const createLibraryView = (editor) => {
  const profile = editor.profile || {};
  const root = createEl('div', 'skin-editor');
  editor.root = root;
  root.appendChild(createCurrentPanel(editor));

  const library = createEl('section', 'skin-editor-library');
  const header = createEl('div', 'skin-editor-library-header');
  header.appendChild(createEl('h3', '', t('skinEditor.library')));
  library.appendChild(header);

  if (editor.message) {
    library.appendChild(statusEl(editor.message, editor.messageKind));
  }
  const deleteConfirm = createDeleteConfirm(editor);
  if (deleteConfirm) library.appendChild(deleteConfirm);

  const skinGridTitle = createEl('h4', '', t('skinEditor.skins'));
  library.appendChild(skinGridTitle);
  const skinGrid = createEl('div', 'skin-editor-grid skin-editor-skin-grid');
  skinGrid.appendChild(createNewSkinCard(editor));
  const skins = Array.isArray(profile.skins) ? profile.skins : [];
  skins.forEach((entry, index) => {
    skinGrid.appendChild(createSkinCard(editor, entry, index));
  });
  library.appendChild(skinGrid);

  root.appendChild(library);
  setBusy(editor, editor.busy);
  return root;
};

const createModelOption = (name, value, checked) => {
  const label = createEl('label', 'skin-editor-model-option');
  const input = document.createElement('input');
  input.type = 'radio';
  input.name = 'skin-editor-model';
  input.value = value;
  input.checked = checked;
  label.appendChild(input);
  label.appendChild(createEl('span', '', name));
  return label;
};

const createCapeChoice = (editor, entry, selectedCapeId, onSelect) => {
  const noCape = !entry;
  const card = createEl('div', 'skin-editor-cape-card');
  const id = noCape ? NONE_CAPE_ID : normalizeEntryId(entry);
  if (id === selectedCapeId) card.classList.add('active');
  bindKeyboardActivation(card, {
    ariaLabel: noCape ? t('skinEditor.noCape') : t('skinEditor.useCape', { name: entry.name || t('skinEditor.cape') }),
  });

  const preview = createEl('div', 'skin-editor-cape-preview');
  if (entry) {
    renderCapePreviewInto(editor, preview, textureUrlForEntry('cape', entry, editor.profile), entry.name || t('skinEditor.cape'));
  } else {
    preview.appendChild(createEl('span', '', t('skinEditor.none')));
  }
  card.appendChild(preview);
  card.appendChild(createEl('strong', '', entry && entry.name || t('skinEditor.noCape')));
  card.addEventListener('click', () => onSelect(id));
  return card;
};

const createFormView = (editor) => {
  const profile = editor.profile || {};
  const editingSkin = editor.editingSkin || null;
  const editingDefaultSkin = isDefaultSkinEntry(editingSkin);
  const draft = getFormDraft(editor);
  editor.selectedCapeId = draft.capeId || NONE_CAPE_ID;

  const root = createEl('div', 'skin-editor skin-editor-form');
  editor.root = root;

  const previewPanel = createEl('section', 'skin-editor-current');
  const previewHeader = createEl('div', 'skin-editor-panel-header');
  previewHeader.appendChild(createEl('h3', '', editingSkin ? t('skinEditor.editSkin') : t('skinEditor.newSkin')));
  previewPanel.appendChild(previewHeader);

  const preview = createEl('div', 'skin-editor-current-preview skin-editor-upload-preview');
  previewPanel.appendChild(preview);
  root.appendChild(previewPanel);
  let selectedSkinDataUrl = draft.skinDataUrl || '';

  const formPanel = createEl('section', 'skin-editor-library skin-editor-form-panel');
  if (editor.message) {
    formPanel.appendChild(statusEl(editor.message, editor.messageKind));
  }

  const nameRow = createEl('label', 'skin-editor-field');
  nameRow.appendChild(createEl('span', '', t('skinEditor.name')));
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.maxLength = 80;
  nameInput.value = draft.name || '';
  nameInput.disabled = editingDefaultSkin;
  if (editingDefaultSkin) nameInput.dataset.locked = '1';
  nameRow.appendChild(nameInput);
  formPanel.appendChild(nameRow);

  const initialModel = normalizeSkinModel(draft.variant);
  const modelWrap = createEl('div', 'skin-editor-field');
  modelWrap.appendChild(createEl('span', '', t('skinEditor.playerModel')));
  const modelOptions = createEl('div', 'skin-editor-model-options');
  modelOptions.appendChild(createModelOption(t('skinEditor.modelWide'), 'classic', initialModel !== 'slim'));
  modelOptions.appendChild(createModelOption(t('skinEditor.modelSlim'), 'slim', initialModel === 'slim'));
  modelWrap.appendChild(modelOptions);
  formPanel.appendChild(modelWrap);

  const fileRow = createEl('div', 'skin-editor-field');
  fileRow.appendChild(createEl('span', '', t('skinEditor.skinFile')));
  const filePickRow = createEl('div', 'skin-editor-file-row');
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = 'image/png,.png';
  fileInput.hidden = true;
  const filePickBtn = createEl('button', '', t('common.chooseFile'));
  filePickBtn.type = 'button';
  const filePickLabel = createEl('span', 'skin-editor-file-label', t('common.noFileChosen'));
  const renderFilePickLabel = () => {
    const file = fileInput.files && fileInput.files[0];
    const name = file && file.name ? file.name : draft.fileName;
    filePickLabel.textContent = name || t('common.noFileChosen');
    filePickLabel.classList.toggle('has-file', !!name);
  };
  filePickBtn.addEventListener('click', () => fileInput.click());
  filePickRow.appendChild(filePickBtn);
  filePickRow.appendChild(filePickLabel);
  filePickRow.appendChild(fileInput);
  fileRow.appendChild(filePickRow);
  if (!editingDefaultSkin) {
    formPanel.appendChild(fileRow);
  }

  const capeTitle = createEl('h4', '', t('skinEditor.capeSelection'));
  formPanel.appendChild(capeTitle);
  const capeGrid = createEl('div', 'skin-editor-grid skin-editor-cape-grid');
  const currentModel = () => {
    const modelInput = root.querySelector('input[name="skin-editor-model"]:checked');
    return modelInput ? modelInput.value : 'classic';
  };
  const syncDraft = () => {
    draft.name = nameInput.value;
    draft.variant = currentModel();
    draft.capeId = editor.selectedCapeId || NONE_CAPE_ID;
    editor.formDraft = draft;
  };
  const selectedCapeEntry = () => {
    const selectedCapeId = editor.selectedCapeId || NONE_CAPE_ID;
    if (selectedCapeId === NONE_CAPE_ID) return null;
    return (Array.isArray(profile.capes) ? profile.capes : [])
      .find((entry) => normalizeEntryId(entry) === selectedCapeId) || null;
  };
  const selectedCapeUrl = () => {
    const entry = selectedCapeEntry();
    return entry ? textureUrlForEntry('cape', entry, profile) : '';
  };
  const selectedSkinUrl = () => {
    if (editingDefaultSkin) {
      const identifier = defaultSkinTextureIdentifier(editingSkin, currentModel());
      return identifier ? getTextureUrl('skin', identifier) : '';
    }
    if (selectedSkinDataUrl) return selectedSkinDataUrl;
    return editingSkin ? textureUrlForEntry('skin', editingSkin, profile) : '';
  };
  const renderUploadPreview = () => {
    const skinUrl = selectedSkinUrl();
    const previewSkinUrl = skinUrl || (!editingSkin ? UNKNOWN_SKIN_PREVIEW_URL : '');
    if (!previewSkinUrl) {
      renderSkinPlaceholderInto(preview);
      return;
    }
    renderSkinViewerInto(editor, preview, previewSkinUrl, {
      capeUrl: selectedCapeUrl(),
      model: currentModel(),
      width: 220,
      height: 320,
      zoom: 0.85,
      interactive: true,
      viewerKey: 'form',
    });
  };
  const rerenderCapeSelection = () => {
    capeGrid.innerHTML = '';
    capeGrid.appendChild(createCapeChoice(editor, null, editor.selectedCapeId, (id) => {
      editor.selectedCapeId = id;
      syncDraft();
      rerenderCapeSelection();
      renderUploadPreview();
    }));
    (Array.isArray(profile.capes) ? profile.capes : []).forEach((entry) => {
      capeGrid.appendChild(createCapeChoice(editor, entry, editor.selectedCapeId, (id) => {
        editor.selectedCapeId = id;
        syncDraft();
        rerenderCapeSelection();
        renderUploadPreview();
      }));
    });
  };
  rerenderCapeSelection();
  formPanel.appendChild(capeGrid);
  nameInput.addEventListener('input', syncDraft);
  modelOptions.querySelectorAll('input[name="skin-editor-model"]').forEach((input) => {
    input.addEventListener('change', () => {
      syncDraft();
      renderUploadPreview();
    });
  });

  const actions = createEl('div', 'skin-editor-form-actions');
  const backBtn = createEl('button', '', t('common.back'));
  backBtn.type = 'button';
  backBtn.dataset.keepEnabled = '1';
  backBtn.addEventListener('click', () => {
    editor.mode = 'library';
    editor.message = '';
    editor.selectedCapeId = '';
    editor.formDraft = null;
    renderEditor(editor);
  });
  actions.appendChild(backBtn);

  const saveBtn = createEl('button', 'primary', t('common.save'));
  saveBtn.type = 'button';
  saveBtn.addEventListener('click', async () => {
    const file = fileInput.files && fileInput.files[0] || null;
    const activeCapeId = getActiveCapeId(editor.profile || {});
    syncDraft();

    if (file && file.size > MAX_CLIENT_SKIN_UPLOAD_BYTES) {
      editor.message = t('skinEditor.errors.tooLarge');
      editor.messageKind = 'error';
      renderEditor(editor);
      return;
    }

    if (file) {
      let dataUrl;
      try {
        dataUrl = await readFileDataUrl(file);
      } catch (err) {
        editor.message = t('skinEditor.errors.readFailed');
        editor.messageKind = 'error';
        renderEditor(editor);
        return;
      }
      const image = await loadImage(dataUrl);
      if (!isValidSkinImage(image)) {
        editor.message = t('skinEditor.errors.invalidResolution');
        editor.messageKind = 'error';
        renderEditor(editor);
        return;
      }
      draft.skinDataUrl = dataUrl;
      draft.fileBase64 = dataUrl.includes(',') ? dataUrl.split(',', 2)[1] : dataUrl;
      draft.fileName = file.name || 'skin.png';
      selectedSkinDataUrl = dataUrl;
      syncDraft();
    }

    await runTextureAction(editor, async () => {
      let result = null;
      const selectedCapeId = draft.capeId || NONE_CAPE_ID;
      const selectedCapePayloadId = capePayloadId(selectedCapeId);
      const hasDraftSkin = !!draft.fileBase64;

      if (editingDefaultSkin && editingSkin && editingSkin.id) {
        result = await api('/api/account/microsoft/skin/save', 'POST', {
          skin_id: editingSkin.id,
          variant: draft.variant,
          cape_id: selectedCapePayloadId,
        });
      } else if (hasDraftSkin || (editingSkin && editingSkin.local && editingSkin.id)) {
        const payload = {
          skin_id: editingSkin && editingSkin.local ? editingSkin.id : '',
          name: draft.name,
          variant: draft.variant,
          cape_id: selectedCapePayloadId,
          file_name: draft.fileName || 'skin.png',
        };
        if (hasDraftSkin) payload.file_base64 = draft.fileBase64;
        result = await api('/api/account/microsoft/skin/save', 'POST', payload);
      }

      if (!result && selectedCapeId === NONE_CAPE_ID && activeCapeId) {
        result = await api('/api/account/microsoft/cape/disable', 'POST', {});
      } else if (!result && selectedCapeId !== NONE_CAPE_ID && selectedCapeId !== activeCapeId) {
        result = await api('/api/account/microsoft/cape/select', 'POST', { cape_id: selectedCapePayloadId });
      }

      if (!result) {
        return { ok: false, error: t('skinEditor.errors.chooseFileOrCape') };
      }
      return result;
    });
  });
  actions.appendChild(saveBtn);
  formPanel.appendChild(actions);

  fileInput.addEventListener('change', async () => {
    renderFilePickLabel();
    const file = fileInput.files && fileInput.files[0] || null;
    if (!file) {
      selectedSkinDataUrl = '';
      draft.skinDataUrl = '';
      draft.fileBase64 = '';
      draft.fileName = '';
      syncDraft();
      renderUploadPreview();
      return;
    }
    draft.skinDataUrl = '';
    draft.fileBase64 = '';
    draft.fileName = file.name || 'skin.png';
    syncDraft();
    try {
      selectedSkinDataUrl = await readFileDataUrl(file);
    } catch (err) {
      selectedSkinDataUrl = '';
      draft.skinDataUrl = '';
      draft.fileBase64 = '';
      draft.fileName = '';
      editor.message = t('skinEditor.errors.readFailed');
      editor.messageKind = 'error';
      syncDraft();
      renderEditor(editor);
      return;
    }
    draft.skinDataUrl = selectedSkinDataUrl;
    draft.fileBase64 = selectedSkinDataUrl.includes(',') ? selectedSkinDataUrl.split(',', 2)[1] : selectedSkinDataUrl;
    draft.fileName = file.name || 'skin.png';
    syncDraft();
    renderFilePickLabel();
    renderUploadPreview();
  });

  root.appendChild(formPanel);
  renderFilePickLabel();
  renderUploadPreview();
  setBusy(editor, editor.busy);
  return root;
};

function renderEditor(editor) {
  if (activeEditor !== editor) return;
  disposeEditorViewers(editor);
  editor.renderToken = (editor.renderToken || 0) + 1;
  const root = editor.mode === 'form' ? createFormView(editor) : createLibraryView(editor);
  const cleanup = () => {
    disposeEditorViewers(editor);
    if (activeEditor === editor) activeEditor = null;
  };
  if (!editor.controls) {
    editor.controls = showMessageBox({
      title: t('skinEditor.title'),
      customContent: root,
      boxClassList: ['skin-editor-box'],
      onClose: cleanup,
      buttons: [
        {
          label: t('common.close'),
          onClick: cleanup,
        },
      ],
    });
    return;
  }

  editor.controls = editor.controls.update({
    title: t('skinEditor.title'),
    customContent: root,
    boxClassList: ['skin-editor-box'],
    onClose: cleanup,
    buttons: [
      {
        label: t('common.close'),
        onClick: cleanup,
      },
    ],
  });
}

export const showMicrosoftSkinEditorModal = () => {
  const editor = {
    controls: null,
    root: null,
    profile: null,
    mode: 'library',
    editingSkin: null,
    selectedCapeId: '',
    formDraft: null,
    pendingDeleteSkin: null,
    viewerCameraStates: {},
    viewers: [],
    renderToken: 0,
    busy: false,
    message: t('skinEditor.loading'),
    messageKind: '',
  };
  activeEditor = editor;
  renderEditor(editor);
  refreshProfile(editor).then(() => {
    if (!isEditorActive(editor)) return;
    renderEditor(editor);
  });
};
