// ui/modules/versions-data.js

import { state } from './state.js';
import { api } from './api.js';
import { getEl, toggleClass } from './dom-utils.js';
import { ADD_PROFILE_OPTION, AVAILABLE_PAGE_SIZE } from './config.js';
import { formatBytes } from './string-utils.js';
import { renderCommonPagination } from './pagination.js';
import { createEmptyState } from './ui-states.js';
import {
  createVersionCard,
  updateVersionsBulkActionsUI,
  pruneVersionsBulkSelection,
} from './versions.js';
import {
  renderScopeProfilesSelect,
  showCreateScopeProfileModal,
  showDeleteScopeProfileModal,
  showRenameScopeProfileModal,
  switchScopeProfile,
  updateScopeProfileDeleteButtonState,
  updateScopeProfileEditButtonState,
} from './profiles.js';

// ---------------- Category / filtering ----------------

export const buildCategoryListFromVersions = (list) => {
  const set = new Set();
  list.forEach((v) => {
    if (v.category) set.add(v.category);
  });
  return Array.from(set).sort();
};

export const formatCategoryName = (cat) => {
  if (!cat) return '';
  const lower = String(cat).toLowerCase();
  if (lower.startsWith('oa-')) {
    return 'OA-' + cat.slice(3);
  }
  return cat.charAt(0).toUpperCase() + cat.slice(1);
};

export const sortRemoteVersions = (list) => {
  return (Array.isArray(list) ? list : []).slice().sort((a, b) => {
    const sourceOrder = (src) => {
      const s = String(src || '').toLowerCase();
      if (s === 'mojang') return 0;
      if (s === 'omniarchive') return 1;
      return 2;
    };
    return sourceOrder(a.source) - sourceOrder(b.source);
  });
};

export const keepNonRemoteVersions = (list) => {
  return (Array.isArray(list) ? list : []).filter(
    (v) => v.installed || v.installing || v.source === 'modloader'
  );
};

export const setVersionsWarning = (message = '') => {
  const warn = getEl('versions-section-warning');
  if (!warn) return;
  if (message) {
    warn.textContent = message;
    warn.classList.remove('hidden');
    return;
  }
  warn.classList.add('hidden');
};

export const setVersionsLoadingState = (isLoading) => {
  const loading = getEl('versions-loading');
  if (loading) {
    loading.classList.toggle('hidden', !isLoading);
  }

  const refreshBtn = getEl('versions-refresh-btn');
  if (refreshBtn) {
    refreshBtn.disabled = isLoading;
  }
};

export const mergeAvailableVersionsIntoState = (remoteVersions, categories = []) => {
  const retainedVersions = keepNonRemoteVersions(state.versionsList);
  const normalizedRemote = sortRemoteVersions(remoteVersions).map((v) => ({
    display: v.display || v.folder,
    category: v.category || 'Release',
    folder: v.folder,
    installed: false,
    installing: false,
    is_remote: true,
    source: v.source || 'mojang',
    image_url: v.image_url || null,
    total_size_bytes: v.total_size_bytes || 0,
    installed_local: !!v.installed_local,
    redownload_available: !!v.redownload_available,
    recommended: !!v.recommended,
  }));

  state.versionsList = retainedVersions.concat(normalizedRemote);
  state.categoriesList =
    Array.isArray(categories) && categories.length > 0
      ? categories.slice()
      : buildCategoryListFromVersions(state.versionsList);
  initCategoryFilter();
};

export const loadAvailableVersions = async ({ force = false, reload = false } = {}) => {
  if (state.versionsPageDataLoading) return false;
  if (state.versionsPageDataLoaded && !force && !reload) return true;

  const requestId = ++state.versionsLoadRequestId;
  state.versionsPageDataLoading = true;
  state.versionsManifestError = false;

  if (force) {
    state.versionsAvailablePage = 1;
  }

  state.versionsList = keepNonRemoteVersions(state.versionsList);
  state.categoriesList = buildCategoryListFromVersions(state.versionsList);
  initCategoryFilter();
  setVersionsWarning('');
  setVersionsLoadingState(true);
  renderAllVersionSections();

  try {
    const res = await api(force ? '/api/versions?refresh=1' : '/api/versions', 'GET');
    if (requestId !== state.versionsLoadRequestId) return false;

    if (!res || res.ok === false) {
      throw new Error((res && res.error) || 'Failed to load versions.');
    }

    mergeAvailableVersionsIntoState(res.available, res.categories);
    state.versionsPageDataLoaded = true;
    state.versionsManifestError = !!res.manifest_error;

    if (state.versionsManifestError) {
      setVersionsWarning(
        'Unable to fetch downloadable versions, please check your internet connection (or URL Proxy in settings)!'
      );
    } else {
      setVersionsWarning('');
    }
  } catch (err) {
    if (requestId !== state.versionsLoadRequestId) return false;

    console.error('[versions] Failed to load available versions:', err);
    state.versionsPageDataLoaded = false;
    state.versionsManifestError = true;
    state.versionsList = keepNonRemoteVersions(state.versionsList);
    state.categoriesList = buildCategoryListFromVersions(state.versionsList);
    initCategoryFilter();
    setVersionsWarning(
      'Unable to fetch downloadable versions, please check your internet connection (or URL Proxy in settings)!'
    );
  } finally {
    if (requestId === state.versionsLoadRequestId) {
      state.versionsPageDataLoading = false;
      setVersionsLoadingState(false);
      renderAllVersionSections();
    }
  }

  return !state.versionsManifestError;
};

export const getFilterState = () => {
  const searchEl = getEl('versions-search');
  const q = searchEl ? (searchEl.value || '').trim().toLowerCase() : '';
  return { categories: state.selectedVersionCategories.slice(), q };
};

export const filterVersionsForUI = () => {
  const { categories, q } = getFilterState();
  let list = state.versionsList.slice();

  // Only filter by category if at least one is selected
  if (categories && categories.length > 0) {
    const selectedCategories = new Set(
      categories.map((category) => String(category || '').trim().toLowerCase())
    );
    list = list.filter((v) =>
      selectedCategories.has(String(v.category || '').trim().toLowerCase())
    );
  }

  if (q) {
    list = list.filter((v) => {
      const hay = `${v.display} ${v.folder} ${v.category}`.toLowerCase();
      return hay.includes(q);
    });
  }

  const installed = list.filter((v) => v.installed && !v.installing);
  const installing = list.filter((v) => v.installing);
  const installingKeys = new Set(
    installing.map((v) => `${String(v.category || '').toLowerCase()}/${v.folder || ''}`)
  );
  // Transient modloader entries are only for in-progress cards and should
  // never appear in the Available list.
  const available = list.filter(
    (v) => !v.installed
      && !v.installing
      && v.source !== 'modloader'
      && !v.suppress_available_while_installing
      && !installingKeys.has(`${String(v.category || '').toLowerCase()}/${v.folder || ''}`)
  );

  return { installed, installing, available };
};

export const initCategoryFilter = () => {
  const sel = getEl('versions-category-select');
  if (!sel) return;

  state.selectedVersionCategories = state.selectedVersionCategories.filter((c) =>
    state.categoriesList.includes(c)
  );

  const renderCategoryOptions = () => {
    sel.innerHTML = '';

    const allOpt = document.createElement('option');
    allOpt.value = '';
    allOpt.textContent =
      state.selectedVersionCategories.length > 0
        ? state.selectedVersionCategories.map(formatCategoryName).join(', ')
        : '* All';
    sel.appendChild(allOpt);

    const selectAllOpt = document.createElement('option');
    selectAllOpt.value = '[SELECT ALL]';
    selectAllOpt.textContent = '[ SELECT ALL ]';
    sel.appendChild(selectAllOpt);

    const deselectAllOpt = document.createElement('option');
    deselectAllOpt.value = '[DESELECT ALL]';
    deselectAllOpt.textContent = '[ DESELECT ALL ]';
    sel.appendChild(deselectAllOpt);

    state.categoriesList.forEach((c) => {
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = state.selectedVersionCategories.includes(c) ? `☑ ${formatCategoryName(c)}` : `☐ ${formatCategoryName(c)}`;
      sel.appendChild(opt);
    });

    sel.value = '';
  };

  renderCategoryOptions();
  sel.onchange = () => {
    const picked = sel.value;
    if (!picked) {
      state.selectedVersionCategories = [];
    } else if (picked === '[SELECT ALL]') {
      state.selectedVersionCategories = state.categoriesList.slice();
    } else if (picked === '[DESELECT ALL]') {
      state.selectedVersionCategories = [];
    } else if (state.selectedVersionCategories.includes(picked)) {
      state.selectedVersionCategories = state.selectedVersionCategories.filter(
        (c) => c !== picked
      );
    } else {
      state.selectedVersionCategories.push(picked);
    }

    renderCategoryOptions();
    state.versionsAvailablePage = 1;
    renderAllVersionSections();
  };

  const searchEl = getEl('versions-search');
  if (searchEl) {
    searchEl.oninput = () => {
      state.versionsAvailablePage = 1;
      renderAllVersionSections();
    };
  }

  const profileSelect = getEl('versions-profile-select');
  if (profileSelect) {
    renderScopeProfilesSelect('versions');
    profileSelect.onchange = async (e) => {
      const selected = String((e && e.target && e.target.value) || '').trim();
      if (!selected) {
        renderScopeProfilesSelect('versions');
        return;
      }

      if (selected === ADD_PROFILE_OPTION) {
        profileSelect.value = state.versionsProfilesState.activeProfile;
        showCreateScopeProfileModal('versions');
        return;
      }

      if (selected === state.versionsProfilesState.activeProfile) {
        return;
      }

      await switchScopeProfile('versions', selected);
    };
  }

  const profileEditBtn = getEl('versions-profile-edit-btn');
  const profileEditIcon = getEl('versions-profile-edit-icon');
  if (profileEditBtn) {
    if (profileEditIcon) {
      profileEditBtn.onmouseenter = () => {
        if (!profileEditBtn.disabled) profileEditIcon.src = 'assets/images/filled_pencil.png';
      };
      profileEditBtn.onmouseleave = () => {
        profileEditIcon.src = 'assets/images/unfilled_pencil.png';
      };
    }
    profileEditBtn.onclick = (e) => {
      e.preventDefault();
      if (profileEditBtn.disabled) return;
      showRenameScopeProfileModal('versions');
    };
    updateScopeProfileEditButtonState('versions');
  }

  const profileDeleteBtn = getEl('versions-profile-delete-btn');
  const profileDeleteIcon = getEl('versions-profile-delete-icon');
  if (profileDeleteBtn) {
    if (profileDeleteIcon) {
      profileDeleteBtn.onmouseenter = () => {
        if (!profileDeleteBtn.disabled) profileDeleteIcon.src = 'assets/images/filled_delete.png';
      };
      profileDeleteBtn.onmouseleave = () => {
        profileDeleteIcon.src = 'assets/images/unfilled_delete.png';
      };
    }
    profileDeleteBtn.onclick = (e) => {
      e.preventDefault();
      if (profileDeleteBtn.disabled) return;
      showDeleteScopeProfileModal('versions');
    };
    updateScopeProfileDeleteButtonState('versions');
  }
};

// ---------------- Badges / size ----------------

export const formatSizeBadge = (v) => {
  let bytes = v.total_size_bytes;

  if (typeof bytes === 'number' && bytes > 0) {
    return formatBytes(bytes);
  }

  if (typeof v.size_mb === 'number' && v.size_mb > 0) {
    return `${v.size_mb.toFixed(1)} MB`;
  }

  return null;
};

// ---------------- Rendering sections ----------------

export const renderAllVersionSections = () => {
  const installedContainer = getEl('installed-versions');
  const installingContainer = getEl('installing-versions');
  const availableContainer = getEl('available-versions');
  const versionsPagination = getEl('versions-pagination');
  const availableSection = getEl('available-section');
  const installingSection = getEl('installing-section');

  if (!installedContainer || !installingContainer || !availableContainer) {
    return;
  }

  pruneVersionsBulkSelection();
  updateVersionsBulkActionsUI();

  installedContainer.innerHTML = '';
  installingContainer.innerHTML = '';
  availableContainer.innerHTML = '';

  const { installed, installing, available } = filterVersionsForUI();

  const installedVersionsSubtitle = getEl('installed-versions-subtitle');
  if (installedVersionsSubtitle) {
    const c = installed.length;
    installedVersionsSubtitle.textContent = `${c} version${c !== 1 ? 's' : ''} installed`;
  }

  const favs = state.settingsState.favorite_versions || [];
  const sortByFavorite = (a, b) => {
    const aFav = favs.includes(`${a.category}/${a.folder}`);
    const bFav = favs.includes(`${b.category}/${b.folder}`);
    if (aFav && !bFav) return -1;
    if (!aFav && bFav) return 1;
    return 0;
  };
  installed.sort(sortByFavorite);

  if (installed.length === 0) {
    installedContainer.appendChild(createEmptyState('No versions installed'));
  } else {
    installed.forEach((v) => {
      const card = createVersionCard(v, 'installed');
      if (state.selectedVersion && `${v.category}/${v.folder}` === state.selectedVersion) {
        card.classList.add('selected');
      }
      installedContainer.appendChild(card);
    });
  }

  if (installingSection) {
    toggleClass(installingSection, 'hidden', installing.length === 0);
  }

  if (installing.length > 0) {
    installing.forEach((v) => {
      const card = createVersionCard(v, 'installing');
      if (card._progressFill && typeof v._progressOverall === 'number') {
        card._progressFill.style.width = `${v._progressOverall}%`;
        if (v.paused) {
          card._progressFill.classList.add('paused');
        } else {
          card._progressFill.classList.remove('paused');
        }
      }
      if (card._progressTextEl && typeof v._progressText === 'string') {
        card._progressTextEl.textContent = v._progressText;
      }
      const pauseBtn = card.querySelector('.pause-resume-btn');
      if (pauseBtn) {
        pauseBtn.textContent = v.paused ? 'Resume' : 'Pause';
        pauseBtn.classList.remove(v.paused ? 'mild' : 'primary');
        pauseBtn.classList.add(v.paused ? 'primary' : 'mild');
      }
      installingContainer.appendChild(card);
    });
  }

  if (availableSection) {
    const shouldShowAvailableSection =
      state.versionsPageDataLoading ||
      state.versionsPageDataLoaded ||
      state.versionsManifestError ||
      available.length > 0;
    availableSection.style.display = shouldShowAvailableSection ? '' : 'none';
  }

  if (!availableContainer) return;
  availableContainer.innerHTML = '';

  if (versionsPagination) {
    versionsPagination.innerHTML = '';
  }

  if (state.versionsPageDataLoading || state.versionsManifestError) {
    updateVersionsBulkActionsUI();
    return;
  }

  if (available.length === 0) {
    if (state.versionsPageDataLoaded) {
      availableContainer.appendChild(
        createEmptyState('No available versions')
      );
    }
    updateVersionsBulkActionsUI();
    return;
  }

  const totalAvailablePages = Math.max(1, Math.ceil(available.length / AVAILABLE_PAGE_SIZE));
  state.versionsAvailablePage = Math.min(Math.max(1, state.versionsAvailablePage), totalAvailablePages);
  const startIndex = (state.versionsAvailablePage - 1) * AVAILABLE_PAGE_SIZE;
  const slice = available.slice(startIndex, startIndex + AVAILABLE_PAGE_SIZE);
  slice.forEach((v) => {
    const card = createVersionCard(v, 'available');
    availableContainer.appendChild(card);
  });

  if (versionsPagination) {
    renderCommonPagination(
      versionsPagination,
      totalAvailablePages,
      state.versionsAvailablePage,
      (page) => {
        state.versionsAvailablePage = page;
        renderAllVersionSections();
      }
    );
  }

  updateVersionsBulkActionsUI();
};
