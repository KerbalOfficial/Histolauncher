// ui/modules/main.js

import { unicodeList } from './config.js';

import { $$, getEl } from './dom-utils.js';


import { isInitialCacheDirty, loadCachedInitialData, saveCachedInitialData } from './cache.js';

import { api } from './api.js';

import { state } from './state.js';

import { showLoadingOverlay, hideLoadingOverlay } from './modal.js';

import { closeAllActionOverflowMenus, initResponsiveActionOverflowMenus } from './action-overflow.js';

import { initTooltips } from './tooltips.js';

import { initWorldsPage, refreshWorldsPageState, loadInstalledWorlds } from './worlds.js';

import {
  initModsPage,
  refreshModsPageState,
  loadInstalledMods,
  showModDetailModal,
} from './mods.js';

import { setVersionsDeps } from './versions.js';

import { startPollingForInstall, setInstallDeps } from './install.js';

import {
  initVersionsViewToggle,
  initCollapsibleSections,
  initVersionsExportImport,
  setVersionControlsDeps,
} from './version-controls.js';

import { updateSettingsValidationUI, initLaunchButton, setLaunchDeps } from './launch.js';

import {
  normalizeStorageDirectoryMode,
  normalizeVersionStorageOverrideMode,
  getCustomStorageDirectoryPath,
  getCustomStorageDirectoryError,
  refreshCustomStorageDirectoryValidation,
  applyScopeProfilesState,
  renderScopeProfilesSelect,
  setProfilesDeps,
} from './profiles.js';

import {
  buildCategoryListFromVersions,
  setVersionsWarning,
  setVersionsLoadingState,
  loadAvailableVersions,
  initCategoryFilter,
  formatSizeBadge,
  renderAllVersionSections,
} from './versions-data.js';


import {
  debug,
  refreshHomeGlobalMessage,
  updateHomeInfo,
  initSettings,
  refreshJavaRuntimeOptions,
  setHomeDeps,
} from './home.js';

import { initSidebar } from './navigation.js';
import {
  autoSaveSetting,
  initSettingsInputs,
  setSettingsAutosaveDeps,
} from './settings-autosave.js';
import {
  checkForCorruptedVersions,
  setCorruptedModalDeps,
} from './corrupted-modal.js';

// ---------------- Launch button (Home) ----------------

// ---------------- Refresh button ----------------

const initRefreshButton = () => {
  const refreshBtn = getEl('refresh-btn');
  if (!refreshBtn) return;

  refreshBtn.addEventListener('click', (e) => {
    if (e.shiftKey) {
      location.reload();
      return;
    }
    init({ preserveAvailableData: true });
  });
};

// ---------------- Shift key tracking (global) ----------------

const initShiftTracking = () => {
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Shift') {
      state.isShiftDown = true;
    }
  });
  document.addEventListener('keyup', (e) => {
    if (e.key === 'Shift') {
      state.isShiftDown = false;
    }
  });
};

const stopActiveInstallPoller = (installKey) => {
  const poller = state.activeInstallPollers[installKey];
  if (!poller) return;

  if (typeof poller === 'function') {
    poller();
  } else {
    clearTimeout(poller);
    delete state.activeInstallPollers[installKey];
  }
};

// ---------------- Init ----------------

const applyInitialData = async (
  data,
  { fromCache = false, preserveAvailableData = false } = {}
) => {
  if (!data || typeof data !== 'object') return;

  const statusEl = getEl('status');
  if (statusEl) statusEl.textContent = '';

  const mapKey = (cat, folder) =>
    `${(cat || '').toLowerCase()}/${folder || ''}`;
  const previousVersionsByKey = new Map(
    state.versionsList
      .filter(Boolean)
      .map((v) => [v._cardFullId || mapKey(v.category, v.folder), v])
  );

  const preservedAvailableVersions = preserveAvailableData
    ? state.versionsList.filter(
        (v) =>
          !!v &&
          !!v.is_remote &&
          !v.installed &&
          !v.installing &&
          v.source !== 'modloader'
      )
    : [];

  if (!preserveAvailableData) {
    state.versionsLoadRequestId += 1;
    state.versionsPageDataLoaded = false;
    state.versionsPageDataLoading = false;
    state.versionsManifestError = false;
    setVersionsLoadingState(false);
    setVersionsWarning('');
  } else if (!state.versionsPageDataLoading) {
    setVersionsLoadingState(false);
  }

  const installedFromBackend = Array.isArray(data.installed)
    ? data.installed
    : [];
  const installingFromBackend = Array.isArray(data.installing)
    ? data.installing
    : [];

  const normalizedInstalled = installedFromBackend.map((v) => ({
    display: v.display_name || v.display || v.folder,
    category: v.category || 'Local',
    folder: v.folder,
    installed: true,
    installing: false,
    is_remote: false,
    source: 'local',
    image_url: v.image_url || null,
    storage_override_mode: normalizeVersionStorageOverrideMode(v.storage_override_mode),
    storage_override_path: v.storage_override_path || '',
    total_size_bytes: v.total_size_bytes || 0,
    _progressOverall: 100,
    _progressText: v.is_imported ? 'Imported' : 'Installed',
    raw: v,
  }));

  const versionsMap = new Map();
  normalizedInstalled.forEach((v) =>
    versionsMap.set(mapKey(v.category, v.folder), v)
  );

  installingFromBackend.forEach((item) => {
    const rawKey =
      item.version_key ||
      `${(item.category || 'unknown').toLowerCase()}/${item.folder}`;
    const encodedKey = encodeURIComponent(rawKey);
    const cat = item.category || 'Unknown';
    const folder = item.folder;
    const display = item.display || folder;
    const pct = item.overall_percent || 0;
    const bytesDone = item.bytes_done || 0;
    const bytesTotal = item.bytes_total || 0;

    const source = item.source || 'installing';
    const cardFullId = item.card_full_id || rawKey;
    const k = source === 'modloader' ? cardFullId : mapKey(cat, folder);
    let v = versionsMap.get(k);
    const previousVersion = previousVersionsByKey.get(k) || previousVersionsByKey.get(mapKey(cat, folder));
    const imageUrl = item.image_url || (previousVersion && previousVersion.image_url) || 'assets/images/version_placeholder.png';
    const progressText =
      bytesTotal > 0
        ? `${pct}% (${Math.round(bytesDone / (1024 * 1024))} MB / ${Math.round(bytesTotal / (1024 * 1024))} MB)`
        : `${pct}%`;

    if (!v) {
      v = {
        display,
        category: cat,
        folder,
        installed: false,
        installing: true,
        is_remote: false,
        source,
        image_url: imageUrl,
        _cardFullId: cardFullId,
        _installKey: encodedKey,
        _progressOverall: pct,
        _progressText: progressText,
        _loaderType: item.loader_type || '',
        _loaderVersion: item.loader_version || '',
      };
      versionsMap.set(k, v);
    } else {
      v.installing = true;
      v.source = source || v.source || 'installing';
      v._cardFullId = cardFullId;
      v._installKey = encodedKey;
      v._progressOverall = pct;
      v._progressText = progressText;
      v.image_url = imageUrl;
      v._loaderType = item.loader_type || v._loaderType || '';
      v._loaderVersion = item.loader_version || v._loaderVersion || '';
    }

    try {
      startPollingForInstall(encodedKey, v);
    } catch (e) {
      // ignore
    }
  });

  const finalList = [];
  for (const v of versionsMap.values()) if (v.installed && !v.installing) finalList.push(v);
  for (const v of versionsMap.values()) if (v.installing) finalList.push(v);

  if (preserveAvailableData && preservedAvailableVersions.length > 0) {
    const existingKeys = new Set(
      finalList.map((v) => mapKey(v.category, v.folder))
    );
    preservedAvailableVersions.forEach((v) => {
      const k = mapKey(v.category, v.folder);
      const hasLocalVersion = existingKeys.has(k);
      const hasInstallingVersion = finalList.some(
        (item) => mapKey(item.category, item.folder) === k && item.installing
      );
      if (hasInstallingVersion) return;
      finalList.push({
        ...v,
        installed: false,
        installing: false,
        installed_local: hasLocalVersion || !!v.installed_local,
        redownload_available: hasLocalVersion || !!v.redownload_available,
        suppress_available_while_installing: false,
      });
      existingKeys.add(k);
    });
  }

  state.versionsList = finalList.map((v) => ({ ...v }));
  state.categoriesList = buildCategoryListFromVersions(state.versionsList);

  state.selectedVersion = data.selected_version || null;

  await initSettings(data.settings || {}, {
    profiles: Array.isArray(data.profiles) ? data.profiles : [],
    active_profile: data.active_profile || 'default',
  });

  applyScopeProfilesState(
    'versions',
    Array.isArray(data.versions_profiles) ? data.versions_profiles : [],
    data.active_versions_profile || 'default'
  );
  applyScopeProfilesState(
    'mods',
    Array.isArray(data.mods_profiles) ? data.mods_profiles : [],
    data.active_mods_profile || 'default'
  );
  renderScopeProfilesSelect('versions');
  renderScopeProfilesSelect('mods');

  const accountSelect = getEl('settings-account-type');
  const connectBtn = getEl('connect-account-btn');
  const disconnectBtn = getEl('disconnect-account-btn');
  const acctType = state.settingsState.account_type || 'Local';
  const isConnected = !!state.settingsState.uuid;

  if (accountSelect) accountSelect.value = acctType;
  if (connectBtn) connectBtn.style.display = 'none';
  if (disconnectBtn) disconnectBtn.style.display = 'none';

  updateHomeInfo();
  refreshHomeGlobalMessage();

  initCategoryFilter();
  renderAllVersionSections();

  state.versionsList.forEach((v) => {
    if (v.installing && v._installKey) {
      stopActiveInstallPoller(v._installKey);
      try {
        startPollingForInstall(v._installKey, v);
      } catch (e) {
        console.warn('[init] Failed to restart polling for', v._installKey, e);
      }
    }
  });

  if (state.selectedVersion) {
    const selCard = document.querySelector(
      `.version-card[data-full-id="${state.selectedVersion}"]`
    );
    $$('.version-card').forEach((c) => c.classList.remove('selected'));
    $$('.version-card[aria-current]').forEach((c) =>
      c.setAttribute('aria-current', 'false')
    );
    if (selCard) {
      selCard.classList.add('selected');
      selCard.setAttribute('aria-current', 'true');
      const found = state.versionsList.find(
        (v) => `${v.category}/${v.folder}` === state.selectedVersion
      );
      if (found) {
        state.selectedVersionDisplay = found.display;
        updateHomeInfo();
      }
    } else {
      state.selectedVersion = null;
      state.selectedVersionDisplay = null;
      updateHomeInfo();
    }
  } else {
    state.selectedVersionDisplay = null;
    updateHomeInfo();
  }

  const settingsPage = getEl('page-settings');
  const versionsPage = getEl('page-versions');
  const worldsPage = getEl('page-worlds');
  const modsPage = getEl('page-mods');

  if (settingsPage && !settingsPage.classList.contains('hidden') && !state.javaRuntimesLoaded) {
    const ok = await refreshJavaRuntimeOptions(false);
    if (ok) state.javaRuntimesLoaded = true;
  }

  if (modsPage && !modsPage.classList.contains('hidden')) {
    if (!state.modsPageDataLoaded) {
      let loaded = false;
      if (preserveAvailableData) {
        loaded = await loadInstalledMods();
      } else {
        loaded = await refreshModsPageState();
      }
      state.modsPageDataLoaded = loaded !== false;
    } else if (preserveAvailableData) {
      await loadInstalledMods();
    }
  }

  if (worldsPage && !worldsPage.classList.contains('hidden')) {
    if (!state.worldsPageDataLoaded) {
      const loaded = await refreshWorldsPageState();
      state.worldsPageDataLoaded = loaded !== false;
    } else if (preserveAvailableData) {
      await loadInstalledWorlds();
    }
  }

  hideLoadingOverlay();

  if (
    !fromCache &&
    !preserveAvailableData &&
    versionsPage &&
    !versionsPage.classList.contains('hidden') &&
    !state.versionsPageDataLoaded
  ) {
    loadAvailableVersions();
  }
};

const refreshInitialData = async ({ preserveAvailableData = false } = {}) => {
  try {
    const data = await api('/api/initial');
    if (!data) return false;
    await applyInitialData(data, { fromCache: false, preserveAvailableData });
    saveCachedInitialData(data);
    return true;
  } catch (e) {
    console.error('[refreshInitialData] Failed to refresh initial data:', e);
    return false;
  }
};

const init = async ({ preserveAvailableData = false } = {}) => {
  showLoadingOverlay();
  state.javaRuntimesLoaded = false;
  state.javaRuntimesLoading = false;
  state.javaRuntimesLoadAttempted = false;

  if (!preserveAvailableData) {
    state.versionsPageDataLoaded = false;
    state.versionsPageDataLoading = false;
    state.versionsManifestError = false;
    state.versionsLoadRequestId += 1;
    state.modsPageDataLoaded = false;
    state.worldsPageDataLoaded = false;
    state.versionsAvailablePage = 1;
  }

  const cachedData = isInitialCacheDirty() ? null : loadCachedInitialData();
  const initialDataPromise = api('/api/initial');

  if (cachedData) {
    try {
      await applyInitialData(cachedData, {
        fromCache: true,
        preserveAvailableData,
      });
    } catch (e) {
      console.warn('[init] Failed to render cached data:', e);
    }
    hideLoadingOverlay();
  }

  let data = null;
  try {
    data = await initialDataPromise;
  } catch (e) {
    console.error('[init] Failed to fetch initial data:', e);
  }

  if (data) {
    try {
      await applyInitialData(data, {
        fromCache: false,
        preserveAvailableData,
      });
      saveCachedInitialData(data);
    } catch (e) {
      console.error('[init] Failed to render initial data:', e);
    }
  }

  // Refresh launcher version info in sidebar
  let localVersion = null;
  let isOutdated = false;

  try {
    const fetchWithTimeout = (url, ms = 5000) => {
      const controller = new AbortController();
      const id = setTimeout(() => controller.abort(), ms);
      return fetch(url, { signal: controller.signal }).finally(() =>
        clearTimeout(id)
      );
    };

    const [lvRes, iloRes] = await Promise.allSettled([
      fetchWithTimeout('/launcher/version.dat'),
      fetchWithTimeout('/api/is-launcher-outdated/'),
    ]);

    if (lvRes.status === 'fulfilled' && lvRes.value && lvRes.value.ok) {
      try {
        localVersion = (await lvRes.value.text()).trim();
      } catch (e) {
        localVersion = null;
      }
    }

    if (iloRes.status === 'fulfilled' && iloRes.value && iloRes.value.ok) {
      try {
        isOutdated = await iloRes.value.json();
        isOutdated = !!isOutdated;
      } catch (e) {
        isOutdated = false;
      }
    }
  } catch (e) {
    localVersion = localVersion || null;
    isOutdated = false;
  }

  try {
    const el = getEl('sidebar-version');
    if (el) {
      if (localVersion) {
        if (isOutdated) {
          el.classList.add('outdated');
          el.textContent = `${localVersion} (outdated)`;
        } else {
          el.classList.remove('outdated');
          el.textContent = localVersion;
        }
      } else {
        el.classList.remove('outdated');
        el.textContent = 'unknown';
      }
    }
  } catch (e) {
    // ignore
  }

  hideLoadingOverlay();

  await checkForCorruptedVersions();
};

// ---------------- Cleanup polling timers on page unload ----------------

const clearAllPollers = () => {
  // Clear all active polling timers to prevent orphaned timers
  for (const key in state.activeInstallPollers) {
    stopActiveInstallPoller(key);
  }
  debug('[cleanup] Cleared all active polling timers');
};

// Clean up polling timers when page unloads or refreshes
window.addEventListener('beforeunload', clearAllPollers);
window.addEventListener('unload', clearAllPollers);

// ---------------- Settings Dropdowns ----------------

const initSettingsDropdowns = () => {
  const titles = $$('.settings-dropdown-title');

  titles.forEach((title) => {
    const content = title.nextElementSibling;
    if (!content || !content.classList.contains('settings-dropdown-content')) {
      return;
    }

    if (!title.hasAttribute('role')) title.setAttribute('role', 'button');
    if (!title.hasAttribute('tabindex')) title.setAttribute('tabindex', '0');

    const indicator = title.querySelector('.dropdown-indicator');
    const setExpanded = (expanded) => {
      content.classList.toggle('collapsed', !expanded);
      if (indicator) indicator.textContent = expanded ? unicodeList.dropdown_open : unicodeList.dropdown_close;
      title.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    };

    const handleToggle = () => {
      const expanded = !content.classList.contains('collapsed');
      setExpanded(!expanded);
    };

    title.addEventListener('click', handleToggle);
    title.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        handleToggle();
      }
    });

    setExpanded(!content.classList.contains('collapsed'));
  });
};


// ---------------- Global init ----------------

setInstallDeps({
  debug,
  init,
  loadAvailableVersions,
  refreshInitialData,
  renderAllVersionSections,
});

setVersionsDeps({
  formatSizeBadge,
  init,
  normalizeVersionStorageOverrideMode,
  renderAllVersionSections,
  updateHomeInfo,
});

setVersionControlsDeps({
  autoSaveSetting,
  debug,
  init,
  loadAvailableVersions,
});

setLaunchDeps({
  debug,
  getCustomStorageDirectoryError,
  getCustomStorageDirectoryPath,
  normalizeStorageDirectoryMode,
  refreshCustomStorageDirectoryValidation,
  updateHomeInfo,
});

setProfilesDeps({
  init,
});

setHomeDeps({
  autoSaveSetting,
  init,
});

setSettingsAutosaveDeps({
  init,
});

setCorruptedModalDeps({
  refreshInitialData,
});

const formatExternalProjectDisplayName = (slug) => String(slug || '')
  .split(/[-_]+/)
  .filter(Boolean)
  .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
  .join(' ') || 'Unknown Project';

const resolveCurseForgeAddonLink = (href) => {
  const match = String(href || '').match(
    /curseforge\.com\/minecraft\/(mc-mods|texture-packs|shaders|modpacks)\/([^/?#]+)/i
  );
  if (!match) return null;

  const category = String(match[1] || '').toLowerCase();
  const addonType = category === 'texture-packs'
    ? 'resourcepacks'
    : category === 'shaders'
      ? 'shaderpacks'
      : category === 'modpacks'
        ? 'modpacks'
      : 'mods';

  return {
    addon_type: addonType,
    slug: match[2],
  };
};

const resolveModrinthAddonLink = (href) => {
  const match = String(href || '').match(
    /modrinth\.com\/(mod|plugin|datapack|resourcepack|shader|modpack)\/([^/?#]+)/i
  );
  if (!match) return null;

  const projectType = String(match[1] || '').toLowerCase();
  const addonType = projectType === 'resourcepack'
    ? 'resourcepacks'
    : projectType === 'shader'
      ? 'shaderpacks'
      : projectType === 'modpack'
        ? 'modpacks'
      : 'mods';

  return {
    addon_type: addonType,
    slug: match[2],
  };
};

document.addEventListener('DOMContentLoaded', () => {
  document.addEventListener('click', async (ev) => {
    const a = ev.target.closest('a[href]');
    if (!a) return;
    const rawHref = (a.getAttribute('href') || '').trim();
    const normalizedHref = (a.getAttribute('data-external-url') || (
      rawHref.startsWith('//') ? `https:${rawHref}` :
      (rawHref.startsWith('www.') ? `https://${rawHref}` : rawHref)
    )).trim();
    if (!normalizedHref || (!normalizedHref.startsWith('http://') && !normalizedHref.startsWith('https://'))) return;
    ev.preventDefault();
    ev.stopPropagation();

    const curseForgeProject = resolveCurseForgeAddonLink(normalizedHref);
    if (curseForgeProject) {
      const { addon_type, slug } = curseForgeProject;
      const displayName = formatExternalProjectDisplayName(slug);
      try {
        const searchRes = await api('/api/mods/search', 'POST', {
          addon_type,
          provider: 'curseforge',
          search_query: slug,
          game_version: '',
          mod_loader: '',
          page_size: 50,
          page_index: 0,
        });

        const mods = (searchRes && searchRes.ok && Array.isArray(searchRes.mods)) ? searchRes.mods : [];
        const slugNorm = String(slug).toLowerCase();
        const exact = mods.find((m) => String(m.mod_slug || '').toLowerCase() === slugNorm);
        const picked = exact || mods[0];

        if (picked && picked.mod_id) {
          showModDetailModal({
            addon_type,
            mod_id: picked.mod_id,
            provider: 'curseforge',
            name: picked.name || displayName,
          });
          return;
        }
      } catch (e) {
        console.error('Failed to resolve CurseForge addon link:', e);
      }

      window.open(normalizedHref, '_blank');
      return;
    }
    const modrinthProject = resolveModrinthAddonLink(normalizedHref);
    if (modrinthProject) {
      const { addon_type, slug } = modrinthProject;
      const displayName = formatExternalProjectDisplayName(slug);
      showModDetailModal({
        addon_type,
        mod_id: slug,
        provider: 'modrinth',
        name: displayName,
      });
      return;
    }

    window.open(normalizedHref, '_blank');
  }, true);

  document.addEventListener('click', () => {
    closeAllActionOverflowMenus();
  });

  window.addEventListener('focus', () => {
    if (normalizeStorageDirectoryMode(state.settingsState.storage_directory) === 'custom') {
      refreshCustomStorageDirectoryValidation();
    }
  });

  initShiftTracking();
  initSidebar();
  initSettingsDropdowns();
  initCollapsibleSections();
  initTooltips();
  initLaunchButton();
  initRefreshButton();
  initSettingsInputs();
  initVersionsViewToggle();
  initVersionsExportImport();
  initWorldsPage();
  initModsPage();
  initResponsiveActionOverflowMenus();
  updateSettingsValidationUI();
  init();
});
