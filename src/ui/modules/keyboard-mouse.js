import { isEditableTarget } from './dom-utils.js';
import { state } from './state.js';

const TRIGGER_KEYS = new Set(['Enter', 'NumpadEnter', ' ', 'Spacebar']);
const ARROW_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']);
const KEYBOARD_MOUSE_SELECTION_SELECTOR = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[role="button"]',
  '[role="link"]',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');
const FAST_CURSOR_SPEED = 500;
const SLOW_CURSOR_SPEED = FAST_CURSOR_SPEED / 5;
const SCROLL_SPEED = 1200;
const SLOW_SCROLL_SPEED = SCROLL_SPEED / 5;
const POINTER_EVENT_BY_MOUSE_TYPE = {
  mousedown: 'pointerdown',
  mousemove: 'pointermove',
  mouseup: 'pointerup',
  mouseover: 'pointerover',
  mouseout: 'pointerout',
  mouseenter: 'pointerenter',
  mouseleave: 'pointerleave',
};

const keyboardMouseState = {
  enabled: false,
  active: false,
  bound: false,
  cursorEl: null,
  rafId: 0,
  lastFrameAt: 0,
  activeKeys: new Set(),
  x: Number.NaN,
  y: Number.NaN,
  lastPhysicalX: Number.NaN,
  lastPhysicalY: Number.NaN,
  hoverEl: null,
  selectionEl: null,
  pressedTarget: null,
  pressedButton: null,
  triggerKey: '',
  dragMoved: false,
};

const isTruthy = (value) => String(value || '').trim().toLowerCase() in {
  1: true,
  true: true,
  yes: true,
  on: true,
};

const getMouseButtonMask = (button) => {
  if (button === 1) return 4;
  if (button === 2) return 2;
  return 1;
};

const isKeyboardMouseActive = () => keyboardMouseState.enabled && keyboardMouseState.active;

const getKeyboardMouseModifierFlag = (modifier) => keyboardMouseState.activeKeys.has(modifier);

const isKeyboardMouseDomEnabled = () => document.documentElement.dataset.keyboardMouseEnabled === '1';

const setKeyboardMouseDomEnabled = (enabled) => {
  document.documentElement.dataset.keyboardMouseEnabled = enabled ? '1' : '0';
  if (document.body) {
    document.body.classList.toggle('keyboard-mouse-enabled', !!enabled);
  }
};

const ensureKeyboardMouseCursor = () => {
  if (keyboardMouseState.cursorEl instanceof HTMLElement) {
    return keyboardMouseState.cursorEl;
  }

  const cursor = document.createElement('div');
  cursor.id = 'keyboard-mouse-cursor';
  cursor.className = 'keyboard-mouse-cursor';
  cursor.setAttribute('aria-hidden', 'true');
  document.body.appendChild(cursor);
  keyboardMouseState.cursorEl = cursor;
  return cursor;
};

const clampCursorPosition = (x, y) => {
  const width = Math.max(window.innerWidth || 0, 1);
  const height = Math.max(window.innerHeight || 0, 1);
  return {
    x: Math.min(width - 1, Math.max(0, Number(x) || 0)),
    y: Math.min(height - 1, Math.max(0, Number(y) || 0)),
  };
};

const recordPhysicalPointerPosition = (clientX, clientY) => {
  const next = clampCursorPosition(clientX, clientY);
  keyboardMouseState.lastPhysicalX = next.x;
  keyboardMouseState.lastPhysicalY = next.y;
  keyboardMouseState.x = next.x;
  keyboardMouseState.y = next.y;
};

const blurElementIfFocused = (target) => {
  if (!(target instanceof HTMLElement)) return;
  if (document.activeElement !== target) return;
  try {
    target.blur();
  } catch (_) {
    // Ignore blur failures.
  }
};

const syncModifierKeysFromEvent = (event) => {
  if (!event) return;
  if (event.ctrlKey) keyboardMouseState.activeKeys.add('Control');
  else keyboardMouseState.activeKeys.delete('Control');

  if (event.shiftKey) keyboardMouseState.activeKeys.add('Shift');
  else keyboardMouseState.activeKeys.delete('Shift');
};

const getKeyboardMouseSelectionTarget = (element) => {
  if (!(element instanceof Element)) return null;
  return element.closest(KEYBOARD_MOUSE_SELECTION_SELECTOR);
};

const blurKeyboardMouseStaleFocus = (nextSelection) => {
  const activeElement = document.activeElement;
  if (!(activeElement instanceof HTMLElement)) return;
  if (activeElement === nextSelection) return;
  if (activeElement === document.body || activeElement === document.documentElement) return;

  if (
    activeElement === keyboardMouseState.selectionEl
    || activeElement.classList.contains('keyboard-mouse-target')
    || isEditableTarget(activeElement)
  ) {
    blurElementIfFocused(activeElement);
  }
};

const clearKeyboardMouseSelection = () => {
  if (keyboardMouseState.selectionEl instanceof HTMLElement) {
    keyboardMouseState.selectionEl.classList.remove('keyboard-mouse-target');
    blurElementIfFocused(keyboardMouseState.selectionEl);
  }
  keyboardMouseState.selectionEl = null;
};

const updateKeyboardMouseSelection = (element) => {
  const nextSelection = getKeyboardMouseSelectionTarget(element);
  const currentSelection = keyboardMouseState.selectionEl;
  blurKeyboardMouseStaleFocus(nextSelection);
  if (currentSelection === nextSelection) return;

  clearKeyboardMouseSelection();

  if (!(nextSelection instanceof HTMLElement)) return;

  keyboardMouseState.selectionEl = nextSelection;
  nextSelection.classList.add('keyboard-mouse-target');
  if (!isEditableTarget(nextSelection)) {
    tryFocusElement(nextSelection);
  }
};

const renderKeyboardMouseCursor = () => {
  const cursor = ensureKeyboardMouseCursor();
  const { x, y } = clampCursorPosition(keyboardMouseState.x, keyboardMouseState.y);
  keyboardMouseState.x = x;
  keyboardMouseState.y = y;
  cursor.style.left = `${x}px`;
  cursor.style.top = `${y}px`;
  cursor.classList.toggle('active', isKeyboardMouseActive());
};

const dispatchKeyboardMouseHoverEvent = (target, type, options = {}) => dispatchSyntheticMouseEvent(
  target,
  type,
  0,
  {
    buttons: options.buttons ?? 0,
    bubbles: options.bubbles,
    relatedTarget: options.relatedTarget ?? null,
  },
);

const clearKeyboardMouseHoverState = () => {
  const previousHover = keyboardMouseState.hoverEl;
  if (previousHover instanceof Element) {
    dispatchKeyboardMouseHoverEvent(previousHover, 'mouseout');
    dispatchKeyboardMouseHoverEvent(previousHover, 'mouseleave', { bubbles: false });
  }
  keyboardMouseState.hoverEl = null;
  clearKeyboardMouseSelection();
};

const syncKeyboardMouseHoverState = () => {
  if (!isKeyboardMouseActive()) {
    clearKeyboardMouseHoverState();
    return;
  }

  const previousHover = keyboardMouseState.hoverEl;
  const nextHover = getElementAtKeyboardMouse();

  if (previousHover !== nextHover) {
    if (previousHover instanceof Element) {
      dispatchKeyboardMouseHoverEvent(previousHover, 'mouseout', { relatedTarget: nextHover || null });
      dispatchKeyboardMouseHoverEvent(previousHover, 'mouseleave', {
        bubbles: false,
        relatedTarget: nextHover || null,
      });
    }

    if (nextHover instanceof Element) {
      dispatchKeyboardMouseHoverEvent(nextHover, 'mouseover', { relatedTarget: previousHover || null });
      dispatchKeyboardMouseHoverEvent(nextHover, 'mouseenter', {
        bubbles: false,
        relatedTarget: previousHover || null,
      });
    }
  }

  keyboardMouseState.hoverEl = nextHover instanceof Element ? nextHover : null;

  if (keyboardMouseState.hoverEl instanceof Element) {
    dispatchKeyboardMouseHoverEvent(keyboardMouseState.hoverEl, 'mousemove');
  }

  updateKeyboardMouseSelection(keyboardMouseState.hoverEl);
};

const activateKeyboardMouse = () => {
  if (!keyboardMouseState.enabled) return;
  keyboardMouseState.active = true;
  setKeyboardMouseDomEnabled(true);
  ensureKeyboardMousePosition();
  renderKeyboardMouseCursor();
  syncKeyboardMouseHoverState();
};

const deactivateKeyboardMouse = ({ clearKeys = true } = {}) => {
  releaseKeyboardMousePrimaryPress({ cancel: true });
  keyboardMouseState.active = false;
  setKeyboardMouseDomEnabled(false);
  clearKeyboardMouseHoverState();
  if (clearKeys) {
    clearKeyboardMouseKeys();
  }
  renderKeyboardMouseCursor();
};

const setKeyboardMousePosition = (x, y) => {
  const next = clampCursorPosition(x, y);
  keyboardMouseState.x = next.x;
  keyboardMouseState.y = next.y;
  renderKeyboardMouseCursor();
  if (isKeyboardMouseActive()) {
    syncKeyboardMouseHoverState();
  }
};

const ensureKeyboardMousePosition = () => {
  if (Number.isFinite(keyboardMouseState.x) && Number.isFinite(keyboardMouseState.y)) {
    return;
  }

  if (Number.isFinite(keyboardMouseState.lastPhysicalX) && Number.isFinite(keyboardMouseState.lastPhysicalY)) {
    setKeyboardMousePosition(keyboardMouseState.lastPhysicalX, keyboardMouseState.lastPhysicalY);
    return;
  }

  setKeyboardMousePosition(window.innerWidth / 2, window.innerHeight / 2);
};

const resetKeyboardMouseLoop = () => {
  if (keyboardMouseState.rafId) {
    cancelAnimationFrame(keyboardMouseState.rafId);
    keyboardMouseState.rafId = 0;
  }
  keyboardMouseState.lastFrameAt = 0;
};

function clearKeyboardMousePressState() {
  keyboardMouseState.pressedTarget = null;
  keyboardMouseState.pressedButton = null;
  keyboardMouseState.triggerKey = '';
  keyboardMouseState.dragMoved = false;
}

const clearKeyboardMouseKeys = () => {
  keyboardMouseState.activeKeys.clear();
  clearKeyboardMousePressState();
  resetKeyboardMouseLoop();
};

const normalizeVector = (x, y) => {
  const magnitude = Math.hypot(x, y);
  if (!magnitude) return { x: 0, y: 0 };
  return { x: x / magnitude, y: y / magnitude };
};

const getArrowVector = () => {
  let x = 0;
  let y = 0;
  if (keyboardMouseState.activeKeys.has('ArrowLeft')) x -= 1;
  if (keyboardMouseState.activeKeys.has('ArrowRight')) x += 1;
  if (keyboardMouseState.activeKeys.has('ArrowUp')) y -= 1;
  if (keyboardMouseState.activeKeys.has('ArrowDown')) y += 1;
  return normalizeVector(x, y);
};

const getElementAtKeyboardMouse = () => {
  ensureKeyboardMousePosition();
  return document.elementFromPoint(keyboardMouseState.x, keyboardMouseState.y);
};

const canScrollElement = (element, axis) => {
  if (!(element instanceof HTMLElement)) return false;
  const style = window.getComputedStyle(element);
  const overflow = axis === 'x' ? style.overflowX : style.overflowY;
  if (!/(auto|scroll|overlay)/i.test(overflow)) return false;
  if (axis === 'x') return element.scrollWidth > element.clientWidth + 1;
  return element.scrollHeight > element.clientHeight + 1;
};

const getScrollableTargetAtKeyboardMouse = (vector) => {
  const axis = Math.abs(vector.x) > Math.abs(vector.y) ? 'x' : 'y';
  let current = getElementAtKeyboardMouse();
  while (current) {
    if (canScrollElement(current, axis)) return current;
    current = current.parentElement;
  }

  return document.scrollingElement || document.documentElement;
};

function dispatchSyntheticPointerEvent(target, type, button, options = {}) {
  if (!(target instanceof EventTarget)) return true;
  if (typeof window === 'undefined' || typeof window.PointerEvent !== 'function') return true;

  const buttons = options.buttons ?? getMouseButtonMask(button);
  const event = new window.PointerEvent(type, {
    bubbles: options.bubbles ?? true,
    cancelable: true,
    composed: true,
    view: window,
    clientX: keyboardMouseState.x,
    clientY: keyboardMouseState.y,
    button,
    buttons,
    ctrlKey: options.ctrlKey ?? getKeyboardMouseModifierFlag('Control'),
    shiftKey: options.shiftKey ?? getKeyboardMouseModifierFlag('Shift'),
    altKey: !!options.altKey,
    metaKey: !!options.metaKey,
    relatedTarget: options.relatedTarget ?? null,
    pointerId: 1,
    pointerType: 'mouse',
    isPrimary: true,
    pressure: buttons ? 0.5 : 0,
  });
  return target.dispatchEvent(event);
}

const dispatchSyntheticMouseEvent = (target, type, button, options = {}) => {
  if (!(target instanceof EventTarget)) return true;
  const buttons = options.buttons ?? getMouseButtonMask(button);
  const pointerType = POINTER_EVENT_BY_MOUSE_TYPE[type];
  const pointerResult = pointerType
    ? dispatchSyntheticPointerEvent(target, pointerType, button, options)
    : true;
  const event = new MouseEvent(type, {
    bubbles: options.bubbles ?? true,
    cancelable: true,
    composed: true,
    view: window,
    clientX: keyboardMouseState.x,
    clientY: keyboardMouseState.y,
    button,
    buttons,
    ctrlKey: options.ctrlKey ?? getKeyboardMouseModifierFlag('Control'),
    shiftKey: options.shiftKey ?? getKeyboardMouseModifierFlag('Shift'),
    altKey: !!options.altKey,
    metaKey: !!options.metaKey,
    relatedTarget: options.relatedTarget ?? null,
  });
  const mouseResult = target.dispatchEvent(event);
  return pointerResult && mouseResult;
};

const tryFocusElement = (target) => {
  if (!(target instanceof HTMLElement)) return;
  try {
    target.focus({ preventScroll: true });
  } catch (_) {
    try {
      target.focus();
    } catch (__){
      // Ignore focus errors.
    }
  }
};

const commitKeyboardMouseLeftClick = (target) => {
  if (!(target instanceof Element)) return;

  if (
    target.closest('#screenshot-lightbox')
    || getKeyboardMouseModifierFlag('Shift')
    || !(target instanceof HTMLElement)
  ) {
    dispatchSyntheticMouseEvent(target, 'click', 0, { buttons: 0 });
    return;
  }

  target.click();
};

function beginKeyboardMousePrimaryPress(target, triggerKey) {
  if (!(target instanceof Element)) return false;

  keyboardMouseState.pressedTarget = target;
  keyboardMouseState.pressedButton = 0;
  keyboardMouseState.triggerKey = triggerKey;
  keyboardMouseState.dragMoved = false;

  tryFocusElement(target instanceof HTMLElement ? target : null);
  dispatchSyntheticMouseEvent(target, 'mousemove', 0, { buttons: 0 });
  dispatchSyntheticMouseEvent(target, 'mousedown', 0, { buttons: 1 });
  return true;
}

function dispatchKeyboardMouseDragMove() {
  if (keyboardMouseState.pressedButton !== 0) return;

  const target = getElementAtKeyboardMouse();
  if (!(target instanceof Element)) return;

  keyboardMouseState.dragMoved = true;
  dispatchSyntheticMouseEvent(target, 'mousemove', 0, { buttons: 1 });
}

function releaseKeyboardMousePrimaryPress({ cancel = false } = {}) {
  const pressedTarget = keyboardMouseState.pressedTarget;
  const pressedButton = keyboardMouseState.pressedButton;
  const didDrag = keyboardMouseState.dragMoved;

  if (pressedButton == null || !(pressedTarget instanceof Element)) {
    clearKeyboardMousePressState();
    return false;
  }

  const hoveredTarget = getElementAtKeyboardMouse();
  const releaseTarget = hoveredTarget instanceof Element ? hoveredTarget : pressedTarget;
  dispatchSyntheticMouseEvent(releaseTarget, 'mouseup', pressedButton, { buttons: 0 });

  clearKeyboardMousePressState();

  if (cancel || pressedButton !== 0 || didDrag) {
    return false;
  }

  commitKeyboardMouseLeftClick(pressedTarget);
  return true;
}

const performMiddleClickAtKeyboardMouse = (target) => {
  if (!(target instanceof Element)) return;
  tryFocusElement(target instanceof HTMLElement ? target : null);
  dispatchSyntheticMouseEvent(target, 'mousemove', 1, { buttons: 0 });
  dispatchSyntheticMouseEvent(target, 'mousedown', 1);
  dispatchSyntheticMouseEvent(target, 'mouseup', 1, { buttons: 0 });
  dispatchSyntheticMouseEvent(target, 'auxclick', 1, { buttons: 0 });
};

const suspendKeyboardMouseForSelect = (target) => {
  if (!(target instanceof HTMLSelectElement)) return false;

  let shouldResumeAfterClose = true;

  const cleanup = () => {
    target.removeEventListener('blur', handleBlur);
    target.removeEventListener('change', handleChange);
    target.removeEventListener('keydown', handleKeyDown, true);
  };

  const resumeKeyboardMouse = () => {
    cleanup();
    if (!shouldResumeAfterClose || !keyboardMouseState.enabled) return;

    requestAnimationFrame(() => {
      if (!keyboardMouseState.enabled) return;
      blurElementIfFocused(target);
      activateKeyboardMouse();
    });
  };

  const handleBlur = () => {
    resumeKeyboardMouse();
  };

  const handleChange = () => {
    resumeKeyboardMouse();
  };

  const handleKeyDown = (event) => {
    if (!event) return;
    if (event.key === 'Tab') {
      shouldResumeAfterClose = false;
      cleanup();
      return;
    }
    if (event.key === 'Enter' || event.key === 'Escape') {
      resumeKeyboardMouse();
    }
  };

  deactivateKeyboardMouse();
  target.addEventListener('blur', handleBlur, { once: true });
  target.addEventListener('change', handleChange, { once: true });
  target.addEventListener('keydown', handleKeyDown, true);
  tryFocusElement(target);
  target.click();
  return true;
};

const handleKeyboardMouseTriggerDown = (triggerKey) => {
  if (keyboardMouseState.triggerKey) return;

  activateKeyboardMouse();
  syncKeyboardMouseHoverState();
  const target = getElementAtKeyboardMouse();
  if (!(target instanceof Element)) return;

  if (suspendKeyboardMouseForSelect(target)) {
    return;
  }

  if (keyboardMouseState.activeKeys.has('Control')) {
    performMiddleClickAtKeyboardMouse(target);
    return;
  }

  beginKeyboardMousePrimaryPress(target, triggerKey);
};

const stepKeyboardMouse = (timestamp) => {
  if (!isKeyboardMouseActive()) {
    resetKeyboardMouseLoop();
    return;
  }

  if (!keyboardMouseState.lastFrameAt) {
    keyboardMouseState.lastFrameAt = timestamp;
  }

  const deltaSeconds = Math.min(0.05, Math.max(0, (timestamp - keyboardMouseState.lastFrameAt) / 1000));
  keyboardMouseState.lastFrameAt = timestamp;

  const vector = getArrowVector();
  const hasMovement = Math.abs(vector.x) > 0 || Math.abs(vector.y) > 0;
  if (hasMovement) {
    if (keyboardMouseState.activeKeys.has('Control')) {
      const scrollTarget = getScrollableTargetAtKeyboardMouse(vector);
      const scrollSpeed = keyboardMouseState.activeKeys.has('Shift') ? SLOW_SCROLL_SPEED : SCROLL_SPEED;
      const distance = scrollSpeed * deltaSeconds;
      if (typeof scrollTarget.scrollBy === 'function') {
        scrollTarget.scrollBy({
          left: vector.x * distance,
          top: vector.y * distance,
          behavior: 'auto',
        });
        syncKeyboardMouseHoverState();
      }
    } else {
      const speed = keyboardMouseState.activeKeys.has('Shift') ? SLOW_CURSOR_SPEED : FAST_CURSOR_SPEED;
      const distance = speed * deltaSeconds;
      const previousX = keyboardMouseState.x;
      const previousY = keyboardMouseState.y;
      setKeyboardMousePosition(
        keyboardMouseState.x + (vector.x * distance),
        keyboardMouseState.y + (vector.y * distance),
      );
      if (
        keyboardMouseState.pressedButton === 0
        && (Math.abs(previousX - keyboardMouseState.x) > 0.1 || Math.abs(previousY - keyboardMouseState.y) > 0.1)
      ) {
        dispatchKeyboardMouseDragMove();
      }
    }
  }

  if (!hasMovement) {
    resetKeyboardMouseLoop();
    return;
  }

  keyboardMouseState.rafId = requestAnimationFrame(stepKeyboardMouse);
};

const ensureKeyboardMouseLoop = () => {
  if (keyboardMouseState.rafId || !isKeyboardMouseActive()) return;
  keyboardMouseState.rafId = requestAnimationFrame(stepKeyboardMouse);
};

const shouldHandleKeyboardMouseEvent = (event) => {
  if (!keyboardMouseState.enabled) return false;
  if (!event) return false;
  if (event.defaultPrevented) return false;
  return true;
};

const handleKeyboardMouseKeyDown = (event) => {
  if (!shouldHandleKeyboardMouseEvent(event)) return;

  if (event.key === 'Tab') {
    deactivateKeyboardMouse();
    return;
  }

  if (event.altKey || event.metaKey) return;
  if (isEditableTarget(event.target)) return;

  syncModifierKeysFromEvent(event);

  if (event.key === 'Shift' || event.key === 'Control') {
    keyboardMouseState.activeKeys.add(event.key);
    return;
  }

  if (TRIGGER_KEYS.has(event.key)) {
    if (event.repeat) return;
    keyboardMouseState.activeKeys.add(event.key);
    event.preventDefault();
    event.stopPropagation();
    handleKeyboardMouseTriggerDown(event.key);
    return;
  }

  if (!ARROW_KEYS.has(event.key)) return;

  activateKeyboardMouse();
  keyboardMouseState.activeKeys.add(event.key);
  event.preventDefault();
  event.stopPropagation();
  ensureKeyboardMousePosition();
  ensureKeyboardMouseLoop();
};

const handleKeyboardMouseKeyUp = (event) => {
  if (!keyboardMouseState.enabled || !event) return;

  syncModifierKeysFromEvent(event);

  if (TRIGGER_KEYS.has(event.key) && keyboardMouseState.triggerKey === event.key) {
    releaseKeyboardMousePrimaryPress();
  }

  if (event.key === 'Shift' || event.key === 'Control' || TRIGGER_KEYS.has(event.key) || ARROW_KEYS.has(event.key)) {
    keyboardMouseState.activeKeys.delete(event.key);
  }

  if (TRIGGER_KEYS.has(event.key) || ARROW_KEYS.has(event.key)) {
    event.preventDefault();
    event.stopPropagation();
  }

  if (![...ARROW_KEYS].some((key) => keyboardMouseState.activeKeys.has(key))) {
    resetKeyboardMouseLoop();
  }
};

const handlePhysicalMouseMove = (event) => {
  if (!event?.isTrusted) return;
  recordPhysicalPointerPosition(event.clientX, event.clientY);
  if (!keyboardMouseState.enabled || !keyboardMouseState.active) return;
  deactivateKeyboardMouse();
};

const handlePhysicalMouseInput = (event) => {
  if (!event?.isTrusted) return;
  if (Number.isFinite(event.clientX) && Number.isFinite(event.clientY)) {
    recordPhysicalPointerPosition(event.clientX, event.clientY);
  }
  if (!keyboardMouseState.enabled || !keyboardMouseState.active) return;
  deactivateKeyboardMouse();
};

const handleViewportResize = () => {
  if (!keyboardMouseState.enabled) return;
  renderKeyboardMouseCursor();
  if (isKeyboardMouseActive()) {
    syncKeyboardMouseHoverState();
  }
};

export const initKeyboardMouse = () => {
  if (keyboardMouseState.bound) return;
  keyboardMouseState.bound = true;

  ensureKeyboardMouseCursor();
  setKeyboardMouseDomEnabled(false);
  renderKeyboardMouseCursor();

  document.addEventListener('keydown', handleKeyboardMouseKeyDown, true);
  document.addEventListener('keyup', handleKeyboardMouseKeyUp, true);
  document.addEventListener('mousemove', handlePhysicalMouseMove, { passive: true });
  document.addEventListener('mousedown', handlePhysicalMouseInput, true);
  document.addEventListener('wheel', handlePhysicalMouseInput, { capture: true, passive: true });
  window.addEventListener('resize', handleViewportResize);
  window.addEventListener('blur', () => {
    if (keyboardMouseState.enabled && keyboardMouseState.active) {
      deactivateKeyboardMouse();
      return;
    }
    clearKeyboardMouseKeys();
  });
};

export const setKeyboardMouseEnabled = (enabled) => {
  initKeyboardMouse();
  keyboardMouseState.enabled = !!enabled;
  if (keyboardMouseState.enabled) {
    activateKeyboardMouse();
    return;
  }

  deactivateKeyboardMouse();
};

export const syncKeyboardMouseFromSettings = () => {
  setKeyboardMouseEnabled(isTruthy(state.settingsState.keyboard_mouse_enabled));
};

export const isKeyboardMouseEnabled = () => keyboardMouseState.enabled;
export const isKeyboardMouseCurrentlyActive = () => isKeyboardMouseActive();