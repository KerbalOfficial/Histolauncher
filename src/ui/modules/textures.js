// ui/modules/textures.js

import { state } from './state.js';


export const bumpTextureRevision = () => {
  state.settingsState.texture_revision = Date.now();
  return state.settingsState.texture_revision;
};
export const getTextureUrl = (textureType, idOrName) => {
  if (!textureType || !idOrName) return '';
  const baseUrl = `/texture/${textureType}/${encodeURIComponent(idOrName)}`;
  const revision = Number(state.settingsState.texture_revision || 0);
  return revision > 0 ? `${baseUrl}?rev=${revision}` : baseUrl;
};

export const getVersionDisplayImageUrl = (category, folder) => {
  if (!category || !folder) return 'assets/images/version_placeholder.png';
  const baseUrl = `/clients/${category}/${folder}/display.png`;
  const revision = Number(state.settingsState.texture_revision || 0);
  return revision > 0 ? `${baseUrl}?rev=${revision}` : baseUrl;
};

export const getVersionCustomDisplayImageUrl = (category, folder) => {
  if (!category || !folder) return 'assets/images/version_placeholder.png';
  const baseUrl = `/clients/${category}/${folder}/custom_display.png`;
  const revision = Number(state.settingsState.texture_revision || 0);
  return revision > 0 ? `${baseUrl}?rev=${revision}` : baseUrl;
};

export const detachVersionImageFallbackHandler = (img) => {
  if (!img) return;
  if (typeof img._versionImageErrorHandler === 'function') {
    img.removeEventListener('error', img._versionImageErrorHandler);
  }
  img._versionImageErrorHandler = null;
};

export const applyVersionImageWithFallback = (
  img,
  {
    imageUrl = '',
    category = '',
    folder = '',
    placeholder = 'assets/images/version_placeholder.png',
  } = {}
) => {
  if (!img) return;

  const placeholderSrc = String(placeholder || 'assets/images/version_placeholder.png');
  detachVersionImageFallbackHandler(img);

  const explicitImageUrl = String(imageUrl || '').trim();
  if (explicitImageUrl) {
    const externalErrorHandler = () => {
      detachVersionImageFallbackHandler(img);
      if (img.src !== placeholderSrc) {
        img.src = placeholderSrc;
      }
    };
    img._versionImageErrorHandler = externalErrorHandler;
    img.addEventListener('error', externalErrorHandler);
    img.src = explicitImageUrl;
    return;
  }

  const customSrc = getVersionCustomDisplayImageUrl(category, folder);
  const defaultSrc = getVersionDisplayImageUrl(category, folder);
  if (!customSrc || !defaultSrc) {
    img.src = placeholderSrc;
    return;
  }

  let stage = 0;
  const localFallbackHandler = () => {
    if (stage === 0) {
      stage = 1;
      img.src = defaultSrc;
      return;
    }
    detachVersionImageFallbackHandler(img);
    if (img.src !== placeholderSrc) {
      img.src = placeholderSrc;
    }
  };

  img._versionImageErrorHandler = localFallbackHandler;
  img.addEventListener('error', localFallbackHandler);
  img.src = customSrc;
};
