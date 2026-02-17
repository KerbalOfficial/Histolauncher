// ui/app.js

(() => {
  // ---------------- State ----------------

  let selectedVersion = null;
  let selectedVersionDisplay = null;
  let versionsList = [];
  let categoriesList = [];
  let settingsState = {};
  let histolauncherUsername = '';
  let localUsernameModified = false;
  const activeInstallPollers = {};
  let visibleAvailableCount = 0;
  const AVAILABLE_PAGE_SIZE = 30;

  // ---------------- DOM helpers ----------------

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  const getEl = (id) => document.getElementById(id);

  const setText = (id, text) => {
    const el = getEl(id);
    if (el) el.textContent = text;
  };

  const setHTML = (id, html) => {
    const el = getEl(id);
    if (el) el.innerHTML = html;
  };

  const toggleClass = (el, className, on) => {
    if (!el) return;
    el.classList[on ? 'add' : 'remove'](className);
  };

  const safeAddEvent = (el, type, handler) => {
    if (el) el.addEventListener(type, handler);
  };

  // ---------------- API helper ----------------

  const api = async (path, method = 'GET', body = null) => {
    const opts = { method, headers: {} };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    return res.json();
  };

  const imageAttachErrorPlaceholder = (img, placeholderLink) => {
    img.addEventListener('error', () => {
      if (!img.src.endsWith(placeholderLink)) {
        img.src = placeholderLink;
      }
    });
  };

  // ---------------- Settings / Home info ----------------

  const normalizeFavoriteVersions = (favRaw) => {
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

  const updateHomeInfo = () => {
    const infoVersionImgHTML =
      '<img width="16px" height="16px" src="assets/images/library.png"/>';
    const infoUsernameImgHTML =
      '<img width="16px" height="16px" src="assets/images/settings.gif"/>';
    const infoRamImgHTML =
      '<img width="16px" height="16px" src="assets/images/settings.gif"/>';

    const versionText = selectedVersionDisplay
      ? `${infoVersionImgHTML} Version: ${selectedVersionDisplay}`
      : `${infoVersionImgHTML} Version: (none selected)`;
    setHTML('info-version', versionText);

    const username = settingsState.username || 'Player';
    const acctType = settingsState.account_type || 'Local';
    setHTML('info-username', `${infoUsernameImgHTML} Account: ${username} (${acctType})`);

    const minRam = (settingsState.min_ram || '256M').toUpperCase();
    const maxRam = (settingsState.max_ram || '1024M').toUpperCase();
    setHTML('info-ram', `${infoRamImgHTML} RAM Limit: ${minRam}B - ${maxRam}B`);

    const topbarProfile = getEl('topbar-profile');
    const topbarUsername = getEl('topbar-username');
    const topbarProfilePic = getEl('topbar-profile-pic');
    
    if (acctType === 'Histolauncher' && settingsState.uuid) {
      if (topbarProfile) {
        topbarProfile.style.display = 'flex';
        topbarProfile.style.alignItems = 'center';
        topbarProfile.style.gap = '8px';
      }
      if (topbarUsername) topbarUsername.textContent = username;
      if (topbarProfilePic) {
        const textureUrl = `http://textures.histolauncher.workers.dev/head/${settingsState.uuid}`;
        topbarProfilePic.src = textureUrl;
        imageAttachErrorPlaceholder(topbarProfilePic, '/assets/images/unknown.png');
      }
    } else {
      if (topbarProfile) topbarProfile.style.display = 'none';
    }
  };

  const initSettings = async (data) => {
    settingsState = { ...settingsState, ...data };

    settingsState.favorite_versions = normalizeFavoriteVersions(
      settingsState.favorite_versions
    );

    if (settingsState.account_type === 'Histolauncher') {
      if (settingsState.histolauncher_username) {
        settingsState.username = settingsState.histolauncher_username;
        histolauncherUsername = settingsState.histolauncher_username;
      } else if (settingsState.uuid && settingsState.username) {
        histolauncherUsername = settingsState.username;
      }
    }

    const usernameInput = getEl('settings-username');
    const usernameRow = getEl('username-row');
    if (usernameInput) {
      usernameInput.value = settingsState.username || 'Player';
      
      const isHistolauncher = settingsState.account_type === 'Histolauncher';
      usernameInput.disabled = isHistolauncher;
      
      if (usernameRow) {
        usernameRow.style.display = isHistolauncher ? 'none' : 'block';
      }
      
      if (isHistolauncher && settingsState.uuid) {
        histolauncherUsername = settingsState.username;
      }
    }

    const minRamInput = getEl('settings-min-ram');
    if (minRamInput) minRamInput.value = settingsState.min_ram || '256M';

    const maxRamInput = getEl('settings-max-ram');
    if (maxRamInput) maxRamInput.value = settingsState.max_ram || '1024M';

    const proxyEl = getEl('settings-url-proxy');
    if (proxyEl) proxyEl.value = settingsState.url_proxy || '';

    const lowDataEl = getEl('settings-low-data');
    if (lowDataEl) lowDataEl.checked = settingsState.low_data_mode === "1";

    const accountSelect = getEl('settings-account-type');
    const connectBtn = getEl('connect-account-btn');
    const disconnectBtn = getEl('disconnect-account-btn');
    const acctType = settingsState.account_type || 'Local';
    const isConnected = !!settingsState.uuid;
    
    if (accountSelect) accountSelect.value = acctType;
    if (connectBtn) connectBtn.style.display = 'none';
    if (disconnectBtn) disconnectBtn.style.display = 'none';

    updateHomeInfo();
  };

  // ---------------- Category / filtering ----------------

  const buildCategoryListFromVersions = (list) => {
    const set = new Set();
    list.forEach((v) => {
      if (v.category) set.add(v.category);
    });
    return Array.from(set).sort();
  };

  const getFilterState = () => {
    const sel = getEl('versions-category-select');
    const searchEl = getEl('versions-search');
    const category = sel ? sel.value : '';
    const q = searchEl ? (searchEl.value || '').trim().toLowerCase() : '';
    return { category, q };
  };

  const filterVersionsForUI = () => {
    const { category, q } = getFilterState();
    let list = versionsList.slice();

    if (category) {
      list = list.filter((v) => v.category === category);
    }

    if (q) {
      list = list.filter((v) => {
        const hay = `${v.display} ${v.folder} ${v.category}`.toLowerCase();
        return hay.includes(q);
      });
    }

    const installed = list.filter((v) => v.installed && !v.installing);
    const installing = list.filter((v) => v.installing);
    const available = list.filter((v) => !v.installed && !v.installing);

    return { installed, installing, available };
  };

  const initCategoryFilter = () => {
    const sel = getEl('versions-category-select');
    if (!sel) return;

    sel.innerHTML = '';

    const allOpt = document.createElement('option');
    allOpt.value = '';
    allOpt.textContent = '* All';
    sel.appendChild(allOpt);

    categoriesList.forEach((c) => {
      const opt = document.createElement('option');
      opt.value = c;
      opt.textContent = c;
      sel.appendChild(opt);
    });

    sel.value = '';
    sel.addEventListener('change', renderAllVersionSections);

    const searchEl = getEl('versions-search');
    if (searchEl) {
      searchEl.addEventListener('input', renderAllVersionSections);
    }
  };

  // ---------------- Badges / size ----------------

  const formatBytes = (bytes) => {
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

  const formatSizeBadge = (v) => {
    let bytes = v.total_size_bytes;
    
    if (typeof bytes === 'number' && bytes > 0) {
      return formatBytes(bytes);
    }
    
    if (typeof v.size_mb === 'number' && v.size_mb > 0) {
      return `${v.size_mb.toFixed(1)} MB`;
    }
    
    return null;
  };

  // ---------------- Message Box ----------------

  const showMessageBox = ({ title = '', message = '', buttons = [], inputs = [] }) => {
    const overlay = getEl('msgbox-overlay');
    const boxTitle = getEl('msgbox-title');
    const boxText = getEl('msgbox-text');
    const btnContainer = getEl('msgbox-buttons');

    if (!overlay || !boxTitle || !boxText || !btnContainer) return;

    boxTitle.textContent = title;
    boxText.innerHTML = typeof message === 'string' ? message : '';

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

    buttons.forEach((btn) => {
      const el = document.createElement('button');
      el.textContent = btn.label;
      if (btn.classList) el.classList.add(...btn.classList);

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

        overlay.classList.add('hidden');
        if (btn.onClick) btn.onClick(values);
      });

      btnContainer.appendChild(el);
    });

    overlay.classList.remove('hidden');
  };

  // ---------------- Install handling ----------------

  const startInstallForFolder = async (folder, category, fullDownloadMode) => {
    if (!folder || typeof folder !== 'string' || folder.trim().length === 0) {
      console.error('startInstallForFolder: missing folder');
      return null;
    }
    if (!category || typeof category !== 'string') {
      category = 'release';
    }

    const fullFlag = !!fullDownloadMode;
    const baseKey = `${category.toLowerCase()}/${folder}`;

    const payloads = [
      { version: folder, category, full_assets: fullFlag },
      { folder, category, full_assets: fullFlag },
      { version_key: baseKey, full_assets: fullFlag },
      { key: baseKey, full_assets: fullFlag },
      baseKey,
    ];

    for (const payload of payloads) {
      try {
        const res = await fetch('/api/install', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        let json;
        try {
          json = await res.json();
        } catch (e) {
          const txt = await res.text().catch(() => '<no body>');
          console.error('install response not JSON:', res.status, txt);
          continue;
        }

        if (json && json.started) {
          return json.version || baseKey;
        }
        if (json && json.error) {
          console.warn(
            'install attempt returned error:',
            json.error,
            'payload:',
            payload
          );
          continue;
        }
        if (json && typeof json === 'object' && json.version) {
          return json.version;
        }
      } catch (e) {
        console.warn('install start failed for payload', payload, e);
      }
    }

    console.error('install start failed: all payload attempts returned errors');
    return null;
  };

  const cancelInstallForVersionKey = async (versionKeyEncoded) => {
    if (!versionKeyEncoded) return;
    try {
      const res = await fetch(`/api/cancel/${versionKeyEncoded}`, {
        method: 'POST',
      });
      const json = await res.json().catch(() => null);
      console.log('cancel response', json);

      versionsList = versionsList.map((x) => {
        const matchesKey =
          (x._installKey && x._installKey === versionKeyEncoded) ||
          `${x.category}/${x.folder}` === decodeURIComponent(versionKeyEncoded);
        if (matchesKey) {
          return {
            ...x,
            installing: false,
            _installKey: null,
            _progressText: 'Cancelled',
            _progressOverall: 0,
          };
        }
        return x;
      });

      if (activeInstallPollers[versionKeyEncoded]) {
        clearTimeout(activeInstallPollers[versionKeyEncoded]);
        delete activeInstallPollers[versionKeyEncoded];
      }
    } catch (e) {
      console.warn('cancel failed', e);
    }
  };

  const pauseInstallForVersionKey = async (versionKeyEncoded) => {
    if (!versionKeyEncoded) return;
    try {
      const res = await fetch(`/api/pause/${versionKeyEncoded}`, {
        method: 'POST',
      });
      const json = await res.json().catch(() => null);
      console.log('pause response', json);
    } catch (e) {
      console.warn('pause failed', e);
    }
  };

  const resumeInstallForVersionKey = async (versionKeyEncoded) => {
    if (!versionKeyEncoded) return;
    try {
      const res = await fetch(`/api/resume/${versionKeyEncoded}`, {
        method: 'POST',
      });
      const json = await res.json().catch(() => null);
      console.log('resume response', json);
    } catch (e) {
      console.warn('resume failed', e);
    }
  };

  const handleInstallClick = async (v, card, installBtn, fullDownloadMode) => {
    const folder = v.folder;
    const category = v.category || 'Release';

    if (!folder || !folder.trim()) {
        installBtn.textContent = 'Error';
        setTimeout(() => {
            const isLowDataMode = settingsState.low_data_mode === "1";
            installBtn.textContent = isLowDataMode ? 'Quick Download' : 'Full Download';
        }, 1500);
        return;
    }

    installBtn.disabled = true;
    installBtn.textContent = 'Starting...';
    card.classList.add('installing');

    const rawVersionKey = await startInstallForFolder(
        folder,
        category,
        fullDownloadMode
    );
    if (!rawVersionKey) {
      card.classList.remove('installing');
      installBtn.disabled = false;
      installBtn.textContent = 'Download';
      return;
    }

    const encodedKey = encodeURIComponent(rawVersionKey);

    v._installKey = encodedKey;
    v.installing = true;
    v.full_install = fullDownloadMode;
    v._progressText = 'Starting...';
    v._progressOverall = 0;

    versionsList = versionsList.map((x) =>
      x.category === v.category && x.folder === v.folder
        ? {
            ...x,
            installing: true,
            _installKey: encodedKey,
            full_install: fullDownloadMode,
            image_url: x.image_url,
            _progressText: 'Starting...',
            _progressOverall: 0,
          }
        : x
    );

    renderAllVersionSections();
    startPollingForInstall(encodedKey, v);
  };

  // ---------------- Polling for install progress ----------------

  const updateVersionInListByKey = (versionKeyEncoded, updater) => {
    versionsList = versionsList.map((x) => {
      const matchesKey =
        (x._installKey && x._installKey === versionKeyEncoded) ||
        `${x.category}/${x.folder}` === decodeURIComponent(versionKeyEncoded);
      return matchesKey ? updater(x) : x;
    });
  };

  const updateCardProgressUI = (vMeta, pct, text, options = {}) => {
    const { paused, statusLabel, pausedColor } = options;
    const card = document.querySelector(
      `.version-card[data-full-id="${vMeta.category}/${vMeta.folder}"]`
    );
    if (!card) return;

    if (card._progressFill) {
      card._progressFill.style.width = `${pct}%`;
      if (paused) {
        card._progressFill.classList.add('paused');
        if (pausedColor) card._progressFill.style.background = pausedColor;
      } else {
        card._progressFill.classList.remove('paused');
        card._progressFill.style.background = '';
      }
    }

    if (card._progressTextEl) {
      card._progressTextEl.textContent = text;
    }

    const badge = card.querySelector('.version-badge');
    if (badge && statusLabel) {
      badge.textContent = statusLabel;
      if (paused) {
        badge.classList.add('paused');
      } else {
        badge.classList.remove('paused');
      }
    }

    const pauseBtn = card.querySelector('.pause-resume-btn');
    if (pauseBtn) {
      if (paused) {
        pauseBtn.textContent = 'Resume';
        pauseBtn.classList.remove('mild');
        pauseBtn.classList.add('primary');
      } else {
        pauseBtn.textContent = 'Pause';
        pauseBtn.classList.remove('primary');
        pauseBtn.classList.add('mild');
      }
    }

    if (!options.keepInstalling) {
      card.classList.remove('installing');
    }
  };

  const startPollingForInstall = (versionKeyEncoded, vMeta) => {
    if (!versionKeyEncoded) return;
    if (activeInstallPollers[versionKeyEncoded]) return;

    const poll = async () => {
      try {
        const r = await fetch(`/api/status/${versionKeyEncoded}`);
        if (!r.ok) {
          activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 300);
          return;
        }

        const s = await r.json();
        if (!s) {
          activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 300);
          return;
        }

        const status = s.status;
        if (status === 'unknown') {
          activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 200);
          return;
        }

        const pct = s.overall_percent || 0;
        const bytesDone = s.bytes_done || 0;
        const bytesTotal = s.bytes_total || 0;

        const mbDone = bytesDone / (1024 * 1024);
        const mbTotal = bytesTotal / (1024 * 1024);

        let text = '';
        let keepPolling = true;

        if (status === 'downloading' || status === 'starting') {
          vMeta.paused = false;
          text =
            bytesTotal > 0
              ? `${pct}% (${mbDone.toFixed(1)} MB / ${mbTotal.toFixed(1)} MB)`
              : `${pct}%`;

          updateVersionInListByKey(versionKeyEncoded, (x) => ({
            ...x,
            paused: false,
            _progressText: text,
            _progressOverall: pct,
          }));

          updateCardProgressUI(vMeta, pct, text, {
            paused: false,
            statusLabel: 'INSTALLING',
            keepInstalling: true,
          });
        } else if (status === 'installed') {
          text = 'Installed';
          keepPolling = false;

          updateVersionInListByKey(versionKeyEncoded, (x) => ({
            ...x,
            installed: true,
            installing: false,
            _installKey: null,
            _progressOverall: 100,
            _progressText: 'Installed',
          }));

          renderAllVersionSections();

          try {
            const fresh = await api('/api/initial');
            const backendInstalled = Array.isArray(fresh.installed)
              ? fresh.installed
              : [];

            versionsList = versionsList.filter((v) => !v.installed);

            backendInstalled.forEach((b) => {
              versionsList.push({
                display: b.display_name || b.display || b.folder,
                category: b.category,
                folder: b.folder,
                installed: true,
                installing: false,
                is_remote: false,
                source: 'local',
                image_url: b.image_url || null,
                total_size_bytes: b.total_size_bytes || 0,
                _progressOverall: 100,
                _progressText: 'Installed',
                raw: b,
              });
            });

            categoriesList =
              Array.isArray(fresh.categories) && fresh.categories.length > 0
                ? fresh.categories.slice()
                : buildCategoryListFromVersions(versionsList);

            initCategoryFilter();
            renderAllVersionSections();

            if (selectedVersion) {
              $$('.version-card').forEach((c) =>
                c.classList.remove('selected')
              );
              const selCard = document.querySelector(
                `.version-card[data-full-id="${selectedVersion}"]`
              );
              if (selCard) selCard.classList.add('selected');
            }
          } catch (e) {
            // ignore
          }
        } else if (status === 'failed') {
          text = 'Failed: ' + (s.message || '');
          keepPolling = false;

          updateVersionInListByKey(versionKeyEncoded, (x) => ({
            ...x,
            installing: false,
            _installKey: null,
            _progressOverall: pct,
            _progressText: text,
          }));
          renderAllVersionSections();
        } else if (status === 'cancelled') {
          text = 'Cancelled';
          keepPolling = false;

          updateVersionInListByKey(versionKeyEncoded, (x) => ({
            ...x,
            installing: false,
            _installKey: null,
            _progressOverall: pct,
            _progressText: text,
          }));
          renderAllVersionSections();
        } else if (status === 'paused') {
          text = 'Paused';

          updateVersionInListByKey(versionKeyEncoded, (x) => ({
            ...x,
            paused: true,
            _progressText: 'Paused',
            _progressOverall: pct,
          }));

          updateCardProgressUI(vMeta, pct, 'Paused', {
            paused: true,
            statusLabel: 'PAUSED',
            pausedColor: '#facc15',
            keepInstalling: true,
          });

          keepPolling = true;
          activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 600);
          return;
        }

        updateCardProgressUI(vMeta, pct, text, {
          keepInstalling: keepPolling,
        });

        if (keepPolling) {
          activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 200);
        } else {
          clearTimeout(activeInstallPollers[versionKeyEncoded]);
          delete activeInstallPollers[versionKeyEncoded];
        }
      } catch (e) {
        activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 300);
      }
    };

    activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 200);
  };

  // ---------------- Version card creation ----------------

  const createFavoriteButton = (v, fullId) => {
    const favBtn = document.createElement('div');
    favBtn.className = 'icon-button';

    const favImg = document.createElement('img');
    favImg.alt = 'favorite';

    const fullKey = fullId;
    const favs = settingsState.favorite_versions || [];
    favImg.src = favs.includes(fullKey)
      ? 'assets/images/filled_favorite.png'
      : 'assets/images/unfilled_favorite.png';

    imageAttachErrorPlaceholder(favImg, 'assets/images/placeholder.png');
    favBtn.appendChild(favImg);

    favBtn.addEventListener('mouseenter', () => {
      const listFav = settingsState.favorite_versions || [];
      if (!listFav.includes(fullKey)) {
        favImg.src = 'assets/images/filled_favorite.png';
      }
    });

    favBtn.addEventListener('mouseleave', () => {
      const listFav = settingsState.favorite_versions || [];
      favImg.src = listFav.includes(fullKey)
        ? 'assets/images/filled_favorite.png'
        : 'assets/images/unfilled_favorite.png';
    });

    favBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const listFav = settingsState.favorite_versions || [];
      const isFav = listFav.includes(fullKey);

      settingsState.favorite_versions = isFav
        ? listFav.filter((x) => x !== fullKey)
        : [...listFav, fullKey];

      favImg.src = isFav
        ? 'assets/images/unfilled_favorite.png'
        : 'assets/images/filled_favorite.png';

      await api('/api/settings', 'POST', {
        favorite_versions: settingsState.favorite_versions.join(', '),
      });
      renderAllVersionSections();
    });

    return favBtn;
  };

  const createDeleteButton = (v) => {
    const delBtn = document.createElement('div');
    delBtn.className = 'icon-button';

    const delImg = document.createElement('img');
    delImg.alt = 'delete';
    delImg.src = 'assets/images/unfilled_delete.png';
    imageAttachErrorPlaceholder(delImg, 'assets/images/placeholder.png');
    delBtn.appendChild(delImg);

    delBtn.addEventListener('mouseenter', () => {
      delImg.src = 'assets/images/filled_delete.png';
    });
    delBtn.addEventListener('mouseleave', () => {
      delImg.src = 'assets/images/unfilled_delete.png';
    });

    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();

      showMessageBox({
        title: 'Delete Version',
        message: `Are you sure you want to permanently delete ${v.category}/${v.folder}? This cannot be undone!`,
        buttons: [
          {
            label: 'Yes',
            classList: ['danger'],
            onClick: async () => {
              const res = await api('/api/delete', 'POST', {
                category: v.category,
                folder: v.folder,
              });

              if (res && res.ok) {
                await init();

                if (selectedVersion === `${v.category}/${v.folder}`) {
                  selectedVersion = null;
                  selectedVersionDisplay = null;
                  updateHomeInfo();
                }
              } else {
                showMessageBox({
                  title: 'Error',
                  message: res.error || 'Failed to delete version.',
                  buttons: [{ label: 'OK' }],
                });
              }
            },
          },
          { label: 'No' },
        ],
      });
    });

    return delBtn;
  };

  const createBadgeRow = (v, sectionType) => {
    const badgeRow = document.createElement('div');
    badgeRow.className = 'version-badge-row';

    const badgeMain = document.createElement('span');
    badgeMain.className =
        'version-badge ' +
        (sectionType === 'installed'
            ? 'installed'
            : 'available');

    if (sectionType === 'installing' && v.paused) {
        badgeMain.textContent = 'PAUSED';
        badgeMain.classList.add('paused');
    } else {
        badgeMain.textContent =
            sectionType === 'installed'
                ? 'INSTALLED'
                : sectionType === 'installing'
                ? 'INSTALLING'
                : 'AVAILABLE';
    }
    badgeRow.appendChild(badgeMain);

    if (v.is_remote && sectionType === 'available') {
        const badgeSource = document.createElement('span');
        badgeSource.className =
            'version-badge ' +
            (v.source === 'mojang' ? 'official' : 'nonofficial');
        badgeSource.textContent = v.source === 'mojang' ? 'MOJANG' : 'PROXY';
        badgeRow.appendChild(badgeSource);
    }

    if ((sectionType === 'installed' && v.raw && v.raw.full_assets === false)||(sectionType === 'installing' && v.full_install === false)) {
        const badgeLite = document.createElement('span');
        badgeLite.className = 'version-badge lite';
        badgeLite.textContent = 'LITE';
        badgeRow.appendChild(badgeLite);
    }

    const sizeLabel = formatSizeBadge(v);
    if (sizeLabel) {
        const badgeSize = document.createElement('span');
        badgeSize.className = 'version-badge size';
        badgeSize.textContent = sizeLabel;
        badgeRow.appendChild(badgeSize);
    }

    return badgeRow;
  };

  const createAvailableActions = (v, card) => {
    const actions = document.createElement('div');
    actions.className = 'version-actions';

    const installBtn = document.createElement('button');
    const isLowDataMode = settingsState.low_data_mode === "1";
    installBtn.textContent = isLowDataMode ? 'Quick Download' : 'Download';
    installBtn.className = isLowDataMode ? 'important' : 'primary';

    installBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const fullDownload = isLowDataMode === false || settingsState.low_data_mode !== "1";
        await handleInstallClick(v, card, installBtn, fullDownload);
    });

    actions.appendChild(installBtn);
    return actions;
  };

  const createInstallingActions = (v) => {
    const actions = document.createElement('div');
    actions.className = 'version-actions';

    const pauseBtn = document.createElement('button');
    pauseBtn.className = 'pause-resume-btn mild';
    pauseBtn.textContent = v.paused ? 'Resume' : 'Pause';
    pauseBtn.classList.remove(v.paused ? 'mild' : 'primary');
    pauseBtn.classList.add(v.paused ? 'primary' : 'mild');

    pauseBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!v._installKey) return;

      try {
        const st = await api(`/api/status/${v._installKey}`);
        const cur = ((st && st.status) || '').toLowerCase();
        if (cur === 'paused') {
          await resumeInstallForVersionKey(v._installKey);
        } else {
          await pauseInstallForVersionKey(v._installKey);
        }
      } catch (err) {
        console.warn('pause/resume action failed', err);
      }
    });

    actions.appendChild(pauseBtn);

    const cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';

    cancelBtn.addEventListener('click', (e) => {
      e.stopPropagation();

      showMessageBox({
        title: 'Cancel Download',
        message: `Do you want to cancel downloading ${v.category}/${v.folder}?`,
        buttons: [
          {
            label: 'Yes',
            classList: ['danger'],
            onClick: async () => {
              if (!v._installKey) return;
              await cancelInstallForVersionKey(v._installKey);
              await init();
            },
          },
          { label: 'No' },
        ],
      });
    });

    actions.appendChild(cancelBtn);
    return actions;
  };

  const createProgressElements = (card, v) => {
    const progressBar = document.createElement('div');
    progressBar.className = 'version-progress';

    const fill = document.createElement('div');
    fill.className = 'version-progress-fill';
    progressBar.appendChild(fill);
    card.appendChild(progressBar);

    const progressText = document.createElement('div');
    progressText.style.fontSize = '11px';
    progressText.style.padding = '4px 10px 8px 10px';
    progressText.style.color = '#9ca3af';
    progressText.textContent = v._progressText || '';
    card.appendChild(progressText);

    card._progressFill = fill;
    card._progressTextEl = progressText;

    if (typeof v._progressOverall === 'number') {
      fill.style.width = `${v._progressOverall}%`;
    }
  };

  const createVersionCard = (v, sectionType) => {
    const fullId = `${v.category}/${v.folder}`;

    const card = document.createElement('div');
    card.className = 'version-card';
    if (
      (settingsState.favorite_versions || []).includes(fullId) &&
      sectionType === 'installed'
    ) {
      card.classList.add('favorite');
    }
    card.setAttribute('data-full-id', fullId);

    if (sectionType !== 'installed') {
      card.classList.add('unselectable');
    }

    const img = document.createElement('img');
    img.className = 'version-image';
    img.src =
      v.image_url ||
      (v.is_remote
        ? 'assets/images/version_placeholder.png'
        : `clients/${v.category}/${v.folder}/display.png`);
    img.alt = v.display || '';
    imageAttachErrorPlaceholder(img, 'assets/images/version_placeholder.png');

    const info = document.createElement('div');
    info.className = 'version-info';

    const headerRow = document.createElement('div');
    headerRow.className = 'version-header-row';

    const disp = document.createElement('div');
    disp.className = 'version-display';
    disp.textContent = v.display;

    const folder = document.createElement('div');
    folder.className = 'version-folder';
    folder.textContent = v.category;

    const iconsRow = document.createElement('div');
    iconsRow.className = 'version-actions-icons';

    if (sectionType === 'installed') {
      iconsRow.appendChild(createFavoriteButton(v, fullId));
      iconsRow.appendChild(createDeleteButton(v));
    }

    headerRow.appendChild(disp);
    headerRow.appendChild(iconsRow);

    info.appendChild(headerRow);
    info.appendChild(folder);

    const badgeRow = createBadgeRow(v, sectionType);

    const actions =
      sectionType === 'available'
        ? createAvailableActions(v, card)
        : sectionType === 'installing'
        ? createInstallingActions(v)
        : (() => {
            const a = document.createElement('div');
            a.className = 'version-actions';
            return a;
          })();

    if (sectionType === 'installed') {
      card.addEventListener('click', async () => {
        $$('.version-card').forEach((c) => c.classList.remove('selected'));
        card.classList.add('selected');
        selectedVersion = fullId;
        selectedVersionDisplay = v.display;
        settingsState.selected_version = selectedVersion;
        updateHomeInfo();
        await api('/api/settings', 'POST', { selected_version: selectedVersion });
      });
    }

    if (sectionType === 'installing') {
      createProgressElements(card, v);
    }

    card.appendChild(img);
    card.appendChild(info);
    card.appendChild(badgeRow);
    card.appendChild(actions);

    return card;
  };

  // ---------------- Rendering sections ----------------

  const renderAllVersionSections = () => {
    const installedContainer = getEl('installed-versions');
    const installingContainer = getEl('installing-versions');
    const availableContainer = getEl('available-versions');
    const availableSection = getEl('available-section');
    const installingSection = getEl('installing-section');

    if (!installedContainer || !installingContainer || !availableContainer) {
      return;
    }

    installedContainer.innerHTML = '';
    installingContainer.innerHTML = '';
    availableContainer.innerHTML = '';

    const { installed, installing, available } = filterVersionsForUI();

    const favs = settingsState.favorite_versions || [];
    const sortByFavorite = (a, b) => {
      const aFav = favs.includes(`${a.category}/${a.folder}`);
      const bFav = favs.includes(`${b.category}/${b.folder}`);
      if (aFav && !bFav) return -1;
      if (!aFav && bFav) return 1;
      return 0;
    };
    installed.sort(sortByFavorite);

    if (installed.length === 0) {
      const empty = document.createElement('div');
      empty.style.padding = '12px';
      empty.style.color = '#9ca3af';
      empty.textContent = 'No installed versions yet.';
      installedContainer.appendChild(empty);
    } else {
      installed.forEach((v) => {
        const card = createVersionCard(v, 'installed');
        if (selectedVersion && `${v.category}/${v.folder}` === selectedVersion) {
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
      availableSection.style.display = available.length === 0 ? 'none' : '';
    }
    
    if (!availableContainer) return;
    availableContainer.innerHTML = '';

    const slice = available.slice(0, visibleAvailableCount);
    slice.forEach((v) => {
      const card = createVersionCard(v, 'available');
      availableContainer.appendChild(card);
    });

    if (available.length > visibleAvailableCount) {
      const loadMore = document.createElement('button');
      loadMore.textContent = 'Load more...';
      loadMore.style.marginTop = '20px';
      loadMore.style.width = "100%";
      loadMore.style.height = "60px";
      loadMore.addEventListener('click', () => {
        visibleAvailableCount += AVAILABLE_PAGE_SIZE;
        renderAllVersionSections();
      });
      availableContainer.appendChild(loadMore);
    }
  };

  // ---------------- Navigation / sidebar ----------------

  const showPage = (page) => {
    $$('.page').forEach((p) => p.classList.add('hidden'));
    const el = getEl(`page-${page}`);
    if (el) el.classList.remove('hidden');
  };

  const initSidebar = () => {
    const items = $$('.sidebar-item');
    items.forEach((item) => {
      const icon = item.querySelector('.sidebar-icon');

      item.addEventListener('click', () => {
        items.forEach((i) => {
          i.classList.remove('active');
          const ic = i.querySelector('.sidebar-icon');
          if (ic && ic.dataset && ic.dataset.static) {
            ic.src = ic.dataset.static;
          }
        });

        item.classList.add('active');
        if (icon && icon.dataset && icon.dataset.anim) {
          icon.src = icon.dataset.anim;
        }

        showPage(item.dataset.page);
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
  };

  // ---------------- Launch button (Home) ----------------

  const initLaunchButton = () => {
    const launchBtn = getEl('launch-btn');
    if (!launchBtn) return;

    launchBtn.addEventListener('click', async () => {
      if (!selectedVersion) {
        setText(
          'status',
          'Please select a version on the Versions page first!'
        );
        return;
      }

      const meta = versionsList.find(
        (v) => `${v.category}/${v.folder}` === selectedVersion
      );
      if (!meta) {
        setText('status', 'Selected version metadata not found.');
        return;
      }

      if (meta.raw && meta.raw.launch_disabled) {
        const msg =
          meta.raw.launch_disabled_message ||
          'This version cannot be launched yet.';
        window.alert(msg);
        setText('status', 'Failed to launch: ' + msg);
        return;
      }

      const overlay = getEl('loading-overlay');
      const box = getEl('launching-box');

      if (overlay) overlay.classList.remove('hidden');
      if (box) box.classList.remove('hidden');

      const username = settingsState.username || 'Player';
      const [category, folder] = selectedVersion.split('/');

      const res = await api('/api/launch', 'POST', { category, folder, username });

      setTimeout(() => {
        setText('status', res.message);
        if (overlay) overlay.classList.add('hidden');
        if (box) box.classList.add('hidden');
      }, 3000 + Math.random() * 7000);
    });
  };

  // ---------------- Refresh button ----------------

  const initRefreshButton = () => {
    const refreshBtn = getEl('refresh-btn');
    if (!refreshBtn) return;

    refreshBtn.addEventListener('click', (e) => {
      if (e.shiftKey) {
        location.reload();
        return;
      }
      init();
    });
  };

  // ---------------- Settings autosave ----------------

  const autoSaveSetting = (key, value) => {
    settingsState[key] = value;
    updateHomeInfo();
    if (key === 'username' && settingsState.account_type === 'Histolauncher') {
      return;
    }
    api('/api/settings', 'POST', { [key]: value });
  };

  const initSettingsInputs = () => {
    const usernameInput = getEl('settings-username');
    if (usernameInput) {
      usernameInput.addEventListener('input', (e) => {
        if (e.target.disabled) return;
        
        let v = e.target.value;
        v = v.replace(/[^ _0-9a-zA-Z]/g, '');
        v = v.replace(/ /g, '_');

        const firstUnderscoreIndex = v.indexOf('_');
        if (firstUnderscoreIndex !== -1) {
          v = v.replace(/_/g, '');
          v =
            v.slice(0, firstUnderscoreIndex) +
            '_' +
            v.slice(firstUnderscoreIndex);
        }

        e.target.value = v;
        localUsernameModified = true;
        autoSaveSetting('username', v);
      });
    }

    const ramInputHandler = (key) => (e) => {
      let v = e.target.value.toUpperCase();
      v = v.replace(/[^0-9KMGT]/gi, '').toUpperCase();

      const numbers = v.match(/^\d+/);
      const letter = v.match(/[KMGT]/i);
      let finalValue = '';

      if (numbers || !letter) {
        if (numbers) finalValue += numbers[0];
        if (letter) finalValue += letter[0];
      }

      e.target.value = finalValue;
      autoSaveSetting(key, finalValue);
    };

    const minRamInput = getEl('settings-min-ram');
    if (minRamInput) {
      minRamInput.addEventListener('input', ramInputHandler('min_ram'));
    }

    const maxRamInput = getEl('settings-max-ram');
    if (maxRamInput) {
      maxRamInput.addEventListener('input', ramInputHandler('max_ram'));
    }

    const storageSelect = getEl('settings-storage-dir');
    if (storageSelect) {
      storageSelect.addEventListener('change', (e) => {
        const val = e.target.value === 'version' ? 'version' : 'global';
        autoSaveSetting('storage_directory', val);
      });
    }

    const accountSelect = getEl('settings-account-type');
    const connectBtn = getEl('connect-account-btn');
    const disconnectBtn = getEl('disconnect-account-btn');
    const usernameRow = getEl('username-row');

    if (connectBtn) connectBtn.style.display = 'none';

    if (accountSelect) {
      accountSelect.addEventListener('change', async (e) => {
        const val = e.target.value === 'Histolauncher' ? 'Histolauncher' : 'Local';
        const isConnected = !!settingsState.uuid;

        if (settingsState.account_type === 'Histolauncher' && val === 'Local') {
          histolauncherUsername = settingsState.username;
        }

        if (val === 'Histolauncher') {
          if (isConnected) {
            if (localUsernameModified && histolauncherUsername) {
              settingsState.username = histolauncherUsername;
              if (usernameInput) usernameInput.value = histolauncherUsername;
              localUsernameModified = false;
              updateHomeInfo();
            }
            if (usernameRow) usernameRow.style.display = 'none';
            if (usernameInput) usernameInput.disabled = true;
            settingsState.account_type = 'Histolauncher';
            autoSaveSetting('account_type', 'Histolauncher');
            return;
          }

          const signupLink = '<span style="color:#9ca3af;font-size:12px;margin-left:6px">Don\'t have an account? <a id="msgbox-signup-link" href="#">Sign up here</a></span>';
          showMessageBox({
            title: 'Histolauncher Login',
            message: `Enter your Histolauncher credentials below.` + signupLink,
            inputs: [
              { name: 'username', type: 'text', placeholder: 'Username' },
              { name: 'password', type: 'password', placeholder: 'Password' },
            ],
            buttons: [
              {
                label: 'Login',
                classList: ['primary'],
                onClick: async (vals) => {
                  try {
                    const username = (vals.username || '').trim();
                    const password = (vals.password || '').trim();
                    if (!username || !password) {
                      showMessageBox({ title: 'Error', message: 'Username and password are required.', buttons: [{ label: 'OK' }] });
                      if (accountSelect) accountSelect.value = 'Local';
                      autoSaveSetting('account_type', 'Local');
                      return;
                    }

                    const res = await fetch('https://accounts.histolauncher.workers.dev/api/login', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ username, password }),
                    });
                    let json;
                    try { json = await res.json(); } catch (e) { json = null; }

                    if (res.ok && json && json.success) {
                      settingsState.account_type = 'Histolauncher';
                      settingsState.username = username;
                      if (json.uuid) settingsState.uuid = json.uuid;
                      histolauncherUsername = username;
                      localUsernameModified = false;
                      await api('/api/settings', 'POST', {
                        account_type: 'Histolauncher',
                        username: username,
                        histolauncher_username: username,
                        uuid: json.uuid || ''
                      });
                      await init();
                    } else {
                      showMessageBox({ title: 'Error', message: (json && json.error) || 'Failed to authenticate.', buttons: [{ label: 'OK' }] });
                      if (accountSelect) accountSelect.value = 'Local';
                      autoSaveSetting('account_type', 'Local');
                    }
                  } catch (e) {
                    showMessageBox({ title: 'Error', message: 'Connection failed.', buttons: [{ label: 'OK' }] });
                    if (accountSelect) accountSelect.value = 'Local';
                    autoSaveSetting('account_type', 'Local');
                  }
                },
              },
              {
                label: 'Cancel',
                onClick: () => {
                  if (accountSelect) accountSelect.value = 'Local';
                  autoSaveSetting('account_type', 'Local');
                }
              }
            ],
          });

          setTimeout(() => {
            const a = getEl('msgbox-signup-link');
            if (a) a.addEventListener('click', (ev) => { ev.preventDefault(); window.open('https://histolauncher.pages.dev/signup', '_blank'); });
          }, 50);

          return;
        }

        if (val === 'Local') {
          if (settingsState.account_type === 'Histolauncher') {
            // Confirm disconnection
            showMessageBox({
              title: 'Disconnect Account',
              message: 'Are you sure you want to disconnect your Histolauncher account? You will need to log in again to use it.',
              buttons: [
                {
                  label: 'Disconnect',
                  classList: ['danger'],
                  onClick: async () => {
                    histolauncherUsername = settingsState.username;
                    settingsState.account_type = 'Local';
                    settingsState.uuid = '';
                    if (usernameInput) {
                      usernameInput.disabled = false;
                      usernameInput.value = settingsState.username || '';
                    }
                    if (disconnectBtn) disconnectBtn.style.display = 'none';
                    await api('/api/settings', 'POST', {
                      account_type: 'Local',
                      uuid: ''
                    });
                    await init();
                  }
                },
                {
                  label: 'Cancel',
                  onClick: () => {
                    if (accountSelect) accountSelect.value = 'Histolauncher';
                  }
                }
              ]
            });
            return;
          }
          
          settingsState.account_type = 'Local';
          if (usernameInput) {
            usernameInput.disabled = false;
            usernameInput.value = settingsState.username || '';
          }
          if (disconnectBtn) disconnectBtn.style.display = 'none';
          autoSaveSetting('account_type', 'Local');
          await init();
          return;
        }
      });
    }

    if (disconnectBtn) {
      disconnectBtn.style.display = 'none';
    }

    const proxyInput = getEl('settings-url-proxy');
    if (proxyInput) {
      proxyInput.addEventListener('input', (e) =>
        autoSaveSetting('url_proxy', e.target.value.trim())
      );
    }

    const openDataFolderButton = getEl('open-data-folder-btn');
    if (openDataFolderButton) {
      openDataFolderButton.addEventListener('click', async () => {
        await api('/api/open_data_folder', 'POST');
      });
    }

    const lowDataInput = getEl('settings-low-data');
    if (lowDataInput) {
      lowDataInput.addEventListener('change', async (e) => {
        const val = e.target.checked ? "1" : "0";
        await api('/api/settings', 'POST', { low_data_mode: val });
        await init();
      });
    }
  };

  // ---------------- Shift key tracking (global) ----------------

  const initShiftTracking = () => {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Shift') {
        isShiftDown = true;
      }
    });
    document.addEventListener('keyup', (e) => {
      if (e.key === 'Shift') {
        isShiftDown = false;
      }
    });
  };

  // ---------------- Init ----------------

  const init = async () => {
    const overlay = getEl('loading-overlay');
    const box = getEl('loading-box');

    if (overlay) overlay.classList.remove('hidden');
    if (box) box.classList.remove('hidden');

    const data = await api('/api/initial');

    let localVersion = null;
    let isOutdated = false;

    visibleAvailableCount = AVAILABLE_PAGE_SIZE;

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

    const statusEl = getEl('status');
    if (statusEl) statusEl.textContent = '';

    const warn = getEl('versions-section-warning');
    if (data.manifest_error) {
      const availableSection = getEl('available-section');
      if (availableSection) availableSection.style.display = 'none';

      if (warn) {
        warn.textContent =
          'Unable to fetch downloadable versions, please check your internet connection (or URL Proxy in settings)!';
        warn.classList.remove('hidden');
      }
    } else if (warn) {
      warn.classList.add('hidden');
    }

    const installedFromBackend = Array.isArray(data.installed)
      ? data.installed
      : [];
    const installingFromBackend = Array.isArray(data.installing)
      ? data.installing
      : [];
    const remoteFromBackend = Array.isArray(data.versions)
      ? data.versions
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
      total_size_bytes: v.total_size_bytes || 0,
      _progressOverall: 100,
      _progressText: 'Installed',
      raw: v,
    }));

    const mapKey = (cat, folder) =>
      `${(cat || '').toLowerCase()}/${folder || ''}`;
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

      const k = mapKey(cat, folder);
      let v = versionsMap.get(k);
      const progressText =
        bytesTotal > 0
          ? `${pct}% (${(bytesDone / (1024 * 1024)).toFixed(1)} MB / ${(bytesTotal / (1024 * 1024)).toFixed(1)} MB)`
          : `${pct}%`;

      if (!v) {
        v = {
          display,
          category: cat,
          folder,
          installed: false,
          installing: true,
          is_remote: false,
          source: 'installing',
          image_url: 'assets/images/version_placeholder.png',
          _installKey: encodedKey,
          _progressOverall: pct,
          _progressText: progressText,
        };
        versionsMap.set(k, v);
      } else {
        v.installing = true;
        v._installKey = encodedKey;
        v._progressOverall = pct;
        v._progressText = progressText;
      }

      try {
        startPollingForInstall(encodedKey, v);
      } catch (e) {
        // ignore
      }
    });
    
    remoteFromBackend.forEach((r) => {
      const cat = r.category || 'Release';
      const folder = r.folder;
      const k = mapKey(cat, folder);
      if (!versionsMap.has(k)) {
        versionsMap.set(k, {
          display: r.display || folder,
          category: cat,
          folder,
          installed: false,
          installing: false,
          is_remote: !!r.is_remote,
          source: r.source || 'mojang',
          image_url: r.image_url || null,
          total_size_bytes: r.total_size_bytes,
        });
      }
    });

    const finalList = [];
    for (const v of versionsMap.values()) if (v.installed && !v.installing) finalList.push(v);
    for (const v of versionsMap.values()) if (v.installing) finalList.push(v);
    for (const v of versionsMap.values())
      if (!v.installed && !v.installing) finalList.push(v);

    versionsList = finalList.map((v) => ({ ...v }));

    categoriesList =
      Array.isArray(data.categories) && data.categories.length > 0
        ? data.categories.slice()
        : buildCategoryListFromVersions(versionsList);

    selectedVersion = data.selected_version || null;

    await initSettings(data.settings || {});

    const accountSelect = getEl('settings-account-type');
    const connectBtn = getEl('connect-account-btn');
    const disconnectBtn = getEl('disconnect-account-btn');
    const acctType = settingsState.account_type || 'Local';
    const isConnected = !!settingsState.uuid;
    
    if (accountSelect) accountSelect.value = acctType;
    if (connectBtn) connectBtn.style.display = 'none';
    if (disconnectBtn) disconnectBtn.style.display = 'none';
    
    updateHomeInfo();

    initCategoryFilter();
    renderAllVersionSections();

    if (selectedVersion) {
      const selCard = document.querySelector(
        `.version-card[data-full-id="${selectedVersion}"]`
      );
      $$('.version-card').forEach((c) => c.classList.remove('selected'));
      if (selCard) {
        selCard.classList.add('selected');
        const found = versionsList.find(
          (v) => `${v.category}/${v.folder}` === selectedVersion
        );
        if (found) {
          selectedVersionDisplay = found.display;
          updateHomeInfo();
        }
      } else {
        selectedVersion = null;
        selectedVersionDisplay = null;
        updateHomeInfo();
      }
    } else {
      selectedVersionDisplay = null;
      updateHomeInfo();
    }

    if (overlay) overlay.classList.add('hidden');
    if (box) box.classList.add('hidden');
  };

  // ---------------- Global init ----------------

  document.addEventListener('DOMContentLoaded', () => {
    initShiftTracking();
    initSidebar();
    initLaunchButton();
    initRefreshButton();
    initSettingsInputs();
    init();
  });
})();
