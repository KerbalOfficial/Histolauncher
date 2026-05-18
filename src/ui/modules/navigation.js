// ui/modules/navigation.js

import { state } from './state.js';
import {
  $$,
  getEl,
  focusMainContentForPage,
  isEditableTarget,
} from './dom-utils.js';
import { closeAllActionOverflowMenus, refreshActionOverflowMenus } from './action-overflow.js';
import { loadAvailableVersions } from './versions-data.js';
import { refreshModsPageState } from './mods.js';
import { refreshScreenshotsPageState } from './screenshots.js';
import { refreshWorldsPageState } from './worlds.js';
import { refreshJavaRuntimeOptions, updatePlaytimeStats, startHomeLiveStream, stopHomeLiveStream } from './home.js';


const showPage = async (page) => {
  $$('.page').forEach((p) => p.classList.add('hidden'));
  const el = getEl(`page-${page}`);
  if (el) el.classList.remove('hidden');

  if (page !== 'home') stopHomeLiveStream();
  if (page === 'home') startHomeLiveStream();

  if (page === 'versions' && !state.versionsPageDataLoaded) {
    loadAvailableVersions();
  }

  if (page === 'settings') {
    updatePlaytimeStats();
    if (!state.javaRuntimesLoaded) {
      const ok = await refreshJavaRuntimeOptions(false);
      if (ok) state.javaRuntimesLoaded = true;
    }
  }

  if (page === 'mods' && !state.modsPageDataLoaded) {
    const loaded = await refreshModsPageState();
    state.modsPageDataLoaded = loaded !== false;
  }

  if (page === 'worlds' && !state.worldsPageDataLoaded) {
    const loaded = await refreshWorldsPageState();
    state.worldsPageDataLoaded = loaded !== false;
  }

  if (page === 'screenshots' && !state.screenshotsPageDataLoaded) {
    const loaded = await refreshScreenshotsPageState();
    state.screenshotsPageDataLoaded = loaded !== false;
  }

  closeAllActionOverflowMenus();
  refreshActionOverflowMenus();

  // Move keyboard focus into the newly visible page content.
  setTimeout(() => focusMainContentForPage(page), 0);
};

export const initSidebar = () => {
  const items = $$('.sidebar-item');

  const activateSidebarItem = async (item) => {
    if (!item) return;
    const icon = item.querySelector('.sidebar-icon');

    items.forEach((i) => {
      i.classList.remove('active');
      i.removeAttribute('aria-current');
      const ic = i.querySelector('.sidebar-icon');
      if (ic && ic.dataset && ic.dataset.static) {
        ic.src = ic.dataset.static;
      }
    });

    item.classList.add('active');
    item.setAttribute('aria-current', 'page');
    if (icon && icon.dataset && icon.dataset.anim) {
      icon.src = icon.dataset.anim;
    }

    await showPage(item.dataset.page);
  };

  const clickSidebarPage = async (pageKey) => {
    const item = items.find((x) => String(x.dataset.page || '') === String(pageKey || ''));
    if (!item) return;
    await activateSidebarItem(item);
  };

  const bindNumberHotkeys = () => {
    const root = document.documentElement;
    if (root && root.dataset && root.dataset.sidebarNumberHotkeysBound === '1') return;
    if (root && root.dataset) root.dataset.sidebarNumberHotkeysBound = '1';

    document.addEventListener('keydown', async (event) => {
      if (!event) return;
      if (event.repeat) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;

      const msgboxOverlay = getEl('msgbox-overlay');
      if (msgboxOverlay && !msgboxOverlay.classList.contains('hidden')) return;

      if (isEditableTarget(event.target)) return;

      const map = {
        '1': 'home',
        '2': 'versions',
        '3': 'worlds',
        '4': 'screenshots',
        '5': 'mods',
        '6': 'settings',
        '7': 'about',
      };

      const pageKey = map[String(event.key || '')];
      if (!pageKey) return;

      event.preventDefault();
      event.stopPropagation();
      try {
        await clickSidebarPage(pageKey);
      } catch (err) {
        console.error('[navigation] Failed to switch page:', err);
      }
    });
  };

  items.forEach((item) => {
    const icon = item.querySelector('.sidebar-icon');

    if (!item.hasAttribute('role')) item.setAttribute('role', 'button');
    if (!item.hasAttribute('tabindex')) item.setAttribute('tabindex', '0');

    item.addEventListener('click', () => {
      activateSidebarItem(item).catch((err) => {
        console.error('[navigation] Failed to switch page:', err);
      });
    });

    item.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        item.click();
      }
    });

    if (!icon) return;

    item.addEventListener('mouseenter', () => {
      if (icon.dataset && icon.dataset.anim) {
        icon.src = icon.dataset.anim;
      }
    });

    item.addEventListener('mouseleave', () => {
      if (
        !item.classList.contains('active') &&
        icon.dataset &&
        icon.dataset.static
      ) {
        icon.src = icon.dataset.static;
      }
    });
  });

  bindNumberHotkeys();
};
