// ui/modules/string-utils.js

export const normalizeFavoriteVersions = (favRaw) => {
  if (Array.isArray(favRaw)) {
    return favRaw
      .map((s) => (typeof s === 'string' ? s.trim() : ''))
      .filter((s) => s.length > 0);
  }
  if (typeof favRaw === 'string') {
    return favRaw
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }
  return [];
};

export const escapeInfoHtml = (txt) => String(txt == null ? '' : txt)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

export const makeInfoRowHTML = (iconSrc, label, value, parens) => {
  const icon = `<img width="16px" height="16px" src="${iconSrc}"/>`;
  const lbl = `<span class="tooltip-label">${escapeInfoHtml(label)}:</span>`;
  const val = `<span class="tooltip-value">${escapeInfoHtml(value)}</span>`;
  const par = parens ? ` <span class="tooltip-parens">(${escapeInfoHtml(parens)})</span>` : '';
  return `${icon} ${lbl} ${val}${par}`;
};

export const makeInfoRowErrorHTML = (label, value, parens, titleAttr) => {
  const par = parens ? ` <span class="tooltip-parens">(${escapeInfoHtml(parens)})</span>` : '';
  return `<span class="home-info-error" title="${escapeInfoHtml(titleAttr)}">&#9888; <span class="tooltip-label">${escapeInfoHtml(label)}:</span> <span class="tooltip-value">${escapeInfoHtml(value)}</span>${par}</span>`;
};

export const sanitizeGlobalMessageHtml = (input) => {
  const template = document.createElement('template');
  template.innerHTML = String(input || '');
  template.content.querySelectorAll('script').forEach((el) => el.remove());
  return template.innerHTML;
};

export const formatBytes = (bytes) => {
  if (!bytes || bytes <= 0) return null;

  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }

  if (unitIndex === 0) {
    return `${size} ${units[unitIndex]}`;
  } else if (unitIndex === 1) {
    return `${size.toFixed(0)} ${units[unitIndex]}`;
  } else {
    return `${size.toFixed(2)} ${units[unitIndex]}`;
  }
};
