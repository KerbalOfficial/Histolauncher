// ui/modules/modal.js

import { getEl, toggleClass } from './dom-utils.js';

const DEFAULT_LOADING_TEXT = 'Loading...';
const DEFAULT_ACTIVITY_IMAGE = 'assets/images/settings.gif';

let activeMessageBoxMode = null;
let activeMessageBoxState = null;
let activeActivityOverlay = null;
let messageBoxRestoreFocusEl = null;

// ---------------- Loading / activity overlay ----------------

const renderActivityOverlay = () => {
  if (!activeActivityOverlay) return;
  showMessageBox({
    ...activeActivityOverlay,
    _internalMode: 'activity',
  });
};

const updateLoadingOverlay = (patch = {}) => {
  if (!activeActivityOverlay) return;
  activeActivityOverlay = {
    ...activeActivityOverlay,
    ...patch,
  };
  renderActivityOverlay();
};

export const setLoadingOverlayText = (message = DEFAULT_LOADING_TEXT) => {
  if (!activeActivityOverlay) return;
  updateLoadingOverlay({ message: message || DEFAULT_LOADING_TEXT });
};

export const showLoadingOverlay = (message = DEFAULT_LOADING_TEXT, options = {}) => {
  const {
    title = '',
    image = DEFAULT_ACTIVITY_IMAGE,
    buttons = [],
    description = '',
    boxClassList = ['activity-box'],
  } = options || {};

  activeActivityOverlay = {
    title,
    message: message || DEFAULT_LOADING_TEXT,
    image,
    buttons,
    description,
    boxClassList,
  };
  renderActivityOverlay();
};

export const hideLoadingOverlay = () => {
  activeActivityOverlay = null;
  if (activeMessageBoxMode === 'activity') {
    hideMessageBox();
  }
};

// ---------------- Message box ----------------

export const sanitizeMessageBoxHtml = (html) => {
  const template = document.createElement('template');
  template.innerHTML = String(html || '');

  template.content
    .querySelectorAll('script, iframe, object, embed, link, meta, base')
    .forEach((el) => el.remove());

  template.content.querySelectorAll('*').forEach((el) => {
    Array.from(el.attributes).forEach((attr) => {
      const name = String(attr.name || '').toLowerCase();
      const value = String(attr.value || '');

      if (name.startsWith('on')) {
        el.removeAttribute(attr.name);
        return;
      }

      if (
        (name === 'href' || name === 'src' || name === 'xlink:href' || name === 'formaction') &&
        /^\s*javascript:/i.test(value)
      ) {
        el.removeAttribute(attr.name);
      }
    });
  });

  return template.innerHTML;
};

export const getMessageBoxFocusableElements = (root) => {
  if (!root) return [];

  const selector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
    '[contenteditable="true"]',
  ].join(',');

  return Array.from(root.querySelectorAll(selector)).filter((el) => {
    if (!(el instanceof HTMLElement)) return false;
    if (el.hasAttribute('disabled')) return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;

    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    return el.getClientRects().length > 0;
  });
};

const focusFirstInMessageBox = (box) => {
  if (!box) return;

  const focusable = getMessageBoxFocusableElements(box);
  if (focusable.length > 0) {
    focusable[0].focus();
    return;
  }

  if (!box.hasAttribute('tabindex')) box.setAttribute('tabindex', '-1');
  box.focus();
};

export const hideMessageBox = () => {
  const overlay = getEl('msgbox-overlay');
  if (overlay) overlay.classList.add('hidden');

  const restoreTarget = messageBoxRestoreFocusEl;
  messageBoxRestoreFocusEl = null;

  if (activeMessageBoxMode === 'activity') {
    activeActivityOverlay = null;
  }
  activeMessageBoxMode = null;
  activeMessageBoxState = null;

  if (restoreTarget && typeof restoreTarget.focus === 'function' && restoreTarget.isConnected) {
    try {
      restoreTarget.focus();
    } catch (e) {
      // Ignore
    }
  }
};

const ensureMessageBoxKeyboardA11y = () => {
  const overlay = getEl('msgbox-overlay');
  const box = getEl('msgbox-box');
  if (!overlay || !box) return;

  if (overlay.dataset && overlay.dataset.messageBoxA11yBound === '1') return;
  if (overlay.dataset) overlay.dataset.messageBoxA11yBound = '1';

  overlay.addEventListener('keydown', (event) => {
    if (overlay.classList.contains('hidden')) return;

    if (event.key === 'Escape') {
      if (activeMessageBoxMode !== 'activity') {
        event.preventDefault();
        event.stopPropagation();
        hideMessageBox();
      }
      return;
    }

    if (event.key !== 'Tab') return;

    const focusable = getMessageBoxFocusableElements(box);
    if (focusable.length === 0) {
      event.preventDefault();
      if (!box.hasAttribute('tabindex')) box.setAttribute('tabindex', '-1');
      box.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (event.shiftKey) {
      if (active === first || !box.contains(active)) {
        event.preventDefault();
        last.focus();
      }
    } else {
      if (active === last || !box.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }
  });
};

export const showMessageBox = ({
  title = '',
  message = '',
  buttons = [],
  inputs = [],
  customContent = null,
  description = '',
  image = '',
  boxClassList = [],
  _internalMode = 'dialog',
}) => {
  const overlay = getEl('msgbox-overlay');
  const box = getEl('msgbox-box');
  const boxImage = getEl('msgbox-image');
  const boxTitle = getEl('msgbox-title');
  const boxText = getEl('msgbox-text');
  const btnContainer = getEl('msgbox-buttons');

  if (!overlay || !box || !boxTitle || !btnContainer) return null;

  ensureMessageBoxKeyboardA11y();

  const wasHidden = overlay.classList.contains('hidden');
  if (wasHidden) {
    const activeEl = document.activeElement;
    messageBoxRestoreFocusEl = activeEl instanceof HTMLElement ? activeEl : null;
  }

  activeMessageBoxMode = _internalMode || 'dialog';
  activeMessageBoxState = {
    title,
    message,
    buttons,
    inputs,
    customContent,
    description,
    image,
    boxClassList,
    _internalMode: activeMessageBoxMode,
  };
  if (activeMessageBoxMode !== 'activity') {
    activeActivityOverlay = null;
  }

  box.className = ['loading-box', ...(Array.isArray(boxClassList) ? boxClassList : [])].join(' ').trim();

  if (boxImage) {
    if (image) {
      boxImage.src = image;
      boxImage.alt = title || 'Activity';
      boxImage.classList.remove('hidden');
    } else {
      boxImage.removeAttribute('src');
      boxImage.alt = '';
      boxImage.classList.add('hidden');
    }
  }

  boxTitle.textContent = title;
  toggleClass(boxTitle, 'hidden', !title);

  // Handle custom content or regular message
  boxText.innerHTML = '';

  if (customContent && customContent instanceof Node) {
    // If custom content is provided, use it instead of message text
    boxText.appendChild(customContent);
  } else if (typeof message === 'string' && message) {
    boxText.innerHTML = sanitizeMessageBoxHtml(message);
  }

  // Add description if provided
  if (description) {
    const descEl = document.createElement('div');
    descEl.style.cssText = `
        font-size: 12px;
        color: #888;
        margin-top: 8px;
        padding-top: 8px;
        border-top: 1px solid #ddd;
      `;
    descEl.textContent = description;
    boxText.appendChild(descEl);
  }
  toggleClass(boxText, 'hidden', !boxText.childNodes.length && !boxText.textContent.trim());

  const inputsContainerId = 'msgbox-inputs';
  let inputsContainer = getEl(inputsContainerId);
  if (inputsContainer) inputsContainer.remove();

  if (Array.isArray(inputs) && inputs.length > 0) {
    inputsContainer = document.createElement('div');
    inputsContainer.id = inputsContainerId;
    inputsContainer.style.marginTop = '8px';

    inputs.forEach((inp) => {
      const wrap = document.createElement('div');
      wrap.style.marginBottom = '8px';

      const el = document.createElement('input');
      el.type = inp.type || 'text';
      el.name = inp.name || '';
      el.placeholder = inp.placeholder || '';
      if (inp.value) el.value = inp.value;
      el.style.width = '100%';
      el.style.boxSizing = 'border-box';
      el.style.padding = '8px';

      wrap.appendChild(el);
      inputsContainer.appendChild(wrap);
    });

    boxText.parentNode.insertBefore(inputsContainer, boxText.nextSibling);
  }


  btnContainer.innerHTML = '';
  toggleClass(btnContainer, 'hidden', !buttons.length);

  const controls = {
    close: hideMessageBox,
    update: (patch = {}) => {
      const nextState = {
        ...(activeMessageBoxState || {}),
        ...patch,
        _internalMode: activeMessageBoxMode || _internalMode || 'dialog',
      };
      if ((nextState._internalMode || 'dialog') === 'activity') {
        activeActivityOverlay = {
          title: nextState.title || '',
          message: nextState.message || DEFAULT_LOADING_TEXT,
          image: nextState.image || DEFAULT_ACTIVITY_IMAGE,
          buttons: Array.isArray(nextState.buttons) ? nextState.buttons : [],
          description: nextState.description || '',
          boxClassList: Array.isArray(nextState.boxClassList) && nextState.boxClassList.length
            ? nextState.boxClassList
            : ['activity-box'],
        };
      }
      return showMessageBox(nextState);
    },
  };

  buttons.forEach((btn) => {
    const el = document.createElement('button');
    el.textContent = btn.label;
    if (btn.classList) el.classList.add(...btn.classList);
    if (btn.disabled) el.disabled = true;

    el.addEventListener('click', () => {
      const values = {};
      if (Array.isArray(inputs) && inputs.length > 0) {
        const container = getEl('msgbox-inputs');
        if (container) {
          Array.from(container.querySelectorAll('input')).forEach((i) => {
            values[i.name || i.placeholder || '__'] = i.value;
          });
        }
      }

      if (btn.closeOnClick !== false) {
        hideMessageBox();
      }
      if (btn.onClick) btn.onClick(values, controls);
    });

    btnContainer.appendChild(el);
  });

  overlay.classList.remove('hidden');

  if (wasHidden) {
    setTimeout(() => {
      if (overlay.classList.contains('hidden')) return;
      const activeEl = document.activeElement;
      if (activeEl && box.contains(activeEl)) return;
      focusFirstInMessageBox(box);
    }, 0);
  }

  return controls;
};
