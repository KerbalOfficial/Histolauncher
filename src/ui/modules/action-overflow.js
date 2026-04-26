// ui/modules/action-overflow.js

import { getEl } from './dom-utils.js';
import { state } from './state.js';

export const closeAllActionOverflowMenus = () => {
  state.actionOverflowControllers.forEach((controller) => {
    if (controller && typeof controller.closeMenu === 'function') {
      controller.closeMenu();
    }
  });
};

export const refreshActionOverflowMenus = () => {
  state.actionOverflowControllers.forEach((controller) => {
    if (controller && typeof controller.refresh === 'function') {
      controller.refresh();
    }
  });
};

export const setupTopbarActionOverflow = ({
  topbarId,
  triggerId,
  menuId,
  sourceButtonIds = [],
  menuActions = [],
}) => {
  const topbar = getEl(topbarId);
  const trigger = getEl(triggerId);
  const menu = getEl(menuId);
  if (!topbar || !trigger || !menu) return null;

  const sourceButtons = sourceButtonIds
    .map((id) => getEl(id))
    .filter((el) => !!el);

  if (!trigger.hasAttribute('aria-haspopup')) trigger.setAttribute('aria-haspopup', 'menu');
  if (!trigger.hasAttribute('aria-controls')) trigger.setAttribute('aria-controls', menuId);
  if (!trigger.hasAttribute('aria-expanded')) trigger.setAttribute('aria-expanded', 'false');

  const isMenuOpen = () => !menu.classList.contains('hidden');

  const closeMenu = ({ restoreFocus = false } = {}) => {
    menu.classList.add('hidden');
    trigger.setAttribute('aria-expanded', 'false');

    if (restoreFocus) {
      try {
        trigger.focus();
      } catch (e) {
        // Ignore
      }
    }
  };

  const openMenu = ({ focusFirstItem = false } = {}) => {
    if (trigger.classList.contains('hidden')) return;
    menu.classList.remove('hidden');
    trigger.setAttribute('aria-expanded', 'true');

    if (focusFirstItem) {
      const first = menu.querySelector(
        'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
      );
      if (first && typeof first.focus === 'function') {
        first.focus();
      }
    }
  };

  const setCollapsed = (collapsed) => {
    sourceButtons.forEach((btn) => {
      btn.classList.toggle('actions-overflow-source-hidden', collapsed);
    });
    trigger.classList.toggle('hidden', !collapsed);
    if (!collapsed) closeMenu();
  };

  const needsOverflowCollapse = () => {
    const internalOverflow = topbar.scrollWidth > (topbar.clientWidth + 2);
    const rect = topbar.getBoundingClientRect();
    const viewportOverflow = rect.right > (window.innerWidth - 2);

    const parentEl = topbar.parentElement;
    const parentOverflow = (() => {
      if (!parentEl) return false;
      const parentRect = parentEl.getBoundingClientRect();
      return rect.right > (parentRect.right + 1);
    })();

    return internalOverflow || viewportOverflow || parentOverflow;
  };

  const updateLayout = () => {
    if (topbar.offsetParent === null) {
      closeMenu();
      return;
    }

    setCollapsed(false);
    const needsOverflow = needsOverflowCollapse();
    if (needsOverflow) {
      setCollapsed(true);
    }
  };

  let rafToken = 0;
  const refresh = () => {
    if (rafToken) {
      cancelAnimationFrame(rafToken);
    }
    rafToken = requestAnimationFrame(() => {
      rafToken = 0;
      updateLayout();
    });
  };

  trigger.addEventListener('click', (ev) => {
    ev.stopPropagation();
    if (trigger.classList.contains('hidden')) return;
    if (isMenuOpen()) {
      closeMenu();
    } else {
      openMenu();
    }
  });

  trigger.addEventListener('keydown', (ev) => {
    if (trigger.classList.contains('hidden')) return;

    if (ev.key === 'Escape' && isMenuOpen()) {
      ev.preventDefault();
      ev.stopPropagation();
      closeMenu({ restoreFocus: true });
      return;
    }

    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      ev.stopPropagation();
      openMenu({ focusFirstItem: true });
    }
  });

  menu.addEventListener('click', (ev) => {
    ev.stopPropagation();
  });

  menu.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') {
      ev.preventDefault();
      ev.stopPropagation();
      closeMenu({ restoreFocus: true });
    }
  });

  menuActions.forEach((action) => {
    const menuBtn = getEl(action.menuButtonId);
    const targetBtn = getEl(action.targetButtonId);
    if (!menuBtn || !targetBtn) return;
    menuBtn.addEventListener('click', (ev) => {
      ev.preventDefault();
      closeMenu({ restoreFocus: true });
      targetBtn.click();
    });
  });

  window.addEventListener('resize', refresh);

  if (typeof ResizeObserver !== 'undefined') {
    const resizeObserver = new ResizeObserver(() => {
      refresh();
    });
    resizeObserver.observe(topbar);
    if (topbar.parentElement) {
      resizeObserver.observe(topbar.parentElement);
    }
  }

  return {
    closeMenu,
    refresh,
  };
};

export const initResponsiveActionOverflowMenus = () => {
  state.actionOverflowControllers.length = 0;

  const versionsOverflow = setupTopbarActionOverflow({
    topbarId: 'versions-topbar-filter',
    triggerId: 'versions-actions-overflow-btn',
    menuId: 'versions-actions-overflow-menu',
    sourceButtonIds: ['export-versions-btn', 'import-versions-btn'],
    menuActions: [
      { menuButtonId: 'versions-overflow-export-btn', targetButtonId: 'export-versions-btn' },
      { menuButtonId: 'versions-overflow-import-btn', targetButtonId: 'import-versions-btn' },
    ],
  });
  if (versionsOverflow) state.actionOverflowControllers.push(versionsOverflow);

  const modsOverflow = setupTopbarActionOverflow({
    topbarId: 'mods-topbar-filter',
    triggerId: 'mods-actions-overflow-btn',
    menuId: 'mods-actions-overflow-menu',
    sourceButtonIds: ['export-modpack-btn', 'import-modpack-btn', 'import-mod-btn'],
    menuActions: [
      { menuButtonId: 'mods-overflow-export-modpack-btn', targetButtonId: 'export-modpack-btn' },
      { menuButtonId: 'mods-overflow-import-modpack-btn', targetButtonId: 'import-modpack-btn' },
      { menuButtonId: 'mods-overflow-import-mod-btn', targetButtonId: 'import-mod-btn' },
    ],
  });
  if (modsOverflow) state.actionOverflowControllers.push(modsOverflow);

  const worldsOverflow = setupTopbarActionOverflow({
    topbarId: 'worlds-topbar-filter',
    triggerId: 'worlds-actions-overflow-btn',
    menuId: 'worlds-actions-overflow-menu',
    sourceButtonIds: ['worlds-import-btn'],
    menuActions: [
      { menuButtonId: 'worlds-overflow-import-btn', targetButtonId: 'worlds-import-btn' },
    ],
  });
  if (worldsOverflow) state.actionOverflowControllers.push(worldsOverflow);

  refreshActionOverflowMenus();
  setTimeout(() => refreshActionOverflowMenus(), 0);
  setTimeout(() => refreshActionOverflowMenus(), 180);
  window.addEventListener('load', refreshActionOverflowMenus, { once: true });
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => {
      refreshActionOverflowMenus();
    });
  }
};
