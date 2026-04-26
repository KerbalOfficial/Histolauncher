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
  ].join(',');

  const controls = Array.from(card.querySelectorAll(selector));
  return controls.filter((el) => {
    if (!(el instanceof HTMLElement)) return false;
    if (el.hasAttribute('disabled')) return false;
    if (el.getAttribute('aria-disabled') === 'true') return false;

    try {
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    } catch (e) {
      // If styles can't be computed yet (e.g., detached), keep the element.
    }
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
    // Keep action controls out of the tab order; they are accessed via arrow keys.
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
