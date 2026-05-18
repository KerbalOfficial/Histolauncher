// ui/modules/dom-utils.js

import { state } from './state.js';

export const $ = (selector) => document.querySelector(selector);
export const $$ = (selector) => Array.from(document.querySelectorAll(selector));

export const getEl = (id) => document.getElementById(id);

export const setText = (id, text) => {
  const el = getEl(id);
  if (el) el.textContent = text;
};

export const setHTML = (id, html) => {
  const el = getEl(id);
  if (el) el.innerHTML = html;
};

export const toggleClass = (el, className, on) => {
  if (!el) return;
  el.classList[on ? 'add' : 'remove'](className);
};

export const bindKeyboardActivation = (
  el,
  {
    ariaLabel = '',
    role = 'button',
    tabIndex = 0,
  } = {}
) => {
  if (!el) return;

  if (role && !el.hasAttribute('role')) el.setAttribute('role', role);
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', String(tabIndex));
  if (ariaLabel && !el.hasAttribute('aria-label')) el.setAttribute('aria-label', ariaLabel);

  if (el.dataset && el.dataset.keyboardActivationBound === '1') {
    return;
  }
  if (el.dataset) el.dataset.keyboardActivationBound = '1';

  let spaceArmed = false;

  el.addEventListener('keydown', (event) => {
    if (event.target !== el) return;

    if (event.key === 'Enter') {
      if (event.repeat) return;
      event.preventDefault();
      event.stopPropagation();
      el.click();
      return;
    }

    if (event.key === ' ' || event.key === 'Spacebar') {
      event.preventDefault();
      event.stopPropagation();
      spaceArmed = true;
    }
  });

  el.addEventListener('keyup', (event) => {
    if (event.target !== el) return;
    if (!spaceArmed) return;
    if (event.key === ' ' || event.key === 'Spacebar') {
      spaceArmed = false;
      event.preventDefault();
      event.stopPropagation();
      el.click();
    }
  });

  el.addEventListener('blur', () => {
    spaceArmed = false;
  });
};

let sharedImageLightboxRestoreFocusEl = null;

const SHARED_IMAGE_LIGHTBOX_ZOOM_SCALE = 2.5;
const SHARED_IMAGE_LIGHTBOX_CURSOR_STEP = 24;

const clampNumber = (value, min, max) => Math.min(max, Math.max(min, value));

const getSharedImageLightboxElements = (lightbox) => {
  if (!lightbox) return { image: null, cursor: null };

  const image = lightbox.querySelector('.screenshot-lightbox-img');
  const cursor = lightbox.querySelector('.screenshot-lightbox-cursor');
  return {
    image: image instanceof HTMLImageElement ? image : null,
    cursor: cursor instanceof HTMLElement ? cursor : null,
  };
};

const getSharedImageLightboxCursorPosition = (lightbox) => {
  const rect = lightbox && typeof lightbox.getBoundingClientRect === 'function'
    ? lightbox.getBoundingClientRect()
    : null;
  if (!rect || rect.width <= 0 || rect.height <= 0) {
    return {
      normX: 0.5,
      normY: 0.5,
      clientX: 0,
      clientY: 0,
      rect,
    };
  }

  const storedNormX = Number(lightbox.dataset.cursorNormX);
  const storedNormY = Number(lightbox.dataset.cursorNormY);
  const normX = Number.isFinite(storedNormX) ? clampNumber(storedNormX, 0, 1) : 0.5;
  const normY = Number.isFinite(storedNormY) ? clampNumber(storedNormY, 0, 1) : 0.5;
  return {
    normX,
    normY,
    clientX: rect.left + (rect.width * normX),
    clientY: rect.top + (rect.height * normY),
    rect,
  };
};

const renderSharedImageLightboxCursor = (lightbox) => {
  const { cursor } = getSharedImageLightboxElements(lightbox);
  const { normX, normY, rect } = getSharedImageLightboxCursorPosition(lightbox);
  if (!cursor || !rect || rect.width <= 0 || rect.height <= 0) return;

  cursor.style.left = `${normX * rect.width}px`;
  cursor.style.top = `${normY * rect.height}px`;
};

const setSharedImageLightboxKeyboardCursorVisible = (lightbox, visible) => {
  if (!lightbox) return;
  if (visible) {
    lightbox.dataset.keyboardCursor = '1';
    return;
  }
  delete lightbox.dataset.keyboardCursor;
};

const setSharedImageLightboxCursor = (lightbox, clientX, clientY) => {
  if (!lightbox) return;
  const rect = lightbox.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return;

  const normX = clampNumber((clientX - rect.left) / rect.width, 0, 1);
  const normY = clampNumber((clientY - rect.top) / rect.height, 0, 1);
  lightbox.dataset.cursorNormX = String(normX);
  lightbox.dataset.cursorNormY = String(normY);
  renderSharedImageLightboxCursor(lightbox);
};

const centerSharedImageLightboxCursor = (lightbox) => {
  if (!lightbox) return;
  const { image } = getSharedImageLightboxElements(lightbox);
  const imageRect = image ? image.getBoundingClientRect() : null;
  if (imageRect && imageRect.width > 0 && imageRect.height > 0) {
    setSharedImageLightboxCursor(
      lightbox,
      imageRect.left + (imageRect.width / 2),
      imageRect.top + (imageRect.height / 2),
    );
    return;
  }

  const lightboxRect = lightbox.getBoundingClientRect();
  setSharedImageLightboxCursor(
    lightbox,
    lightboxRect.left + (lightboxRect.width / 2),
    lightboxRect.top + (lightboxRect.height / 2),
  );
};

const getSharedImagePointInfo = (lightbox, clientX, clientY) => {
  const { image } = getSharedImageLightboxElements(lightbox);
  if (!image) return null;

  const rect = image.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) {
    return null;
  }

  return {
    originX: clampNumber(((clientX - rect.left) / rect.width) * 100, 0, 100),
    originY: clampNumber(((clientY - rect.top) / rect.height) * 100, 0, 100),
  };
};

const setSharedImageLightboxZoom = (lightbox, { zoomed = false, originX = 50, originY = 50 } = {}) => {
  const { image } = getSharedImageLightboxElements(lightbox);
  if (!lightbox || !image) return;

  if (!zoomed) {
    delete lightbox.dataset.zoomed;
    image.style.transform = '';
    image.style.transformOrigin = '50% 50%';
    return;
  }

  lightbox.dataset.zoomed = '1';
  image.style.transformOrigin = `${originX}% ${originY}%`;
  image.style.transform = `scale(${SHARED_IMAGE_LIGHTBOX_ZOOM_SCALE})`;
};

const activateSharedImageLightboxAtPoint = (lightbox, clientX, clientY) => {
  if (!lightbox) return;
  setSharedImageLightboxCursor(lightbox, clientX, clientY);

  if (lightbox.dataset.zoomed === '1') {
    setSharedImageLightboxZoom(lightbox, { zoomed: false });
    return;
  }

  const pointInfo = getSharedImagePointInfo(lightbox, clientX, clientY);
  if (!pointInfo) {
    closeSharedImageLightbox();
    return;
  }

  setSharedImageLightboxZoom(lightbox, {
    zoomed: true,
    originX: pointInfo.originX,
    originY: pointInfo.originY,
  });
};

const activateSharedImageLightboxAtCursor = (lightbox) => {
  const { clientX, clientY } = getSharedImageLightboxCursorPosition(lightbox);
  activateSharedImageLightboxAtPoint(lightbox, clientX, clientY);
};

export const closeSharedImageLightbox = ({ restoreFocus = true } = {}) => {
  const lightbox = getEl('screenshot-lightbox');
  if (!lightbox) return;

  lightbox.classList.remove('active');
  setSharedImageLightboxKeyboardCursorVisible(lightbox, false);
  setSharedImageLightboxZoom(lightbox, { zoomed: false });
  renderSharedImageLightboxCursor(lightbox);

  const restoreTarget = sharedImageLightboxRestoreFocusEl;
  sharedImageLightboxRestoreFocusEl = null;
  if (!restoreFocus) return;
  if (restoreTarget instanceof HTMLElement && restoreTarget.isConnected) {
    try {
      restoreTarget.focus();
    } catch (_) {
      // Ignore focus restoration failures.
    }
  }
};

export const ensureSharedImageLightbox = ({ ariaLabel = '' } = {}) => {
  let lightbox = getEl('screenshot-lightbox');
  if (!lightbox) {
    lightbox = document.createElement('div');
    lightbox.id = 'screenshot-lightbox';
    lightbox.className = 'screenshot-lightbox';

    const image = document.createElement('img');
    image.className = 'screenshot-lightbox-img';
    lightbox.appendChild(image);

    const cursor = document.createElement('div');
    cursor.className = 'screenshot-lightbox-cursor';
    cursor.setAttribute('aria-hidden', 'true');
    lightbox.appendChild(cursor);

    document.body.appendChild(lightbox);
  }

  if (!lightbox.hasAttribute('role')) lightbox.setAttribute('role', 'dialog');
  if (!lightbox.hasAttribute('tabindex')) lightbox.setAttribute('tabindex', '0');
  lightbox.setAttribute('aria-modal', 'true');
  if (ariaLabel) lightbox.setAttribute('aria-label', ariaLabel);

  if (lightbox.dataset && lightbox.dataset.sharedImageLightboxBound !== '1') {
    lightbox.dataset.sharedImageLightboxBound = '1';
    lightbox.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        closeSharedImageLightbox();
        return;
      }

      if (document.documentElement.dataset.keyboardMouseEnabled === '1') return;

      if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
        if (event.repeat) return;
        event.preventDefault();
        event.stopPropagation();
        setSharedImageLightboxKeyboardCursorVisible(lightbox, true);
        activateSharedImageLightboxAtCursor(lightbox);
        return;
      }

      if (!event.key.startsWith('Arrow')) return;
      event.preventDefault();
      event.stopPropagation();
      setSharedImageLightboxKeyboardCursorVisible(lightbox, true);

      const step = event.shiftKey
        ? Math.max(8, Math.round(SHARED_IMAGE_LIGHTBOX_CURSOR_STEP * 0.5))
        : SHARED_IMAGE_LIGHTBOX_CURSOR_STEP;
      const { clientX, clientY } = getSharedImageLightboxCursorPosition(lightbox);
      if (event.key === 'ArrowLeft') setSharedImageLightboxCursor(lightbox, clientX - step, clientY);
      else if (event.key === 'ArrowRight') setSharedImageLightboxCursor(lightbox, clientX + step, clientY);
      else if (event.key === 'ArrowUp') setSharedImageLightboxCursor(lightbox, clientX, clientY - step);
      else if (event.key === 'ArrowDown') setSharedImageLightboxCursor(lightbox, clientX, clientY + step);
    });
    lightbox.addEventListener('click', (event) => {
      setSharedImageLightboxKeyboardCursorVisible(lightbox, false);
      activateSharedImageLightboxAtPoint(lightbox, event.clientX, event.clientY);
    });
    window.addEventListener('resize', () => {
      if (!lightbox.classList.contains('active')) return;
      renderSharedImageLightboxCursor(lightbox);
    });
  }

  return lightbox;
};

export const openSharedImageLightbox = ({
  src = '',
  alt = '',
  restoreFocusEl = null,
  closeAriaLabel = '',
  showKeyboardCursor = false,
} = {}) => {
  const imageSrc = String(src || '').trim();
  if (!imageSrc) return null;

  const lightbox = ensureSharedImageLightbox({ ariaLabel: closeAriaLabel });
  const image = lightbox.querySelector('.screenshot-lightbox-img');
  if (!(image instanceof HTMLImageElement)) return null;

  sharedImageLightboxRestoreFocusEl = restoreFocusEl instanceof HTMLElement
    ? restoreFocusEl
    : (document.activeElement instanceof HTMLElement ? document.activeElement : null);

  image.src = imageSrc;
  image.alt = String(alt || '');
  setSharedImageLightboxKeyboardCursorVisible(lightbox, !!showKeyboardCursor);
  setSharedImageLightboxZoom(lightbox, { zoomed: false });
  lightbox.classList.add('active');

  const syncCursorToImage = () => {
    requestAnimationFrame(() => {
      centerSharedImageLightboxCursor(lightbox);
    });
  };

  if (image.complete && image.naturalWidth > 0) {
    syncCursorToImage();
  } else {
    image.addEventListener('load', syncCursorToImage, { once: true });
    image.addEventListener('error', syncCursorToImage, { once: true });
  }

  try {
    lightbox.focus();
  } catch (_) {
    // Ignore focus failures.
  }

  return lightbox;
};

export const isEditableTarget = (target) => {
  if (!(target instanceof Element)) return false;
  const el = target;
  if (el.closest('[contenteditable="true"]')) return true;
  const tag = String(el.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  return !!el.closest('input, textarea, select');
};

export const focusMainContentForPage = (pageKey) => {
  const pageEl = getEl(`page-${pageKey}`);
  if (!pageEl) return;

  const focusTarget =
    pageEl.querySelector('.section-title, h1, h2, h3, [role="heading"]') ||
    pageEl;

  if (focusTarget instanceof HTMLElement) {
    if (!focusTarget.hasAttribute('tabindex')) focusTarget.setAttribute('tabindex', '-1');
    try {
      focusTarget.focus({ preventScroll: true });
    } catch (e) {
      try {
        focusTarget.focus();
      } catch (err) {
        // Ignore
      }
    }
  }
};

export const getCardActionControls = (card) => {
  if (!card) return [];

  const selector = [
    '.icon-button',
    '.version-actions button',
    '.quick-install-wrap button',
    '.skin-editor-card-actions button',
  ].join(',');

  const controls = Array.from(card.querySelectorAll(selector));
  return controls.filter((el) => {
    if (!(el instanceof HTMLElement)) return false;
    if (el.hasAttribute('disabled')) return false;
    if (el.getAttribute('aria-disabled') === 'true') return false;

    try {
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    } catch (e) { }
    return true;
  });
};

export const wireCardActionArrowNavigation = (card) => {
  if (!card || !(card instanceof HTMLElement)) return;
  if (card.dataset && card.dataset.cardArrowNavBound === '1') return;
  if (card.dataset) card.dataset.cardArrowNavBound = '1';

  const ensureCardTabStop = () => {
    if (!card.hasAttribute('tabindex')) card.setAttribute('tabindex', '0');
  };

  const getControls = () => {
    const list = getCardActionControls(card);
    list.forEach((el) => {
      if (!el.hasAttribute('tabindex') || el.getAttribute('tabindex') !== '-1') {
        el.setAttribute('tabindex', '-1');
      }
    });
    return list;
  };

  const moveFocusFromCard = (direction) => {
    const controls = getControls();
    if (controls.length === 0) return;

    const shouldGoLast = direction === 'prev';
    const next = shouldGoLast ? controls[controls.length - 1] : controls[0];
    try {
      next.focus();
    } catch (e) {
      // Ignore
    }
  };

  const moveFocusBetweenControls = (current, direction) => {
    const controls = getControls();
    if (controls.length === 0) return;
    const index = controls.indexOf(current);
    if (index === -1) return;

    const delta = direction === 'prev' ? -1 : 1;
    let nextIndex = index + delta;
    if (nextIndex < 0) nextIndex = controls.length - 1;
    if (nextIndex >= controls.length) nextIndex = 0;

    const next = controls[nextIndex];
    try {
      next.focus();
    } catch (e) {
      // Ignore
    }
  };

  ensureCardTabStop();

  card.addEventListener('keydown', (event) => {
    if (event.target !== card) return;

    const key = event.key;
    if (
      key === 'ArrowRight' ||
      key === 'ArrowDown' ||
      key === 'ArrowLeft' ||
      key === 'ArrowUp'
    ) {
      event.preventDefault();
      event.stopPropagation();
      moveFocusFromCard(key === 'ArrowLeft' || key === 'ArrowUp' ? 'prev' : 'next');
    }
  });

  const bindControls = () => {
    const controls = getControls();
    controls.forEach((control) => {
      if (control.dataset && control.dataset.cardControlArrowNavBound === '1') return;
      if (control.dataset) control.dataset.cardControlArrowNavBound = '1';

      control.addEventListener('keydown', (event) => {
        if (event.target !== control) return;
        const key = event.key;
        if (
          key === 'ArrowRight' ||
          key === 'ArrowDown' ||
          key === 'ArrowLeft' ||
          key === 'ArrowUp'
        ) {
          event.preventDefault();
          event.stopPropagation();
          moveFocusBetweenControls(
            control,
            key === 'ArrowLeft' || key === 'ArrowUp' ? 'prev' : 'next'
          );
        }
      });
    });
  };

  bindControls();

  card.addEventListener('focus', () => {
    bindControls();
  });
};

export const imageAttachErrorPlaceholder = (img, placeholderLink) => {
  img.addEventListener('error', () => {
    if (!img.src.endsWith(placeholderLink)) {
      img.src = placeholderLink;
    }
  });
};

export const isShiftDelete = (event) => {
  return !!((event && event.shiftKey) || state.isShiftDown);
};
