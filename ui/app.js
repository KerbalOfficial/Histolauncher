// ui/app.js

(() => {
  // ---------------- State ----------------

  let selectedVersion = null;
  let selectedVersionDisplay = null;
  let versionsList = [];
  let categoriesList = [];
  let settingsState = { mods_view: 'list' };
      settingsState.mods_view = 'list';
  let javaRuntimes = [];
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

  // Build a styled info-row HTML: icon | Label: Value (parens)
  // Mirrors the tooltip label/value/parens CSS classes used in the hover tooltips.
  const makeInfoRowHTML = (iconSrc, label, value, parens) => {
    const icon = `<img width="16px" height="16px" src="${iconSrc}"/>`;
    const lbl = `<span class="tooltip-label">${label}:</span>`;
    const val = `<span class="tooltip-value">${value}</span>`;
    const par = parens ? ` <span class="tooltip-parens">(${parens})</span>` : '';
    return `${icon} ${lbl} ${val}${par}`;
  };

  const makeInfoRowErrorHTML = (label, value, parens, titleAttr) => {
    const par = parens ? ` <span class="tooltip-parens">(${parens})</span>` : '';
    return `<span class="home-info-error" title="${titleAttr}">⚠ <span class="tooltip-label">${label}:</span> <span class="tooltip-value">${value}</span>${par}</span>`;
  };

  const updateHomeInfo = () => {
    const errors = validateSettings();
    const username = settingsState.username || 'Player';
    const acctType = settingsState.account_type || 'Local';
    
    // Username error message
    let usernameTooltip = '';
    if (errors.username) {
      const len = username.length;
      if (len === 0) {
        usernameTooltip = 'Username cannot be empty';
      } else if (len < 3) {
        usernameTooltip = `Username too short (${len}/3-16 characters)`;
      } else if (len > 16) {
        usernameTooltip = `Username too long (${len}/3-16 characters)`;
      }
    }
    
    // RAM error message
    let ramTooltip = '';
    if (errors.min_ram || errors.max_ram) {
      const minRamStr = (settingsState.min_ram || '').toUpperCase();
      const maxRamStr = (settingsState.max_ram || '').toUpperCase();
      
      if (errors.max_ram) {
        if (!validateRAMFormat(maxRamStr)) {
          ramTooltip = 'Invalid format: use number with optional K, M, G, or T suffix (e.g., 4096M)';
        } else {
          const maxVal = parseRAMValue(maxRamStr);
          if (maxVal < 1) {
            ramTooltip = 'Maximum RAM must be at least 1 byte (value is too low)';
          } else if (minRamStr && validateRAMFormat(minRamStr)) {
            const minVal = parseRAMValue(minRamStr);
            if (minVal > maxVal) {
              ramTooltip = `Maximum RAM must be greater than Minimum RAM (${minRamStr} > ${maxRamStr})`;
            }
          }
        }
      } else if (errors.min_ram) {
        ramTooltip = 'Invalid format: use number with optional K, M, G, or T suffix (e.g., 256M)';
      }
    }

    // Version row
    const versionText = selectedVersionDisplay
      ? makeInfoRowHTML('assets/images/library.png', 'Version', selectedVersionDisplay)
      : makeInfoRowHTML('assets/images/library.png', 'Version', '(none selected)');
    setHTML('info-version', versionText);

    // Account row
    const usernameHTML = errors.username
      ? makeInfoRowErrorHTML('Account', username, acctType, usernameTooltip)
      : makeInfoRowHTML('assets/images/settings.gif', 'Account', username, acctType);
    setHTML('info-username', usernameHTML);

    // RAM row
    const minRam = (settingsState.min_ram || '2048M').toUpperCase();
    const maxRam = (settingsState.max_ram || '4096M').toUpperCase();
    const ramHTML = errors.min_ram || errors.max_ram
      ? makeInfoRowErrorHTML('RAM Limit', `${minRam}B - ${maxRam}B`, null, ramTooltip)
      : makeInfoRowHTML('assets/images/settings.gif', 'RAM Limit', `${minRam}B - ${maxRam}B`);
    setHTML('info-ram', ramHTML);

    // --- Version panel: image + details ---
    const homeVersionImg = getEl('home-version-image');
    const infoCategoryEl = getEl('info-version-category');
    const infoSizeEl = getEl('info-version-size');
    const infoLoadersEl = getEl('info-version-loaders');

    if (selectedVersion) {
      const vData = versionsList.find(
        (v) => `${v.category}/${v.folder}` === selectedVersion
      );

      if (homeVersionImg) {
        const imgSrc = vData
          ? (vData.image_url ||
              (vData.installed
                ? `clients/${vData.category}/${vData.folder}/display.png`
                : 'assets/images/version_placeholder.png'))
          : 'assets/images/version_placeholder.png';
        homeVersionImg.src = imgSrc;
      }

      if (vData) {
        if (infoCategoryEl) {
          infoCategoryEl.innerHTML = makeInfoRowHTML('assets/images/library.png', 'Category', vData.category);
          infoCategoryEl.classList.remove('hidden');
        }

        const sizeBytes = vData.total_size_bytes || (vData.raw && vData.raw.total_size_bytes) || 0;
        const assetsType = (vData.raw && vData.raw.full_assets === false) ? 'Lite' : 'Full';
        if (infoSizeEl) {
          if (sizeBytes > 0) {
            infoSizeEl.innerHTML = makeInfoRowHTML('assets/images/cobblestone.png', 'Size', formatBytes(sizeBytes), assetsType);
          } else {
            infoSizeEl.innerHTML = makeInfoRowHTML('assets/images/cobblestone.png', 'Assets', assetsType);
          }
          infoSizeEl.classList.remove('hidden');
        }

        if (infoLoadersEl) {
          const loaders = (vData.raw && vData.raw.loaders) || null;
          if (loaders) {
            const parts = [];
            (loaders.fabric || []).forEach((l) => parts.push(`Fabric ${l.version}`));
            (loaders.forge || []).forEach((l) => parts.push(`Forge ${l.version}`));
            infoLoadersEl.innerHTML = makeInfoRowHTML(
              'assets/images/anvil_hammer.png',
              'Loaders',
              parts.length > 0 ? parts.join(', ') : 'None'
            );
            infoLoadersEl.classList.remove('hidden');
          } else {
            infoLoadersEl.classList.add('hidden');
          }
        }
      } else {
        if (infoCategoryEl) infoCategoryEl.classList.add('hidden');
        if (infoSizeEl) infoSizeEl.classList.add('hidden');
        if (infoLoadersEl) infoLoadersEl.classList.add('hidden');
      }
    } else {
      if (homeVersionImg) homeVersionImg.src = 'assets/images/version_placeholder.png';
      if (infoCategoryEl) infoCategoryEl.classList.add('hidden');
      if (infoSizeEl) infoSizeEl.classList.add('hidden');
      if (infoLoadersEl) infoLoadersEl.classList.add('hidden');
    }

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
        const textureUrl = `https://textures.histolauncher.workers.dev/head/${settingsState.uuid}`;
        topbarProfilePic.src = textureUrl;
        imageAttachErrorPlaceholder(topbarProfilePic, '/assets/images/unknown.png');
      }
    } else {
      if (topbarProfile) topbarProfile.style.display = 'none';
    }
  };

  const initSettings = async (data) => {
    settingsState = { ...settingsState, ...data };

    if (!settingsState.mods_view) {
      settingsState.mods_view = 'list';
    }

    settingsState.favorite_versions = normalizeFavoriteVersions(
      settingsState.favorite_versions
    );

    if (settingsState.account_type === 'Histolauncher') {
      try {
        const currentUser = await api('/api/account/current', 'GET');
        if (currentUser.ok && currentUser.authenticated) {
          settingsState.username = currentUser.username;
          settingsState.uuid = currentUser.uuid;
          histolauncherUsername = currentUser.username;
        } else {
          const unauthorized = !!currentUser.unauthorized;
          if (unauthorized) {
            console.warn('[Account] Session verification failed (unauthorized):', currentUser.error);
            settingsState.account_type = 'Local';
            settingsState.username = data.username || 'Player';
            settingsState.uuid = null;
            autoSaveSetting('account_type', 'Local');
          } else {
            console.warn('[Account] Unable to verify session (network issue?), keeping existing login:', currentUser.error);
            settingsState.username = data.username || 'Player';
          }
        }
      } catch (e) {
        console.warn('[Account] Error verifying session:', e);
        settingsState.username = data.username || 'Player';
      }
    } else {
      settingsState.username = data.username || 'Player';
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
    }

    const minRamInput = getEl('settings-min-ram');
    if (minRamInput) minRamInput.value = settingsState.min_ram || '32M';

    const maxRamInput = getEl('settings-max-ram');
    if (maxRamInput) maxRamInput.value = settingsState.max_ram || '4096M';

    const extraJvmInput = getEl('settings-extra-jvm-args');
    if (extraJvmInput) extraJvmInput.value = settingsState.extra_jvm_args || '';

    const storageSelect = getEl('settings-storage-dir');
    if (storageSelect) {
      storageSelect.value = (settingsState.storage_directory || 'global') === 'version' ? 'version' : 'global';
    }

    const proxyEl = getEl('settings-url-proxy');
    if (proxyEl) proxyEl.value = settingsState.url_proxy || '';

    const lowDataEl = getEl('settings-low-data');
    if (lowDataEl) lowDataEl.checked = settingsState.low_data_mode === "1";

    const fastDownloadEl = getEl('settings-fast-download');
    if (fastDownloadEl) fastDownloadEl.checked = settingsState.fast_download === "1";

    const accountSelect = getEl('settings-account-type');
    const connectBtn = getEl('connect-account-btn');
    const disconnectBtn = getEl('disconnect-account-btn');
    const acctType = settingsState.account_type || 'Local';
    const isConnected = !!settingsState.uuid;
    
    if (accountSelect) accountSelect.value = acctType;
    if (connectBtn) connectBtn.style.display = 'none';
    if (disconnectBtn) disconnectBtn.style.display = 'none';

    await refreshJavaRuntimeOptions(false);

    updateHomeInfo();
    updateSettingsValidationUI();
    applyVersionsViewMode();
    applyModsViewMode();
  };

  const refreshJavaRuntimeOptions = async (force = false) => {
    const select = getEl('settings-java-runtime');
    if (!select) return;

    const endpoint = force ? '/api/java-runtimes-refresh' : '/api/java-runtimes';
    const res = await api(endpoint, 'GET');
    if (!res || !res.ok) {
      return;
    }

    javaRuntimes = Array.isArray(res.runtimes) ? res.runtimes : [];

    select.innerHTML = '';
    const autoOpt = document.createElement('option');
    autoOpt.value = '';
    autoOpt.textContent = 'Auto (default Java from PATH)';
    select.appendChild(autoOpt);

    javaRuntimes.forEach((rt) => {
      const opt = document.createElement('option');
      opt.value = rt.path || '';
      opt.textContent = rt.display || rt.path || 'Java runtime';
      select.appendChild(opt);
    });

    const selectedPath = (settingsState.java_path || res.selected_java_path || '').trim();
    select.value = selectedPath;

    if (selectedPath && !javaRuntimes.some((rt) => rt.path === selectedPath)) {
      const missingOpt = document.createElement('option');
      missingOpt.value = selectedPath;
      missingOpt.textContent = `[Missing] ${selectedPath}`;
      select.appendChild(missingOpt);
      select.value = selectedPath;
    }
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

    if (category) list = list.filter((v) => v.category === category);

    if (q) {
      list = list.filter((v) => {
        const hay = `${v.display} ${v.folder} ${v.category}`.toLowerCase();
        return hay.includes(q);
      });
    }

    const installed = list.filter((v) => v.installed && !v.installing);
    const installing = list.filter((v) => v.installing);
    // Transient modloader entries are only for in-progress cards and should
    // never appear in the Available list.
    const available = list.filter(
      (v) => !v.installed && !v.installing && v.source !== 'modloader'
    );

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

  const showMessageBox = ({ title = '', message = '', buttons = [], inputs = [], customContent = null, description = '' }) => {
    const overlay = getEl('msgbox-overlay');
    const boxTitle = getEl('msgbox-title');
    const boxText = getEl('msgbox-text');
    const btnContainer = getEl('msgbox-buttons');

    if (!overlay || !boxTitle || !btnContainer) return;

    boxTitle.textContent = title;
    
    // Handle custom content or regular message
    boxText.innerHTML = '';
    
    if (customContent && customContent instanceof Node) {
      // If custom content is provided, use it instead of message text
      boxText.appendChild(customContent);
    } else if (typeof message === 'string' && message) {
      boxText.innerHTML = message;
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
          // Drop transient modloader install cards entirely after cancel.
          if (x.source === 'modloader') return null;
          return {
            ...x,
            installing: false,
            _installKey: null,
            _progressText: 'Cancelled',
            _progressOverall: 0,
          };
        }
        return x;
      }).filter(Boolean);

      if (activeInstallPollers[versionKeyEncoded]) {
        clearTimeout(activeInstallPollers[versionKeyEncoded]);
        delete activeInstallPollers[versionKeyEncoded];
      }

      // Rehydrate from backend so cards move to correct sections immediately.
      await init();
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

  const findVersionByInstallKey = (versionKeyEncoded) => {
    return versionsList.find((x) => {
      const matchesKey =
        (x._installKey && x._installKey === versionKeyEncoded) ||
        `${x.category}/${x.folder}` === decodeURIComponent(versionKeyEncoded);
      return matchesKey;
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

    let unknownCount = 0;
    let hadProgress = false;

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
        
        // Safety mechanism: if we had progress but now getting unknown repeatedly, stop polling
        if (status === 'unknown') {
          if (hadProgress) {
            unknownCount++;
            // After 10 consecutive unknown responses, assume installation is done and stop polling
            if (unknownCount >= 10) {
              console.log('[poll] Installation likely complete (too many unknown responses)');
              clearTimeout(activeInstallPollers[versionKeyEncoded]);
              delete activeInstallPollers[versionKeyEncoded];
              await init();
              return;
            }
          }
          activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 200);
          return;
        }
        
        // Reset unknown counter when we get valid status
        unknownCount = 0;
        if (status === 'downloading' || status === 'starting') {
          hadProgress = true;
        }

        const pct = s.overall_percent || 0;
        const bytesDone = s.bytes_done || 0;
        const bytesTotal = s.bytes_total || 0;

        const mbDone = bytesDone / (1024 * 1024);
        const mbTotal = bytesTotal / (1024 * 1024);

        let text = '';
        let keepPolling = true;
        
        // Look up the current version from versionsList to avoid stale references after page refresh
        const currentVMeta = findVersionByInstallKey(versionKeyEncoded);
        if (!currentVMeta) {
          // Version not found - might have been removed, stop polling
          clearTimeout(activeInstallPollers[versionKeyEncoded]);
          delete activeInstallPollers[versionKeyEncoded];
          return;
        }

        if (status === 'downloading' || status === 'starting') {
          currentVMeta.paused = false;
          text =
            bytesTotal > 0
              ? `${pct}% (${mbDone.toFixed(1)} MB / ${mbTotal.toFixed(1)} MB)`
              : bytesDone > 0
              ? `${pct}% (${mbDone.toFixed(1)} MB)`
              : `${pct}%`;

          updateVersionInListByKey(versionKeyEncoded, (x) => ({
            ...x,
            paused: false,
            _progressText: text,
            _progressOverall: pct,
          }));

          updateCardProgressUI(currentVMeta, pct, text, {
            paused: false,
            statusLabel: 'Installing',
            keepInstalling: true,
          });
          
          // Schedule next poll and return to avoid the generic updateCardProgressUI call below
          activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 200);
          return;
        } else if (status === 'installed') {
          text = 'Installed';
          keepPolling = false;

          const isImported = currentVMeta.raw?.is_imported === true;
          updateVersionInListByKey(versionKeyEncoded, (x) => ({
            ...x,
            installed: true,
            installing: false,
            _installKey: null,
            _progressOverall: 100,
            _progressText: isImported ? 'Imported' : 'Installed',
          }));

          renderAllVersionSections();

          try {
            const fresh = await api('/api/initial');
            const backendInstalled = Array.isArray(fresh.installed)
              ? fresh.installed
              : [];

            versionsList = versionsList.filter((v) => !v.installed);

            backendInstalled.forEach((b) => {
              const isImported = b.is_imported === true;
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
                _progressText: isImported ? 'Imported' : 'Installed',
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
          
          // Refresh backend data to update the list
          try {
            const fresh = await api('/api/initial');
            const backendInstalled = Array.isArray(fresh.installed) ? fresh.installed : [];
            const backendInstalling = Array.isArray(fresh.installing) ? fresh.installing : [];
            const backendRemote = Array.isArray(fresh.versions) ? fresh.versions : [];
            
            versionsList = versionsList.filter((v) => !v.installed && !v.installing);
            
            backendInstalled.forEach((b) => {
              const isImported = b.is_imported === true;
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
                _progressText: isImported ? 'Imported' : 'Installed',
                raw: b,
              });
            });
            
            backendRemote.forEach((r) => {
              if (!versionsList.find((v) => v.category === r.category && v.folder === r.folder)) {
                versionsList.push({
                  display: r.display || r.folder,
                  category: r.category || 'Release',
                  folder: r.folder,
                  installed: false,
                  installing: false,
                  is_remote: !!r.is_remote,
                  source: r.source || 'mojang',
                  image_url: r.image_url || null,
                  total_size_bytes: r.total_size_bytes,
                });
              }
            });
            
            categoriesList = Array.isArray(fresh.categories) && fresh.categories.length > 0
              ? fresh.categories.slice()
              : buildCategoryListFromVersions(versionsList);
            
            initCategoryFilter();
            renderAllVersionSections();
          } catch (e) {
            renderAllVersionSections();
          }
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
          
          // Refresh backend data to update the list
          try {
            const fresh = await api('/api/initial');
            const backendInstalled = Array.isArray(fresh.installed) ? fresh.installed : [];
            const backendInstalling = Array.isArray(fresh.installing) ? fresh.installing : [];
            const backendRemote = Array.isArray(fresh.versions) ? fresh.versions : [];
            
            versionsList = versionsList.filter((v) => !v.installed && !v.installing);
            
            backendInstalled.forEach((b) => {
              const isImported = b.is_imported === true;
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
                _progressText: isImported ? 'IMPORTED' : 'Installed',
                raw: b,
              });
            });
            
            backendRemote.forEach((r) => {
              if (!versionsList.find((v) => v.category === r.category && v.folder === r.folder)) {
                versionsList.push({
                  display: r.display || r.folder,
                  category: r.category || 'Release',
                  folder: r.folder,
                  installed: false,
                  installing: false,
                  is_remote: !!r.is_remote,
                  source: r.source || 'mojang',
                  image_url: r.image_url || null,
                  total_size_bytes: r.total_size_bytes,
                });
              }
            });
            
            categoriesList = Array.isArray(fresh.categories) && fresh.categories.length > 0
              ? fresh.categories.slice()
              : buildCategoryListFromVersions(versionsList);
            
            initCategoryFilter();
            renderAllVersionSections();
          } catch (e) {
            renderAllVersionSections();
          }
        } else if (status === 'paused') {
          text = 'Paused';

          updateVersionInListByKey(versionKeyEncoded, (x) => ({
            ...x,
            paused: true,
            _progressText: 'Paused',
            _progressOverall: pct,
          }));

          updateCardProgressUI(currentVMeta, pct, 'Paused', {
            paused: true,
            statusLabel: 'PAUSED',
            pausedColor: '#facc15',
            keepInstalling: true,
          });

          keepPolling = true;
          activeInstallPollers[versionKeyEncoded] = setTimeout(poll, 600);
          return;
        }

        updateCardProgressUI(currentVMeta, pct, text, {
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

  // ============ MOD LOADER UI ============

  const createAddLoaderButton = (v) => {
    const loaderBtn = document.createElement('div');
    loaderBtn.className = 'icon-button';

    const loaderImg = document.createElement('img');
    loaderImg.alt = 'add loader';
    loaderImg.src = 'assets/images/unfilled_plus.png';
    imageAttachErrorPlaceholder(loaderImg, 'assets/images/placeholder.png');
    loaderBtn.appendChild(loaderImg);

    loaderBtn.addEventListener('mouseenter', () => {
      loaderImg.src = 'assets/images/filled_plus.png';
    });
    loaderBtn.addEventListener('mouseleave', () => {
      loaderImg.src = 'assets/images/unfilled_plus.png';
    });

    loaderBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      showLoaderManagementModal(v);
    });

    return loaderBtn;
  };

  const showLoaderManagementModal = async (v) => {
    // Fetch available and installed loaders
    try {
      const loaderData = await api(`/api/loaders/${v.category.toLowerCase()}/${v.folder}`);
      if (!loaderData || !loaderData.ok) {
        showMessageBox({
          title: 'Error',
          message: 'Failed to load loaders information.',
          buttons: [{ label: 'OK' }],
        });
        return;
      }

      const installed = loaderData.installed || {};
      const available = loaderData.available || {};

      // Create enhanced UI with loader cards
      let html = `
        <div style="max-height: 500px; overflow-y: auto; padding: 10px;">
          <div style="margin-bottom: 20px;">
            <h4 style="color: #fff; margin-top: 0; margin-bottom: 10px; text-transform: uppercase; font-size: 12px; letter-spacing: 1px;">
              ✓ Installed Loaders
            </h4>
            <div style="display: grid; gap: 8px;" id="installed-loaders-container">
      `;

      const hasFabric = Array.isArray(installed.fabric) && installed.fabric.length > 0;
      const hasForge = Array.isArray(installed.forge) && installed.forge.length > 0;
      
      if (!hasFabric && !hasForge) {
        html += `<p style="color:#999;font-size:12px;font-style:italic;">No loaders installed</p>`;
      } else {
        // Display installed Fabric loaders
        if (installed.fabric?.length) {
          installed.fabric.forEach((loader, idx) => {
            html += `
              <div style="background:#2a2a2a;border-left:3px solid #bebb88;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;">
                <div>
                  <strong style="color:#bebb88;">Fabric</strong>
                  <span style="color:#aaa; font-size: 12px;"> ${loader.version}</span>
                  <span style="color:#666; font-size: 11px;"> - ${loader.size_display || 'Unknown size'}</span>
                </div>
                <div class="loader-delete-btn" style="width: 24px; height: 24px; cursor: pointer; background: transparent; border: none; padding: 0; display: flex; align-items: center; justify-content: center;" data-loader-type="fabric" data-loader-version="${loader.version}">
                  <img src="assets/images/unfilled_delete.png" alt="delete" style="width: 100%; height: 100%;">
                </div>
              </div>
            `;
          });
        }
        
        // Display installed Forge loaders
        if (installed.forge?.length) {
          installed.forge.forEach((loader, idx) => {
            html += `
              <div style="background:#2a2a2a;border-left:3px solid #646ec9;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;">
                <div>
                  <strong style="color:#646ec9;">Forge</strong>
                  <span style="color:#aaa; font-size: 12px;"> ${loader.version}</span>
                  <span style="color:#666; font-size: 11px;"> - ${loader.size_display || 'Unknown size'}</span>
                </div>
                <div class="loader-delete-btn" style="width: 24px; height: 24px; cursor: pointer; background: transparent; border: none; padding: 0; display: flex; align-items: center; justify-content: center;" data-loader-type="forge" data-loader-version="${loader.version}">
                  <img src="assets/images/unfilled_delete.png" alt="delete" style="width: 100%; height: 100%;">
                </div>
              </div>
            `;
          });
        }
      }

      html += `
            </div>
          </div>

          <div>
            <h4 style="color: #fff; margin-top: 0; margin-bottom: 10px; text-transform: uppercase; font-size: 12px; letter-spacing: 1px;">
              + Add New Loader
            </h4>
            <div style="display:grid;gap:8px;">
              <button class="fabric" data-action="install-fabric">
                <div style="font-size:15px;font-weight:bold;margin-bottom:4px;">Fabric</div>
                <div style="font-size:9px;opacity:75%;"><b>Lightweight & fast</b><br><i>Mostly used for game optimization</i></div>
              </button>

              <!-- Forge Card -->
              <button class="forge" data-action="install-forge">
                <div style="font-size:15px;font-weight:bold;margin-bottom:4px;">Forge</div>
                <div style="font-size:9px;opacity:75%;"><b>Full-modifications & popular</b><br><i>Mostly used for game modifications</i></div>
              </button>
            </div>
          </div>
        </div>
      `;

      showMessageBox({
        title: `Mod Loaders - ${v.display}`,
        message: html,
        buttons: [{ label: 'Close' }],
      });

      // Add click handlers after modal is shown
      setTimeout(() => {
        // Add delete button handlers
        const deleteButtons = document.querySelectorAll('.loader-delete-btn');
        deleteButtons.forEach(btn => {
          const loaderType = btn.getAttribute('data-loader-type');
          const loaderVersion = btn.getAttribute('data-loader-version');
          const imgEl = btn.querySelector('img');
          
          btn.addEventListener('mouseenter', () => {
            imgEl.src = 'assets/images/filled_delete.png';
          });
          btn.addEventListener('mouseleave', () => {
            imgEl.src = 'assets/images/unfilled_delete.png';
          });
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteLoaderVersion(v, loaderType, loaderVersion);
          });
        });
        
        const fabricCard = document.querySelector('[data-action="install-fabric"]');
        const forgeCard = document.querySelector('[data-action="install-forge"]');
        
        if (fabricCard) {
          fabricCard.addEventListener('click', (e) => {
            e.preventDefault();
            showLoaderVersionSelector(v, 'fabric');
          });
        }
        if (forgeCard) {
          forgeCard.addEventListener('click', (e) => {
            e.preventDefault();
            showLoaderVersionSelector(v, 'forge');
          });
        }
      }, 100);
    } catch (err) {
      console.error('Failed to fetch loaders:', err);
      showMessageBox({
        title: 'Error',
        message: 'Failed to load loaders information.',
        buttons: [{ label: 'OK' }],
      });
    }
  };

  const showLoaderVersionSelector = async (v, loaderType) => {
    try {
      const loaderData = await api(`/api/loaders/${v.category.toLowerCase()}/${v.folder}`);
      if (!loaderData || !loaderData.ok) {
        showMessageBox({
          title: 'Error',
          message: `Failed to fetch available ${loaderType} versions.`,
          buttons: [{ label: 'OK' }],
        });
        return;
      }

      const available = loaderData.available || {};
      const allVersions = available[loaderType] || [];
      const totalAvailable = (loaderData.total_available || {})[loaderType] || allVersions.length;

      if (!allVersions || allVersions.length === 0) {
        showMessageBox({
          title: `Install ${loaderType.charAt(0).toUpperCase() + loaderType.slice(1)}`,
          message: `No ${loaderType} versions available for ${v.display}.`,
          buttons: [{ label: 'OK' }],
        });
        return;
      }

      // Pagination state
      let displayedCount = 15;

      const renderVersionList = (versions) => {
        let html = `<div style="display: grid; gap: 8px; max-height: 400px; overflow-y: auto; padding: 10px 0;">`;
        
        versions.forEach((ver, idx) => {
          const isRecommended = idx === 0;
          const btnClass = isRecommended ? 'primary' : 'default';
          html += `
            <button class="version-btn ${btnClass}" 
              data-version="${ver.version}"
              style="
                text-align: left;
                padding: 10px 12px;
                border: 1px solid #666;
                background: #2a2a2a;
                color: #ccc;
                cursor: pointer;
                font-size: 13px;
              ">
              <div style="font-weight: bold;">${ver.version}${isRecommended ? ' (Recommended)' : ''}</div>
            </button>
          `;
        });

        html += '</div>';
        return html;
      };

      const buildMessage = () => {
        const displayedVersions = allVersions.slice(0, displayedCount);
        const hasMore = displayedCount < totalAvailable;
        
        let msg = `
          <div style="font-family: Arial, sans-serif;">
            <p style="margin-top: 0; color: #aaa; font-size: 12px; margin-bottom: 12px;">
              Select a ${loaderType} version for <strong>${v.display}</strong>
            </p>
            ${renderVersionList(displayedVersions)}
            <p style="margin-top: 8px; margin-bottom: 8px; color: #666; font-size: 11px;">
              Showing ${displayedVersions.length} of ${totalAvailable} versions
            </p>
        `;
        
        if (hasMore) {
          msg += `<button id="load-more-btn" class="default" style="width: 100%; padding: 8px; margin-top: 4px;">Load More...</button>`;
        }
        
        msg += `</div>`;
        return msg;
      };

      const versionButtons = [
        {
          label: `Install ${allVersions[0]?.version || 'Latest'}`,
          classList: ['primary'],
          onClick: () => installLoaderVersion(v, loaderType, allVersions[0].version),
        },
        { label: 'Cancel' },
      ];

      const title = loaderType === 'fabric' 
        ? 'Install Fabric - Select Version'
        : 'Install Forge - Select Version';

      showMessageBox({
        title: title,
        message: buildMessage(),
        buttons: versionButtons,
      });

      const attachHandlers = () => {
        const versionBtns = document.querySelectorAll('.version-btn');
        versionBtns.forEach(btn => {
          btn.addEventListener('click', () => {
            const ver = btn.getAttribute('data-version');
            installLoaderVersion(v, loaderType, ver);
          });
        });

        const loadMoreBtn = document.getElementById('load-more-btn');
        if (loadMoreBtn) {
          loadMoreBtn.addEventListener('click', () => {
            displayedCount += 15;
            const msgboxText = document.getElementById('msgbox-text');
            if (msgboxText) {
              msgboxText.innerHTML = buildMessage();
              attachHandlers();
            }
          });
        }
      };

      setTimeout(() => {
        attachHandlers();
      }, 100);

    } catch (err) {
      console.error(`Failed to fetch ${loaderType} versions:`, err);
      showMessageBox({
        title: 'Error',
        message: `Failed to fetch available ${loaderType} versions.`,
        buttons: [{ label: 'OK' }],
      });
    }
  };

  const installLoaderVersion = async (v, loaderType, loaderVersion) => {
    const loaderName = loaderType === 'fabric' ? 'Fabric' : 'Forge';
    const fullId = `${v.category}/${v.folder}`;
    
    const msgboxOverlay = getEl('msgbox-overlay');
    if (msgboxOverlay) msgboxOverlay.classList.add('hidden');
    
    const modloaderVersionKey = `${v.category.toLowerCase()}/${v.folder}/modloader-${loaderType}-${loaderVersion}`;
    const installKey = encodeURIComponent(modloaderVersionKey);
    
    const modloaderEntry = {
      display: `${loaderName} ${loaderVersion}`,
      category: `${v.category}/${v.folder}`,
      folder: `${v.folder}/${loaderType}-${loaderVersion}`,
      installed: false,
      installing: true,
      is_remote: false,
      source: 'modloader',
      image_url: `assets/images/modloader-${loaderType}-versioncard.png`,
      _installKey: installKey,
      _progressText: 'Starting...',
      _progressOverall: 0,
      _loaderType: loaderType,
      _loaderVersion: loaderVersion,
      _parentVersion: fullId,
    };
    
    // Add to versionsList if not already there
    if (!versionsList.find(x => x._installKey === installKey)) {
      versionsList.push(modloaderEntry);
    }
    
    // Force render to show the modloader in Installing section
    renderAllVersionSections();
    
    try {
      // Make API call to install loader (non-blocking, returns immediately)
      const installResult = await api('/api/install-loader', 'POST', {
        category: v.category,
        folder: v.folder,
        loader_type: loaderType,
        loader_version: loaderVersion,
      });

      if (installResult && installResult.ok) {
        const installKeyForTracking = installResult.install_key || modloaderVersionKey;
        const encodedInstallKey = encodeURIComponent(installKeyForTracking);
        
        // Update the modloader entry with the correct install key for progress polling
        versionsList = versionsList.map(x =>
          x._installKey === installKey ? { ...x, _installKey: encodedInstallKey } : x
        );
        
        // Re-render so pause/cancel buttons are created with the correct install key
        renderAllVersionSections();
        
        // Start polling for progress (same pattern as version downloads)
        const pollModloaderProgress = async () => {
          const vMeta = findVersionByInstallKey(encodedInstallKey);
          if (!vMeta) return;

          let unknownCount = vMeta._unknownCount || 0;

          try {
            const s = await api(`/api/status/${encodedInstallKey}`);
            
            if (!s || s.status === 'unknown') {
              unknownCount += 1;
              updateVersionInListByKey(encodedInstallKey, (x) => ({
                ...x,
                _unknownCount: unknownCount,
              }));

              if (unknownCount >= 10) {
                delete activeInstallPollers[encodedInstallKey];
                await init();
                return;
              }

              activeInstallPollers[encodedInstallKey] = setTimeout(pollModloaderProgress, 200);
              return;
            }

            // Reset unknown counter once status is valid
            updateVersionInListByKey(encodedInstallKey, (x) => ({
              ...x,
              _unknownCount: 0,
            }));

            const pct = s.overall_percent || 0;
            const status = s.status;
            let keepPolling = true;

            if (status === 'downloading' || status === 'installing' || status === 'starting') {
              vMeta.paused = false;
              const bytesDone = s.bytes_done || 0;
              const bytesTotal = s.bytes_total || 0;
              let text = '';

              if (bytesTotal > 0) {
                const mbDone = (bytesDone / (1024 * 1024)).toFixed(1);
                const mbTotal = (bytesTotal / (1024 * 1024)).toFixed(1);
                text = `${pct}% (${mbDone} MB / ${mbTotal} MB)`;
              } else {
                text = `${pct}%`;
              }

              updateVersionInListByKey(encodedInstallKey, (x) => ({
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
            } else if (status === 'paused') {
              vMeta.paused = true;
              const text = `${pct}% (paused)`;

              updateVersionInListByKey(encodedInstallKey, (x) => ({
                ...x,
                paused: true,
                _progressText: text,
                _progressOverall: pct,
              }));

              updateCardProgressUI(vMeta, pct, text, {
                paused: true,
                statusLabel: 'PAUSED',
                keepInstalling: true,
              });
            } else if (status === 'installed' || pct >= 100) {
              keepPolling = false;

              // Remove transient entry and pull fresh backend state so cards
              // move to the correct sections (installed/available).
              versionsList = versionsList.filter((x) => x._installKey !== encodedInstallKey);
              await init();
            } else if (status === 'failed' || status === 'error') {
              const errorMsg = s.message || 'Unknown error';
              keepPolling = false;

              versionsList = versionsList.filter((x) => x._installKey !== encodedInstallKey);
              await init();
              showMessageBox({
                title: `${loaderName} Install Failed`,
                message: errorMsg,
                buttons: [{ label: 'OK' }],
              });
            } else if (status === 'cancelled') {
              keepPolling = false;
              versionsList = versionsList.filter((x) => x._installKey !== encodedInstallKey);
              await init();
            }

            if (keepPolling) {
              activeInstallPollers[encodedInstallKey] = setTimeout(pollModloaderProgress, 200);
            } else {
              delete activeInstallPollers[encodedInstallKey];
            }
          } catch (e) {
            activeInstallPollers[encodedInstallKey] = setTimeout(pollModloaderProgress, 2000);
          }
        };

        // Start polling for modloader progress
        pollModloaderProgress();
      } else {
        const errorMsg = installResult?.error || 'Unknown error';
        
        // Mark as failed in the list
        versionsList = versionsList.map(x =>
          x._installKey === installKey ? { ...x, installing: false, _progressText: `Failed: ${errorMsg}` } : x
        );
        renderAllVersionSections();
      }
    } catch (err) {
      console.error(`Loader installation error:`, err);
      
      // Mark as failed in the list
      versionsList = versionsList.map(x =>
        x._installKey === installKey ? { ...x, installing: false, _progressText: `Failed: ${err.message}` } : x
      );
      renderAllVersionSections();
    }
  };

  const deleteLoaderVersion = (v, loaderType, loaderVersion) => {
    const loaderName = loaderType === 'fabric' ? 'Fabric' : 'Forge';
    
    // Show confirmation dialog
    showMessageBox({
      title: 'Delete Loader',
      message: `Are you sure you want to delete ${loaderName} ${loaderVersion}?`,
      buttons: [
        { label: 'Cancel' },
        { 
          label: 'Delete', 
          classList: ['danger'],
          onClick: async () => {
            try {
              const deleteResult = await api('/api/delete-loader', 'POST', {
                category: v.category,
                folder: v.folder,
                loader_type: loaderType,
                loader_version: loaderVersion,
              });

              if (deleteResult && deleteResult.ok) {
                setTimeout(() => {
                  showLoaderManagementModal(v);
                }, 500);
              } else {
                const errorMsg = deleteResult?.error || 'Unknown error';
              }
            } catch (err) {
              console.error(`Loader deletion error:`, err);
            }
          }
        }
      ],
    });
  };

  const createBadgeRow = (v, sectionType) => {
    const badgeRow = document.createElement('div');
    badgeRow.className = 'version-badge-row';

    const badgeMain = document.createElement('span');
    badgeMain.className =
        'version-badge ' +
        (sectionType === 'installed'
            ? (v.raw && v.raw.is_imported === true ? 'imported' : 'installed')
            : 'available');

    if (sectionType === 'installing' && v.paused) {
        badgeMain.textContent = 'PAUSED';
        badgeMain.classList.add('paused');
    } else {
        badgeMain.textContent =
            sectionType === 'installed'
                ? (v.raw && v.raw.is_imported === true ? 'IMPORTED' : 'INSTALLED')
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
          // Resuming
          await resumeInstallForVersionKey(v._installKey);
          // Update UI immediately
          updateVersionInListByKey(v._installKey, (x) => ({
            ...x,
            paused: false,
            _progressText: 'Resuming...',
          }));
          renderAllVersionSections();
        } else {
          // Pausing
          await pauseInstallForVersionKey(v._installKey);
          // Update UI immediately
          updateVersionInListByKey(v._installKey, (x) => ({
            ...x,
            paused: true,
            _progressText: 'Paused',
          }));
          renderAllVersionSections();
        }
        // Trigger immediate poll after pause/resume
        setTimeout(() => {
          const vMeta = findVersionByInstallKey(v._installKey);
          if (vMeta) {
            // Delete old poller completely before restarting
            if (activeInstallPollers[v._installKey]) {
              clearTimeout(activeInstallPollers[v._installKey]);
              delete activeInstallPollers[v._installKey];
            }
            // Re-run polling immediately
            startPollingForInstall(v._installKey, vMeta);
          }
        }, 100);
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
              // Trigger immediate poll after cancel
              setTimeout(() => {
                const vMeta = findVersionByInstallKey(v._installKey);
                if (vMeta) {
                  renderAllVersionSections();
                }
              }, 100);
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

    const progressText = document.createElement('div');
    progressText.className = 'version-progress-text';
    progressText.textContent = v._progressText || '';
    card.appendChild(progressBar);
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
    card.classList.add(`section-${sectionType}`);
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
      iconsRow.appendChild(createAddLoaderButton(v));
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

    card.appendChild(img);
    card.appendChild(info);
    card.appendChild(badgeRow);
    card.appendChild(actions);
    if (sectionType === 'installing') {
      createProgressElements(card, v);
    }

    return card;
  };

  // ---------------- View Toggle (Grid/List) ----------------

  const applyVersionsViewMode = () => {
    const viewMode = settingsState.versions_view || 'grid';
    const containers = [
      getEl('installed-versions'),
      getEl('installing-versions'),
      getEl('available-versions')
    ];
    
    containers.forEach((container) => {
      if (container) {
        if (viewMode === 'list') {
          container.classList.add('list-view');
        } else {
          container.classList.remove('list-view');
        }
      }
    });

    const gridBtn = getEl('view-grid-btn');
    const listBtn = getEl('view-list-btn');
    if (gridBtn && listBtn) {
      gridBtn.classList.toggle('active', viewMode === 'grid');
      listBtn.classList.toggle('active', viewMode === 'list');
    }
  };

  const initVersionsViewToggle = () => {
    const gridBtn = getEl('view-grid-btn');
    const listBtn = getEl('view-list-btn');

    if (gridBtn) {
      gridBtn.addEventListener('click', () => {
        if (settingsState.versions_view !== 'grid') {
          settingsState.versions_view = 'grid';
          applyVersionsViewMode();
          autoSaveSetting('versions_view', 'grid');
        }
      });
    }

    if (listBtn) {
      listBtn.addEventListener('click', () => {
        if (settingsState.versions_view !== 'list') {
          settingsState.versions_view = 'list';
          applyVersionsViewMode();
          autoSaveSetting('versions_view', 'list');
        }
      });
    }

    applyVersionsViewMode();
  };

  const initCollapsibleSections = () => {
    $$('.collapsible-section').forEach((section) => {
      const toggle = section.querySelector('.section-dropdown-toggle');
      const body = section.querySelector('.section-dropdown-body');
      const triggers = Array.from(section.querySelectorAll('.section-dropdown-trigger'));

      if (!toggle || !body || toggle.dataset.dropdownBound === '1') {
        return;
      }

      const setExpanded = (expanded) => {
        section.classList.toggle('collapsed', !expanded);
        toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        const indicator = toggle.querySelector('.section-dropdown-indicator');
        if (indicator) {
          indicator.textContent = expanded ? '⏷' : '⏶';
        }
        body.classList.toggle('hidden', !expanded);
      };

      const handleToggle = () => {
        const expanded = toggle.getAttribute('aria-expanded') !== 'false';
        setExpanded(!expanded);
      };

      triggers.forEach((trigger) => {
        trigger.addEventListener('click', handleToggle);
      });
      toggle.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          handleToggle();
        }
      });

      toggle.dataset.dropdownBound = '1';
      setExpanded(true);
    });
  };

  const handleExportVersions = async () => {
    // Check if a version is selected
    if (!selectedVersion) {
      showMessageBox({ title: 'Export Error', message: 'Please select a version to export first!', buttons: [{ label: 'OK' }] });
      return;
    }
    
    try {
      // Parse selectedVersion (format: "Category/folder")
      const [category, folder] = selectedVersion.split('/');
      
      if (!category || !folder) {
        showMessageBox({ title: 'Export Error', message: 'Invalid version selection', buttons: [{ label: 'OK' }] });
        return;
      }
      
      // Show export options dialog
      const exportOptions = {
        include_loaders: true,
        include_assets: true,
        include_config: false,
        compression: 'standard'
      };
      
      await new Promise((resolve) => {
        const optionsHTML = `
          <div style="display: flex; flex-direction: column; gap: 16px; max-width: 400px;">
            <div style="color: #aaa; font-size: 14px;">
              Exporting <b>${category}/${folder}</b>
            </div>
            
            <div class="row" style="display:grid;gap:8px;max-height:300px;overflow-y:auto;padding:8px 0;">
              <div style="color:#fff;font-size:12px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Include Options</div>
              <br>
              
              <label>
                <input type="checkbox" id="export-loaders" checked style="cursor:pointer;">
                <span>Include installed Mod Loaders</span>
              </label>
              <br>
              
              <label>
                <input type="checkbox" id="export-assets" checked style="cursor:pointer;">
                <span>Include assets</span>
              </label>
              <br>
              
              <label>
                <input type="checkbox" id="export-config" style="cursor:pointer;">
                <span>Local version configuration & saves</span>
              </label>
            </div>
            
            <div style="border-top:1px solid #333;padding-top:12px;">
              <div style="color:#fff;font-size:12px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Compression Level</div>
              
              <select id="export-compression" style="width:90%;padding:6px;background:#1a1a1a;color:#fff;border:1px solid #333;">
                <option value="quick">Fast</option>
                <option value="standard" selected>Regular</option>
                <option value="full">Maximum</option>
              </select>
              
              <div style="font-size:11px;color:#666;margin-top:6px;" id="compression-hint">
                Balanced speed and file size
              </div>
            </div>
          </div>
        `;
        
        showMessageBox({
          title: 'Export Options',
          message: optionsHTML,
          buttons: [
            {
              label: 'Export',
              classList: ['primary'],
              onClick: async () => {
                exportOptions.include_loaders = document.getElementById('export-loaders').checked;
                exportOptions.include_assets = document.getElementById('export-assets').checked;
                exportOptions.include_config = document.getElementById('export-config').checked;
                exportOptions.compression = document.getElementById('export-compression').value;
                resolve(true);
              }
            },
            {
              label: 'Cancel',
              onClick: () => resolve(false)
            }
          ]
        });
        
        // Add compression level hint listener
        setTimeout(() => {
          const compressionSelect = document.getElementById('export-compression');
          const hint = document.getElementById('compression-hint');
          if (compressionSelect && hint) {
            compressionSelect.addEventListener('change', (e) => {
              const hints = {
                quick: 'Faster but larger file size',
                standard: 'Balanced speed and file size',
                full: 'Smaller file but slower compression'
              };
              hint.textContent = hints[e.target.value] || '';
            });
          }
        }, 100);
      }).then(async (confirmed) => {
        if (!confirmed) return;
        
        // Show loading message
        const loadingBox = getEl('loading-box');
        if (loadingBox) {
          const loadingText = loadingBox.querySelector('.loading-text');
          if (loadingText) loadingText.textContent = 'Exporting version...';
          toggleClass(getEl('loading-overlay'), 'hidden', false);
          toggleClass(loadingBox, 'hidden', false);
        }
        
        const result = await api('/api/versions/export', 'POST', { 
          category, 
          folder,
          export_options: exportOptions
        });
        
        // Hide loading
        if (loadingBox) {
          toggleClass(getEl('loading-overlay'), 'hidden', true);
          toggleClass(loadingBox, 'hidden', true);
        }
        
        if (!result.ok) {
          if (result.error === 'Export cancelled by user') {
            showMessageBox({ title: 'Export Cancelled', message: 'You cancelled the export', buttons: [{ label: 'OK' }] });
          } else {
            showMessageBox({ title: 'Export Error', message: result.error || 'Failed to export version', buttons: [{ label: 'OK' }] });
          }
          return;
        }
        
        const fileSize = (result.size_bytes / 1024 / 1024).toFixed(2);
        showMessageBox({ title: 'Export Successful!', message: `File saved to:<br><b>${result.filepath}</b><br><br>File size<br><b>${fileSize} MB</b>`, buttons: [{ label: 'OK' }] });
        await init();
      });
    } catch (e) {
      console.error('Export error:', e);
      showMessageBox({ title: 'Export Error', message: 'An error occurred during export:<br><br>' + e.message, buttons: [{ label: 'OK' }] });
    }
  };

  const handleImportVersions = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.hlvdf';
    input.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      
      // Show loading
      const loadingBox = getEl('loading-box');
      if (loadingBox) {
        const loadingText = loadingBox.querySelector('.loading-text');
        if (loadingText) loadingText.textContent = 'Importing version...';
        toggleClass(getEl('loading-overlay'), 'hidden', false);
        toggleClass(loadingBox, 'hidden', false);
      }
      
      try {
        const filename = file.name;
        
        // Extract version name from filename - remove .hlvdf extension if present
        const versionName = filename.endsWith('.hlvdf') ? filename.slice(0, -6) : filename;
        
        if (!versionName || versionName.length === 0) {
          // Hide loading
          if (loadingBox) {
            toggleClass(getEl('loading-overlay'), 'hidden', true);
            toggleClass(loadingBox, 'hidden', true);
          }
          
          showMessageBox({
            title: 'Import Error',
            message: 'Invalid filename. Please use a valid .hlvdf file.',
            buttons: [{ label: 'OK' }]
          });
          return;
        }
        
        // Use FormData to send file directly (no base64 conversion needed)
        const formData = new FormData();
        formData.append('version_name', versionName);
        formData.append('zip_file', file); // The File object directly
        
        // Send to backend using FormData (multipart/form-data encoding)
        // The browser will handle streaming large files without converting to strings
        console.log('Sending import request with file size:', file.size);
        
        try {
          const response = await fetch('/api/versions/import', {
            method: 'POST',
            body: formData
            // Note: Don't set Content-Type header - browser will set it with boundary
          });
          
          const result = await response.json();
          
          // Hide loading
          if (loadingBox) {
            toggleClass(getEl('loading-overlay'), 'hidden', true);
            toggleClass(loadingBox, 'hidden', true);
          }
          
          if (!result.ok) {
            showMessageBox({
              title: 'Import Error',
              message: result.error || 'Failed to import version',
              buttons: [{ label: 'OK' }]
            });
            return;
          }
          
          showMessageBox({
            title: 'Import Successful',
            message: `Successfully imported version "${versionName}"<br><br>The version now appears in your Installed list with an IMPORTED badge.`,
            buttons: [{ label: 'OK' }]
          });
          
          // Refresh the versions list
          await init();
        } catch (e) {
          // Hide loading on error
          if (loadingBox) {
            toggleClass(getEl('loading-overlay'), 'hidden', true);
            toggleClass(loadingBox, 'hidden', true);
          }
          
          console.error('Import error:', e);
          showMessageBox({
            title: 'Import Error',
            message: 'An error occurred during import: ' + e.message,
            buttons: [{ label: 'OK' }]
          });
        }
      } catch (e) {
        // Hide loading on any outer error
        if (loadingBox) {
          toggleClass(getEl('loading-overlay'), 'hidden', true);
          toggleClass(loadingBox, 'hidden', true);
        }
        console.error('Unexpected error during import:', e);
        showMessageBox({
          title: 'Import Error',
          message: 'An unexpected error occurred: ' + e.message,
          buttons: [{ label: 'OK' }]
        });
      }
    };
    input.click();
  };

  const initVersionsExportImport = () => {
    const exportBtn = getEl('export-versions-btn');
    const importBtn = getEl('import-versions-btn');
    
    if (exportBtn) {
      exportBtn.addEventListener('click', handleExportVersions);
    }
    
    if (importBtn) {
      importBtn.addEventListener('click', handleImportVersions);
    }
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

    // Update installed versions count in subtitle
    const installedVersionsSubtitle = getEl('installed-versions-subtitle');
    if (installedVersionsSubtitle) {
      const c = installed.length;
      installedVersionsSubtitle.textContent = `${c} version${c !== 1 ? 's' : ''} installed`;
    }

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

  // -------- Settings Validation --------

  const validateRAMFormat = (ramStr) => {
    if (!ramStr || !ramStr.trim()) return false;
    // Match: digits only, or digits followed by single character (K, M, G, T)
    const match = ramStr.trim().match(/^(\d+)([KMGT])?$/i);
    return !!match;
  };

  const parseRAMValue = (ramStr) => {
    const match = ramStr.trim().match(/^(\d+)([KMGT])?$/i);
    if (!match) return null;
    
    const value = parseInt(match[1], 10);
    const unit = match[2] ? match[2].toUpperCase() : '';
    
    if (unit === 'K') return value;
    if (unit === 'M') return value * 1024;
    if (unit === 'G') return value * 1024 * 1024;
    if (unit === 'T') return value * 1024 * 1024 * 1024;
    return value;
  };

  const validateSettings = () => {
    const errors = {};
    
    // Validate username - must be between 3 and 16 characters
    const username = (getEl('settings-username')?.value || '').trim();
    if (!username || username.length < 3 || username.length > 16) {
      errors.username = true;
    }
    
    // Validate RAM values
    const minRamStr = (getEl('settings-min-ram')?.value || '').trim();
    const maxRamStr = (getEl('settings-max-ram')?.value || '').trim();
    
    // Minimum RAM must not be empty
    if (!minRamStr) {
      errors.min_ram = true;
    } else if (!validateRAMFormat(minRamStr)) {
      errors.min_ram = true;
    } else {
      // Check if min RAM is >= 0
      const minVal = parseRAMValue(minRamStr);
      if (minVal < 0) {
        errors.min_ram = true;
      }
    }
    
    // Maximum RAM must not be empty
    if (!maxRamStr) {
      errors.max_ram = true;
    } else if (!validateRAMFormat(maxRamStr)) {
      errors.max_ram = true;
    } else {
      // Check if max RAM is >= 1
      const maxVal = parseRAMValue(maxRamStr);
      if (maxVal < 1) {
        errors.max_ram = true;
      }
    }
    
    // Check if max RAM is less than min RAM
    if (minRamStr && maxRamStr && validateRAMFormat(minRamStr) && validateRAMFormat(maxRamStr)) {
      const minVal = parseRAMValue(minRamStr);
      const maxVal = parseRAMValue(maxRamStr);
      if (minVal > maxVal) {
        errors.max_ram = true;
      }
    }
    
    return errors;
  };

  const updateSettingsValidationUI = () => {
    const errors = validateSettings();
    
    // Helper to set indicator tooltip based on error type
    const setIndicatorTooltip = (indicator, errorKey, value) => {
      if (!indicator) return;
      
      let tooltip = '';
      if (errorKey === 'username') {
        const len = value.length;
        if (len === 0) {
          tooltip = 'Username cannot be empty';
        } else if (len < 3) {
          tooltip = `Username too short (${len}/3-16 characters)`;
        } else if (len > 16) {
          tooltip = `Username too long (${len}/3-16 characters)`;
        }
      } else if (errorKey === 'min_ram') {
        if (!value || value.trim() === '') {
          tooltip = 'Minimum RAM cannot be empty';
        } else if (!validateRAMFormat(value)) {
          tooltip = 'Invalid format: use number with optional K, M, G, or T suffix (e.g., 16M)';
        } else {
          const minVal = parseRAMValue(value);
          if (minVal < 0) {
            tooltip = 'Minimum RAM cannot be negative';
          }
        }
      } else if (errorKey === 'max_ram') {
        if (!value || value.trim() === '') {
          tooltip = 'Maximum RAM cannot be empty';
        } else if (!validateRAMFormat(value)) {
          tooltip = 'Invalid format: use number with optional K, M, G, or T suffix (e.g., 4096M)';
        } else {
          const maxVal = parseRAMValue(value);
          const minRamStr = (getEl('settings-min-ram')?.value || '').trim();
          if (maxVal < 1) {
            tooltip = 'Maximum RAM must be at least 1 byte or more (value is too low)';
          } else if (minRamStr && validateRAMFormat(minRamStr)) {
            const minVal = parseRAMValue(minRamStr);
            if (minVal > maxVal) {
              tooltip = `Maximum RAM must be greater than Minimum RAM (${minRamStr} > ${value})`;
            }
          }
        }
      }
      
      if (tooltip) {
        indicator.title = tooltip;
      }
    };
    
    // Update username
    const usernameInput = getEl('settings-username');
    const usernameRow = getEl('username-row');
    if (usernameInput && usernameRow) {
      const indicator = usernameRow.querySelector('.invalid-indicator');
      if (errors.username) {
        usernameInput.classList.add('invalid-setting');
        usernameRow.classList.add('row-invalid');
        indicator?.classList.remove('hidden');
        setIndicatorTooltip(indicator, 'username', usernameInput.value);
      } else {
        usernameInput.classList.remove('invalid-setting');
        usernameRow.classList.remove('row-invalid');
        indicator?.classList.add('hidden');
      }
    }
    
    // Update min ram
    const minRamInput = getEl('settings-min-ram');
    if (minRamInput) {
      const minRamRow = minRamInput.closest('.row');
      const indicator = minRamRow?.querySelector('.invalid-indicator');
      if (errors.min_ram) {
        minRamInput.classList.add('invalid-setting');
        minRamRow?.classList.add('row-invalid');
        indicator?.classList.remove('hidden');
        setIndicatorTooltip(indicator, 'min_ram', minRamInput.value);
      } else {
        minRamInput.classList.remove('invalid-setting');
        minRamRow?.classList.remove('row-invalid');
        indicator?.classList.add('hidden');
      }
    }
    
    // Update max ram
    const maxRamInput = getEl('settings-max-ram');
    if (maxRamInput) {
      const maxRamRow = maxRamInput.closest('.row');
      const indicator = maxRamRow?.querySelector('.invalid-indicator');
      if (errors.max_ram) {
        maxRamInput.classList.add('invalid-setting');
        maxRamRow?.classList.add('row-invalid');
        indicator?.classList.remove('hidden');
        setIndicatorTooltip(indicator, 'max_ram', maxRamInput.value);
      } else {
        maxRamInput.classList.remove('invalid-setting');
        maxRamRow?.classList.remove('row-invalid');
        indicator?.classList.add('hidden');
      }
    }
    
    // Update launch button disabled state
    const launchBtn = getEl('launch-btn');
    if (launchBtn) {
      launchBtn.disabled = Object.keys(errors).length > 0;
    }
    
    // Update home info to show validation warnings
    updateHomeInfo();
    
    // Reinitialize tooltips in case indicators have changed visibility
    initTooltips();
  };

  const initLaunchButton = () => {
    const launchBtn = getEl('launch-btn');
    if (!launchBtn) return;

    launchBtn.addEventListener('click', async () => {
      const validationErrors = validateSettings();
      if (Object.keys(validationErrors).length > 0) {
        setText('status', '⚠ Please fix the invalid settings before launching!');
        return;
      }

      if (!selectedVersion) {
        setText(
          'status',
          '⚠ Please select a version on the Versions page first!'
        );
        return;
      }

      const meta = versionsList.find(
        (v) => `${v.category}/${v.folder}` === selectedVersion
      );
      if (!meta) {
        setText('status', '⚠ Selected version metadata not found!');
        return;
      }

      if (meta.raw && meta.raw.launch_disabled) {
        const msg =
          meta.raw.launch_disabled_message ||
          '⚠ This version cannot be launched!';
        window.alert(msg);
        setText('status', '⚠ Failed to launch: ' + msg);
        return;
      }

      const [category, folder] = selectedVersion.split('/');
      let selectedLoader = null;

      try {
        const loaderData = await api(`/api/loaders/${category}/${folder}`);
        if (loaderData && loaderData.ok && loaderData.installed) {
          const installed = loaderData.installed;
          const hasLoaders = (installed.fabric && installed.fabric.length > 0) || 
                             (installed.forge && installed.forge.length > 0);
          
          if (hasLoaders) {
            selectedLoader = await promptLoaderSelection(installed);
            if (selectedLoader === false) return;
          }
        }
      } catch (err) {
        console.warn('Failed to check loaders:', err);
      }

      const overlay = getEl('loading-overlay');
      const box = getEl('launching-box');

      if (overlay) overlay.classList.remove('hidden');
      if (box) box.classList.remove('hidden');

      const username = settingsState.username || 'Player';
      const launchData = { category, folder, username };
      if (selectedLoader) {
        launchData.loader = selectedLoader.type;
        launchData.loader_version = selectedLoader.version;
      }

      const res = await api('/api/launch', 'POST', launchData);

      if (!res.ok) {
        // messages with line breaks are shown as HTML so the user can read
        // multi-line compatibility warnings.
        if (res.message && res.message.includes('\n')) {
          setHTML('status', res.message.replace(/\n/g, '<br>'));
        } else {
          setText('status', res.message);
        }
        const overlay = getEl('loading-overlay');
        const box = getEl('launching-box');
        if (overlay) overlay.classList.add('hidden');
        if (box) box.classList.add('hidden');
        return;
      }

      // Game launched successfully - poll status until game exits or crashes
      const processId = res.process_id;
      let pollAttempts = 0;
      const maxPollAttempts = 600;
      let overlayClosedByWindow = false;
      
      const pollWindowVisibility = async () => {
        if (overlayClosedByWindow) return;
        
        try {
          const windowRes = await api(`/api/game_window_visible/${processId}`);
          console.log(`[Window] Visibility check:`, windowRes);
          
          if (windowRes.ok && windowRes.visible) {
            console.log('[Window] Game window is visible, closing overlay');
            overlayClosedByWindow = true;
            const overlay = getEl('loading-overlay');
            const box = getEl('launching-box');
            if (overlay) overlay.classList.add('hidden');
            if (box) box.classList.add('hidden');
            setText('status', 'Minecraft has opened!');
            return;
          }
        } catch (err) {
          console.log('[Window] Could not check visibility (normal if not on Windows):', err.message);
        }
        
        if (pollAttempts < maxPollAttempts && !overlayClosedByWindow) {
          setTimeout(pollWindowVisibility, 2000);
        }
      };
      
      const pollGameStatus = async () => {
        try {
          const statusRes = await api(`/api/launch_status/${processId}`);
          console.log(`[Polling] Attempt ${pollAttempts}, Response:`, statusRes);
          
          if (statusRes.ok && statusRes.status === 'running') {
            pollAttempts++;
            
            if (!overlayClosedByWindow) {
              const elapsed = Math.floor(statusRes.elapsed || 0);
              const minutes = Math.floor(elapsed / 60);
              const seconds = elapsed % 60;
              const timeStr = minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
              setText('status', `Launching... (${timeStr})`);
            }
            
            if (pollAttempts < maxPollAttempts) {
              setTimeout(pollGameStatus, 1000);
            } else {
              console.warn('[Polling] Max polling attempts reached');
              const overlay = getEl('loading-overlay');
              const box = getEl('launching-box');
              if (overlay) overlay.classList.add('hidden');
              if (box) box.classList.add('hidden');
              setText('status', '');
            }
            return;
          }
          
          // Game has exited or crashed
          console.log('[Polling] Game has exited with status:', statusRes.status);
          const overlay = getEl('loading-overlay');
          const box = getEl('launching-box');
          if (overlay) overlay.classList.add('hidden');
          if (box) box.classList.add('hidden');
          
          if (statusRes.ok) {
            setText('status', '');
          } else {
            setText('status', `Minecraft has crashed! (exit code: ${statusRes.exit_code || 'unknown'})`);
            if (statusRes.log_path) {
              await showCrashDialog(processId, statusRes.log_path);
            }
          }
        } catch (err) {
          console.error('[Polling] Error polling game status:', err);
          pollAttempts++;
          if (pollAttempts < maxPollAttempts) {
            setTimeout(pollGameStatus, 1000);
          } else {
            console.warn('[Polling] Max polling attempts reached after error');
            const overlay = getEl('loading-overlay');
            const box = getEl('launching-box');
            if (overlay) overlay.classList.add('hidden');
            if (box) box.classList.add('hidden');
            setText('status', '');
          }
        }
      };
      
      setText('status', 'Launching...');
      setTimeout(() => {
        pollGameStatus();
        pollWindowVisibility();
      }, 2000);
    });
  };


  const showCrashDialog = async (processId, logPath) => {
    console.log(`[showCrashDialog] Minecraft crashed. logPath: ${logPath}`);
    
    let crashDetails = '';
    
    if (logPath) {
      try {
        const crashRes = await api('/api/crash-log', 'POST', {
          log_path: logPath
        });
        
        if (crashRes.ok && crashRes.error_analysis) {
          const analysis = crashRes.error_analysis;
          if (analysis.has_error && analysis.message) {
            crashDetails += `<br><strong style="color:#ff6b6b;">${analysis.message}</strong><br>`;
            if (analysis.details) {
              crashDetails += analysis.details;
            }
            if (analysis.suggestion) {
              crashDetails += `<br><br><strong>Suggestion:</strong> ${analysis.suggestion}`;
            }
          }
        }
      } catch (err) {
        console.error('Error analyzing crash log:', err);
      }
    }
    
    const buttons = [
      {
        label: 'Open logs',
        onClick: () => viewCrashLogs(processId, logPath),
      },
      { 
        label: 'OK',
        classList: ['primary'],
        onClick: () => {},
      },
    ];

    let message = 'Ouch, it looks like Minecraft crashed...';
    if (crashDetails) {
      message += `\n\n${crashDetails}`;
    }

    showMessageBox({
      title: 'Minecraft Crashed',
      message: message,
      buttons: buttons,
      description: logPath ? `Latest log: ${getFileName(logPath)}` : 'No log file found',
    });
  };

  const viewCrashLogs = async (processId, logPath) => {
    try {
      if (!logPath) {
        showMessageBox({
          title: 'Log Not Found',
          message: 'No crash log file found for this process.',
          buttons: [{
            label: 'OK',
            onClick: () => {},
          }],
        });
        return;
      }

      // Debug logging
      console.log(`[viewCrashLogs] Opening crash log: ${logPath}`);

      // Open the log file in the system's default app
      const openRes = await api('/api/open-crash-log', 'POST', {
        log_path: logPath
      });
      
      if (openRes.ok) {
        showMessageBox({
          title: 'Opening Crash Log',
          message: `Opening ${logPath.split(/[\\/]/).pop()} in your default text editor...`,
          buttons: [{
            label: 'OK',
            onClick: () => {},
          }],
        });
      } else {
        showMessageBox({
          title: 'Error',
          message: `Failed to open crash log: ${openRes.error || 'Unknown error'}`,
          buttons: [{
            label: 'OK',
            onClick: () => {},
          }],
        });
      }
    } catch (err) {
      console.error('Error opening crash log:', err);
      showMessageBox({
        title: 'Error',
        message: `Error: ${err.message}`,
        buttons: [{
          label: 'OK',
          onClick: () => {},
        }],
      });
    }
  };

  const getFileName = (path) => {
    if (!path) return '';
    return path.split(/[\\/]/).pop();
  };

  const promptLoaderSelection = (installed) => {
    return new Promise((resolve) => {
      const loaderOptions = [];
      
      // Add vanilla option
      loaderOptions.push({
        label: 'None (vanilla)',
        onClick: () => resolve(null),
      });

      // Add fabric loaders
      if (installed.fabric && installed.fabric.length > 0) {
        installed.fabric.forEach((loader) => {
          loaderOptions.push({
            label: `Fabric ${loader.version}`,
            onClick: () => resolve({type: 'fabric', version: loader.version}),
          });
        });
      }

      // Add forge loaders
      if (installed.forge && installed.forge.length > 0) {
        installed.forge.forEach((loader) => {
          loaderOptions.push({
            label: `Forge ${loader.version}`,
            onClick: () => resolve({type: 'forge', version: loader.version}),
          });
        });
      }

      // Add cancel
      loaderOptions.push({
        label: 'Cancel',
        onClick: () => resolve(false),
      });

      showMessageBox({
        title: 'Choose Mod Loader',
        message: 'This version has mod loaders installed. Which one would you like to launch with?',
        buttons: loaderOptions,
      });
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
        updateSettingsValidationUI();
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
      updateSettingsValidationUI();
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

    const extraJvmInput = getEl('settings-extra-jvm-args');
    if (extraJvmInput) {
      extraJvmInput.addEventListener('input', (e) => {
        autoSaveSetting('extra_jvm_args', (e.target.value || '').trim());
      });
    }

    const javaRuntimeSelect = getEl('settings-java-runtime');
    if (javaRuntimeSelect) {
      javaRuntimeSelect.addEventListener('change', (e) => {
        autoSaveSetting('java_path', (e.target.value || '').trim());
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
            title: 'Login',
            message: `Enter your Histolauncher account credentials below.<br>` + signupLink,
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
                      credentials: 'include',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ username, password }),
                    });
                    let json;
                    try { json = await res.json(); } catch (e) { json = null; }

                    console.log('[Login] Response status:', res.status);

                    if (res.ok && json && json.success) {
                      console.log('[Login] Success! Session token received, verifying with launcher...');
                      
                      const sessionToken = json.sessionToken;
                      if (!sessionToken) {
                        console.error('[Login] No session token in response!');
                        showMessageBox({ title: 'Error', message: 'No session token received. Please try again.', buttons: [{ label: 'OK' }] });
                        if (accountSelect) accountSelect.value = 'Local';
                        autoSaveSetting('account_type', 'Local');
                        return;
                      }

                      // Verify session with the launcher backend (which verifies with Cloudflare)
                      const verifyRes = await api('/api/account/verify-session', 'POST', { sessionToken });
                      console.log('[Login] Launcher verification response:', verifyRes);
                      
                      if (verifyRes.ok && verifyRes.username && verifyRes.uuid) {
                        console.log('[Login] Session verified! UUID:', verifyRes.uuid);
                        // Only store account_type, NOT username/uuid (those come from Cloudflare via /api/account/current)
                        settingsState.account_type = 'Histolauncher';
                        histolauncherUsername = verifyRes.username;
                        localUsernameModified = false;
                        await api('/api/settings', 'POST', {
                          account_type: 'Histolauncher'
                          // Don't send username/uuid - those will be fetched securely from /api/account/current
                        });
                        // Now fetch the verified account data from backend
                        const currentUser = await api('/api/account/current', 'GET');
                        if (currentUser.ok && currentUser.authenticated) {
                          settingsState.username = currentUser.username;
                          settingsState.uuid = currentUser.uuid;
                        }
                        await init();
                      } else {
                        console.error('[Login] Launcher verification failed! Response:', verifyRes);
                        showMessageBox({ title: 'Error', message: verifyRes.error || 'Failed to verify session. Please try again.', buttons: [{ label: 'OK' }] });
                        if (accountSelect) accountSelect.value = 'Local';
                        autoSaveSetting('account_type', 'Local');
                      }
                    } else {
                      const errorMsg = (json && json.error) || `Failed to authenticate (${res.status})`;
                      console.error('[Login] Error:', errorMsg);
                      showMessageBox({ title: 'Error', message: errorMsg, buttons: [{ label: 'OK' }] });
                      if (accountSelect) accountSelect.value = 'Local';
                      autoSaveSetting('account_type', 'Local');
                    }
                  } catch (e) {
                    console.error('[Login] Exception:', e);
                    showMessageBox({ title: 'Error', message: `Connection failed: ${e.message}`, buttons: [{ label: 'OK' }] });
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

    const clearLogsButton = getEl('clear-logs-btn');
    if (clearLogsButton) {
      clearLogsButton.addEventListener('click', async () => {
        const result = await api('/api/clear-logs', 'POST');
        if (result.ok) {
          showMessageBox({
            title: 'Logs Cleared',
            message: result.message || 'Logs have been cleared successfully.',
            buttons: [{
              label: 'OK',
              onClick: () => {}
            }]
          });
        } else {
          showMessageBox({
            title: 'Error',
            message: `Failed to clear logs: ${result.error || 'Unknown error'}`,
            buttons: [{
              label: 'OK',
              onClick: () => {}
            }]
          });
        }
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

    const fastDownloadInput = getEl('settings-fast-download');
    if (fastDownloadInput) {
      fastDownloadInput.addEventListener('change', async (e) => {
        const val = e.target.checked ? "1" : "0";
        await api('/api/settings', 'POST', { fast_download: val });
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

  // ---------------- Corrupted Versions Modal ----------------

  const showCorruptedVersionsModal = (corruptedList) => {
    if (!corruptedList || corruptedList.length === 0) {
      return;
    }

    const selectedVersions = {};
    
    // Build HTML for checkboxes
    let checkboxHtml = '<div class="row" style="display:grid;gap:8px;max-height:300px;overflow-y:auto;padding:8px 0;">';
    
    corruptedList.forEach((v) => {
      const id = `corrupted-${v.category}-${v.folder}`.replace(/\s+/g, '-').toLowerCase();
      selectedVersions[id] = false;
      
      checkboxHtml += `
        <label class="corrupted-version-item">
          <input type="checkbox" id="${id}" data-version-id="${id}">
          <span style="font-size:13px;">${v.folder} (${v.category})</span>
        </label>
      `;
    });
    
    checkboxHtml += '</div>';

    const message = `
      <div style="padding: 8px 0;">
        <p style="margin: 0 0 12px 0; color: #aaa; font-size: 13px;">
          You have corrupted versions that cannot be launched.<br><i>Select which ones you'd like to delete:</i>
        </p>
        ${checkboxHtml}
      </div>
    `;

    showMessageBox({
      title: 'Corrupted Versions detected',
      message: message,
      buttons: [
        {
          label: 'Delete Selected',
          classList: ['danger'],
          onClick: async () => {
            const checkboxes = document.querySelectorAll('input[data-version-id]:checked');
            const versionsToDelete = [];
            
            checkboxes.forEach((checkbox) => {
              const versionId = checkbox.getAttribute('data-version-id');
              const version = corruptedList.find(v => {
                const id = `corrupted-${v.category}-${v.folder}`.replace(/\s+/g, '-').toLowerCase();
                return id === versionId;
              });
              if (version) {
                versionsToDelete.push({
                  category: version.category,
                  folder: version.folder,
                });
              }
            });

            if (versionsToDelete.length > 0) {
              try {
                const deleteResult = await api('/api/delete-corrupted-versions', 'POST', {
                  versions: versionsToDelete,
                });

                if (deleteResult.ok) {
                  console.log(`[corrupted] Deleted ${deleteResult.deleted.length} version(s)`);
                  await init();
                } else {
                  console.error('[corrupted] Delete failed:', deleteResult.error);
                  showMessageBox({
                    title: 'Error',
                    message: `Failed to delete corrupted versions: ${deleteResult.error}`,
                    buttons: [{ label: 'OK' }],
                  });
                }
              } catch (e) {
                console.error('[corrupted] Error deleting:', e);
                showMessageBox({
                  title: 'Error',
                  message: `Failed to delete corrupted versions: ${e.message}`,
                  buttons: [{ label: 'OK' }],
                });
              }
            }
          },
        },
        { label: 'Cancel' },
      ],
    });

    setTimeout(() => {
      const checkboxes = document.querySelectorAll('input[data-version-id]');
      checkboxes.forEach((checkbox) => {
        checkbox.addEventListener('change', (e) => {
          const versionId = e.target.getAttribute('data-version-id');
          selectedVersions[versionId] = e.target.checked;
        });
      });
    }, 50);
  };

  const checkForCorruptedVersions = async () => {
    try {
      const result = await api('/api/corrupted-versions');
      if (result.ok && result.corrupted && result.corrupted.length > 0) {
        showCorruptedVersionsModal(result.corrupted);
      }
    } catch (e) {
      console.error('[corrupted] Error checking corrupted versions:', e);
    }
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
      _progressText: v.is_imported ? 'Imported' : 'Installed',
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

    // After rendering, restart polling for any installing versions to ensure
    // progress elements are properly cached from the newly rendered cards
    versionsList.forEach((v) => {
      if (v.installing && v._installKey) {
        // Delete old poller and restart it to use new card's progress elements
        if (activeInstallPollers[v._installKey]) {
          clearTimeout(activeInstallPollers[v._installKey]);
          delete activeInstallPollers[v._installKey];
        }
        try {
          startPollingForInstall(v._installKey, v);
        } catch (e) {
          console.warn('[init] Failed to restart polling for', v._installKey, e);
        }
      }
    });

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

    // Check for corrupted versions after UI is fully loaded
    await checkForCorruptedVersions();
  };

  // ---------------- Cleanup polling timers on page unload ----------------
  
  const clearAllPollers = () => {
    // Clear all active polling timers to prevent orphaned timers
    for (const key in activeInstallPollers) {
      const timeoutId = activeInstallPollers[key];
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      delete activeInstallPollers[key];
    }
    console.log('[cleanup] Cleared all active polling timers');
  };

  // Clean up polling timers when page unloads or refreshes
  window.addEventListener('beforeunload', clearAllPollers);
  window.addEventListener('unload', clearAllPollers);

  // -------- Tooltips --------

  let currentTooltip = null;

  const addFormattedLine = (parent, line) => {
    // Check positions of colon and first parenthesis
    const firstParenIndex = line.indexOf('(');
    const colonIndex = line.indexOf(': ');
    
    // Only apply colon formatting if colon comes before any parenthesis
    if (colonIndex !== -1 && (firstParenIndex === -1 || colonIndex < firstParenIndex)) {
      const label = line.substring(0, colonIndex);
      const value = line.substring(colonIndex + 2);
      
      const labelSpan = document.createElement('span');
      labelSpan.className = 'tooltip-label';
      labelSpan.textContent = label + ': ';
      parent.appendChild(labelSpan);
      
      const valueSpan = document.createElement('span');
      valueSpan.className = 'tooltip-value';
      parent.appendChild(valueSpan);
      
      // Parse parentheses in the value
      parseParenthesesInElement(valueSpan, value);
    } else {
      // No colon before parenthesis, just parse parentheses directly
      parseParenthesesInElement(parent, line);
    }
  };

  const parseParenthesesInElement = (parent, text) => {
    let lastIndex = 0;
    const regex = /\(([^)]*)\)/g;
    let match;
    
    while ((match = regex.exec(text)) !== null) {
      // Add text before parentheses
      if (match.index > lastIndex) {
        parent.appendChild(document.createTextNode(text.substring(lastIndex, match.index)));
      }
      
      // Add parentheses text as special span
      const parensSpan = document.createElement('span');
      parensSpan.className = 'tooltip-parens';
      parensSpan.textContent = match[0];
      parent.appendChild(parensSpan);
      
      lastIndex = regex.lastIndex;
    }
    
    // Add remaining text
    if (lastIndex < text.length) {
      parent.appendChild(document.createTextNode(text.substring(lastIndex)));
    }
  };

  const createTooltip = (text) => {
    const tooltip = document.createElement('div');
    tooltip.className = 'tooltip';
    
    // Support line breaks using \n character
    const lines = text.split('\\n');
    lines.forEach((line, index) => {
      addFormattedLine(tooltip, line);
      
      if (index < lines.length - 1) {
        tooltip.appendChild(document.createElement('br'));
      }
    });
    
    document.body.appendChild(tooltip);
    return tooltip;
  };

  const updateTooltipPosition = (tooltip, x, y) => {
    tooltip.style.left = (x + 10) + 'px';
    tooltip.style.top = (y + 10) + 'px';
  };

  const showTooltip = (element, text, e) => {
    if (!text || !text.trim()) return;
    
    // Remove existing tooltip
    if (currentTooltip) {
      currentTooltip.remove();
    }
    
    currentTooltip = createTooltip(text);
    
    // Position tooltip following mouse
    const mouseMoveHandler = (event) => {
      updateTooltipPosition(currentTooltip, event.clientX + 10, event.clientY);
    };
    
    const hideHandler = () => {
      if (currentTooltip) {
        currentTooltip.remove();
        currentTooltip = null;
      }
      element.removeEventListener('mousemove', mouseMoveHandler);
      element.removeEventListener('mouseleave', hideHandler);
    };
    
    element.addEventListener('mousemove', mouseMoveHandler);
    element.addEventListener('mouseleave', hideHandler);
    
    // Initial position
    updateTooltipPosition(currentTooltip, e.clientX + 10, e.clientY);
  };

  const initTooltips = () => {
    const infoBubbles = document.querySelectorAll('.info-bubble');
    
    infoBubbles.forEach((bubble) => {
      bubble.addEventListener('mouseenter', (e) => {
        const tooltip = bubble.getAttribute('data-tooltip');
        if (tooltip) {
          showTooltip(bubble, tooltip, e);
        }
      });
      
      // Also handle the error warning icon tooltips
      bubble.addEventListener('mousemove', (e) => {
        if (currentTooltip) {
          updateTooltipPosition(currentTooltip, e.clientX + 10, e.clientY);
        }
      });
      
      bubble.addEventListener('mouseleave', () => {
        if (currentTooltip) {
          currentTooltip.remove();
          currentTooltip = null;
        }
      });
    });
    
    // Also apply to error indicators
    const errorIndicators = document.querySelectorAll('.invalid-indicator:not(.hidden)');
    errorIndicators.forEach((indicator) => {
      indicator.addEventListener('mouseenter', (e) => {
        const tooltip = indicator.title;
        if (tooltip) {
          showTooltip(indicator, tooltip, e);
        }
      });
      
      indicator.addEventListener('mousemove', (e) => {
        if (currentTooltip) {
          updateTooltipPosition(currentTooltip, e.clientX + 10, e.clientY);
        }
      });
      
      indicator.addEventListener('mouseleave', () => {
        if (currentTooltip) {
          currentTooltip.remove();
          currentTooltip = null;
        }
      });
    });
  };

  // ---------------- Settings Dropdowns ----------------

  const initSettingsDropdowns = () => {
    const titles = $$('.settings-dropdown-title');
    
    titles.forEach((title) => {
      title.addEventListener('click', () => {
        const content = title.nextElementSibling;
        const indicator = title.querySelector('.dropdown-indicator');
        
        if (!content || !content.classList.contains('settings-dropdown-content')) {
          return;
        }
        
        const isCollapsed = content.classList.contains('collapsed');
        
        if (isCollapsed) {
          content.classList.remove('collapsed');
          indicator.textContent = '⏷';
        } else {
          content.classList.add('collapsed');
          indicator.textContent = '⏶';
        }
      });
    });
  };

  // ---------------- Mods Page ----------------

  const MODS_PAGE_SIZE = 20;

  let modsState = {
    provider: 'modrinth',
    modLoader: '',
    gameVersion: '',
    category: '',
    sortBy: 'relevance',
    searchQuery: '',
    currentPage: 1,
    totalPages: 1,
    availableModsRaw: [],
    availableMods: [],
    installedMods: [],
    installedModpacks: [],
    lastError: null,
  };

  const resetModsSearch = () => {
    modsState.currentPage = 1;
    modsState.totalPages = 1;
    modsState.availableModsRaw = [];
    modsState.availableMods = [];
  };

  const applyModsClientFilters = () => {
    let list = (modsState.availableModsRaw || []).slice();

    const categoryFilter = (modsState.category || '').trim().toLowerCase();
    if (categoryFilter) {
      list = list.filter((mod) => {
        const categories = Array.isArray(mod.categories) ? mod.categories : [];
        return categories.some((c) => String(c || '').toLowerCase() === categoryFilter);
      });
    }

    const sortBy = (modsState.sortBy || 'relevance').toLowerCase();
    if (sortBy === 'downloads') {
      list.sort((a, b) => Number(b.download_count || 0) - Number(a.download_count || 0));
    } else if (sortBy === 'name') {
      list.sort((a, b) => String(a.name || a.mod_name || '').localeCompare(String(b.name || b.mod_name || '')));
    } else if (sortBy === 'updated') {
      list.sort((a, b) => {
        const da = Date.parse(a.date_modified || 0) || 0;
        const db = Date.parse(b.date_modified || 0) || 0;
        return db - da;
      });
    }

    modsState.availableMods = list;
  };

  const refreshModsCategoryOptions = () => {
    const categorySelect = getEl('mods-category-select');
    if (!categorySelect) return;

    const previousValue = categorySelect.value || '';
    const set = new Set();
    (modsState.availableModsRaw || []).forEach((mod) => {
      const categories = Array.isArray(mod.categories) ? mod.categories : [];
      categories.forEach((cat) => {
        const normalized = String(cat || '').trim();
        if (normalized) set.add(normalized);
      });
    });

    const sortedCategories = Array.from(set).sort((a, b) => a.localeCompare(b));

    categorySelect.innerHTML = '';
    const allOpt = document.createElement('option');
    allOpt.value = '';
    allOpt.textContent = 'All';
    categorySelect.appendChild(allOpt);

    sortedCategories.forEach((cat) => {
      const opt = document.createElement('option');
      opt.value = cat;
      opt.textContent = cat;
      categorySelect.appendChild(opt);
    });

    if (sortedCategories.includes(previousValue)) {
      categorySelect.value = previousValue;
    } else {
      categorySelect.value = '';
      modsState.category = '';
    }
  };

  // --- Mods View Toggle ---
  const applyModsViewMode = () => {
    const mode = settingsState.mods_view || 'list';
    const containers = [
      getEl('installed-modpacks-list'),
      getEl('installed-mods-list'),
      getEl('available-mods-list'),
    ];
    containers.forEach((c) => {
      if (c) c.classList.toggle('list-view', mode === 'list');
    });

    const gridBtn = getEl('mods-view-grid-btn');
    const listBtn = getEl('mods-view-list-btn');
    if (gridBtn) gridBtn.classList.toggle('active', mode === 'grid');
    if (listBtn) listBtn.classList.toggle('active', mode === 'list');
  };

  const initModsViewToggle = () => {
    const gridBtn = getEl('mods-view-grid-btn');
    const listBtn = getEl('mods-view-list-btn');

    if (gridBtn) {
      gridBtn.addEventListener('click', () => {
        if (settingsState.mods_view !== 'grid') {
          autoSaveSetting('mods_view', 'grid');
          applyModsViewMode();
        }
      });
    }
    if (listBtn) {
      listBtn.addEventListener('click', () => {
        if (settingsState.mods_view !== 'list') {
          autoSaveSetting('mods_view', 'list');
          applyModsViewMode();
        }
      });
    }
    applyModsViewMode();
  };

  const initModsPage = () => {
    const clearBtn = getEl('mods-clear-filters-btn');

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        modsState.provider = 'modrinth';
        modsState.modLoader = '';
        modsState.gameVersion = '';
        modsState.category = '';
        modsState.sortBy = 'relevance';
        modsState.searchQuery = '';
        resetModsSearch();

        const providerSelect = getEl('mods-provider-select');
        const loaderSelect = getEl('mods-loader-select');
        const versionSelect = getEl('mods-version-select');
        const categorySelect = getEl('mods-category-select');
        const sortSelect = getEl('mods-sort-select');
        const searchInput = getEl('mods-search');

        if (providerSelect) providerSelect.value = 'modrinth';
        if (loaderSelect) loaderSelect.value = '';
        if (versionSelect) versionSelect.value = '';
        if (categorySelect) categorySelect.value = '';
        if (sortSelect) sortSelect.value = 'relevance';
        if (searchInput) searchInput.value = '';

        updateModsProviderDisplay();
        searchMods();
      });
    }

    let filterTimeout;

    const providerSelect = getEl('mods-provider-select');
    if (providerSelect) {
      providerSelect.addEventListener('change', () => {
        modsState.provider = providerSelect.value;
        resetModsSearch();
        updateModsProviderDisplay();
        clearTimeout(filterTimeout);
        filterTimeout = setTimeout(() => searchMods(), 400);
      });
    }

    const loaderSelect = getEl('mods-loader-select');
    if (loaderSelect) {
      loaderSelect.addEventListener('change', () => {
        modsState.modLoader = loaderSelect.value;
        renderInstalledMods();
        resetModsSearch();
        clearTimeout(filterTimeout);
        filterTimeout = setTimeout(() => searchMods(), 400);
      });
    }

    const versionSelect = getEl('mods-version-select');
    if (versionSelect) {
      versionSelect.addEventListener('change', () => {
        modsState.gameVersion = versionSelect.value;
        resetModsSearch();
        clearTimeout(filterTimeout);
        filterTimeout = setTimeout(() => searchMods(), 400);
      });
    }

    const categorySelect = getEl('mods-category-select');
    if (categorySelect) {
      categorySelect.addEventListener('change', () => {
        modsState.category = categorySelect.value;
        applyModsClientFilters();
        renderAvailableMods();
      });
    }

    const sortSelect = getEl('mods-sort-select');
    if (sortSelect) {
      sortSelect.addEventListener('change', () => {
        modsState.sortBy = sortSelect.value;
        applyModsClientFilters();
        renderAvailableMods();
      });
    }

    const searchInput = getEl('mods-search');
    if (searchInput) {
      let searchTimeout;
      searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          modsState.searchQuery = searchInput.value.trim();
          resetModsSearch();
          searchMods();
        }, 500);
      });
    }

    const modsRefreshBtn = getEl('mods-refresh-btn');
    if (modsRefreshBtn) {
      modsRefreshBtn.addEventListener('click', () => {
        resetModsSearch();
        searchMods();
      });
    }

    // --- Import mod JAR ---
    const importModBtn = getEl('import-mod-btn');
    const importModFileInput = getEl('import-mod-file-input');
    if (importModBtn && importModFileInput) {
      importModBtn.addEventListener('click', () => {
        importModFileInput.value = '';
        importModFileInput.click();
      });
      importModFileInput.addEventListener('change', () => {
        const file = importModFileInput.files[0];
        if (!file) return;
        handleImportMod(file);
      });
    }

    // --- Export modpack ---
    const exportModpackBtn = getEl('export-modpack-btn');
    if (exportModpackBtn) {
      exportModpackBtn.addEventListener('click', () => showExportModpackWizard());
    }

    // --- Import modpack ---
    const importModpackBtn = getEl('import-modpack-btn');
    const importModpackFileInput = getEl('import-modpack-file-input');
    if (importModpackBtn && importModpackFileInput) {
      importModpackBtn.addEventListener('click', () => {
        importModpackFileInput.value = '';
        importModpackFileInput.click();
      });
      importModpackFileInput.addEventListener('change', () => {
        const file = importModpackFileInput.files[0];
        if (!file) return;
        handleImportModpack(file);
      });
    }

    initModsViewToggle();
    populateModsVersionDropdown();
    loadInstalledMods();
    searchMods();
  };

  const updateModsProviderDisplay = () => {
    const display = getEl('mods-provider-display');
    if (display) {
      display.textContent = modsState.provider === 'modrinth' ? 'Modrinth' : 'CurseForge';
    }
  };

  const populateModsVersionDropdown = () => {
    const select = getEl('mods-version-select');
    if (!select) return;

    select.innerHTML = '<option value="">All</option>';

    api('/api/mods/version-options', 'GET')
      .then((res) => {
        if (!res || !res.ok) return;
        const versions = Array.isArray(res.versions) ? res.versions : [];
        versions.slice(0, 100).forEach((entry) => {
          const ver = entry.version || entry.folder;
          if (!ver) return;
          const opt = document.createElement('option');
          opt.value = ver;
          opt.textContent = ver;
          select.appendChild(opt);
        });
      })
      .catch((err) => console.error('Failed to load mod version options:', err));
  };

  const loadInstalledMods = async () => {
    try {
      const [modsRes, packsRes] = await Promise.all([
        api('/api/mods/installed', 'GET'),
        api('/api/modpacks/installed', 'GET'),
      ]);
      if (modsRes && modsRes.ok) {
        modsState.installedMods = modsRes.mods || [];
      }
      if (packsRes && packsRes.ok) {
        modsState.installedModpacks = packsRes.modpacks || [];
      }
      renderInstalledMods();
    } catch (err) {
      console.error('Failed to load installed mods:', err);
    }
  };

  const searchMods = async () => {
    try {
      modsState.lastError = null;
      const warn = getEl('mods-section-warning');
      if (warn) warn.classList.add('hidden');

      // Show loading indicator, clear current list
      const modsLoading = getEl('mods-loading');
      const availableList = getEl('available-mods-list');
      if (modsLoading) modsLoading.classList.remove('hidden');
      if (availableList) availableList.innerHTML = '';

      const pageIndex = modsState.currentPage - 1;
      const res = await api('/api/mods/search', 'POST', {
        provider: modsState.provider,
        search_query: modsState.searchQuery,
        game_version: modsState.gameVersion,
        mod_loader: modsState.modLoader,
        page_size: MODS_PAGE_SIZE,
        page_index: pageIndex,
      });

      if (res && res.ok) {
        const incoming = Array.isArray(res.mods) ? res.mods : [];

        modsState.availableModsRaw = incoming;

        // Calculate total pages from total_count if available
        const totalCount = res.total_count || incoming.length;
        modsState.totalPages = Math.max(1, Math.ceil(totalCount / MODS_PAGE_SIZE));

        refreshModsCategoryOptions();
        applyModsClientFilters();

        if (warn) {
          if (res.error) {
            warn.textContent = res.requires_api_key
              ? 'CurseForge requires an API key. Add a key to use CurseForge provider, or switch to Modrinth.'
              : `Provider error: ${res.error}`;
            warn.classList.remove('hidden');
          }
        }

        if (modsLoading) modsLoading.classList.add('hidden');
        renderAvailableMods();
        renderModsPagination();
      } else {
        if (modsLoading) modsLoading.classList.add('hidden');
        modsState.lastError = (res && res.error) ? `Search failed: ${res.error}` : 'Search failed due to an unknown error.';
        if (warn) {
          warn.textContent = modsState.lastError;
          warn.classList.remove('hidden');
        }
        renderAvailableMods();
        renderModsPagination();
      }
    } catch (err) {
      console.error('Failed to search mods:', err);
      const modsLoading = getEl('mods-loading');
      if (modsLoading) modsLoading.classList.add('hidden');
      modsState.lastError = 'Search failed due to a network error.';
      const warn = getEl('mods-section-warning');
      if (warn) {
        warn.textContent = modsState.lastError;
        warn.classList.remove('hidden');
      }
      renderAvailableMods();
      renderModsPagination();
    }
  };

  // --- Pagination ---
  const renderModsPagination = () => {
    const container = getEl('mods-pagination');
    if (!container) return;
    container.innerHTML = '';

    const total = modsState.totalPages;
    const current = modsState.currentPage;
    if (total <= 1) return;

    const createPageBtn = (label, page, isActive, isDisabled) => {
      const btn = document.createElement('button');
      btn.textContent = label;
      btn.className = 'mods-page-btn';
      if (isActive) btn.classList.add('active');
      if (isDisabled) btn.disabled = true;
      btn.addEventListener('click', () => {
        if (page !== current && !isDisabled) {
          modsState.currentPage = page;
          searchMods();
        }
      });
      return btn;
    };

    // Previous button
    container.appendChild(createPageBtn('‹', current - 1, false, current <= 1));

    // Page numbers with ellipsis
    const pages = [];
    pages.push(1);
    if (current > 3) pages.push('...');
    for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
      pages.push(i);
    }
    if (current < total - 2) pages.push('...');
    if (total > 1) pages.push(total);

    pages.forEach((p) => {
      if (p === '...') {
        const ellipsis = document.createElement('span');
        ellipsis.className = 'mods-page-ellipsis';
        ellipsis.textContent = '...';
        container.appendChild(ellipsis);
      } else {
        container.appendChild(createPageBtn(String(p), p, p === current, false));
      }
    });

    // Next button
    container.appendChild(createPageBtn('›', current + 1, false, current >= total));
  };

  // --- Installed Mods (Fabric / Forge sections) ---
  const renderInstalledMods = () => {
    const list = getEl('installed-mods-list');
    const packsList = getEl('installed-modpacks-list');
    if (!list) return;

    const subtitle = getEl('installed-mods-subtitle');
    const installedCount = modsState.installedMods.length;
    const disabledCount = modsState.installedMods.filter((mod) => mod && mod.disabled).length;
    const packCount = modsState.installedModpacks.length;
    if (subtitle) {
      let text = `Your installed mods (${installedCount} installed, ${disabledCount} disabled)`;
      if (packCount > 0) text += ` · ${packCount} modpack${packCount !== 1 ? 's' : ''}`;
      subtitle.textContent = text;
    }

    // Render modpacks
    if (packsList) {
      packsList.innerHTML = '';
      const loaderFilter = (modsState.modLoader || '').toLowerCase();
      let packs = modsState.installedModpacks;
      if (loaderFilter) {
        packs = packs.filter((p) => (p.mod_loader || '').toLowerCase() === loaderFilter);
      }
      if (packs.length > 0) {
        const header = document.createElement('div');
        header.className = 'installed-mods-loader-header';
        header.textContent = 'Modpacks';
        packsList.appendChild(header);
        packs.forEach((pack) => packsList.appendChild(createModpackCard(pack)));
      }
    }

    list.innerHTML = '';

    // Apply current filters (provider only affects Available, not Installed)
    let filtered = modsState.installedMods;
    const loaderFilter = (modsState.modLoader || '').toLowerCase();
    if (loaderFilter) {
      filtered = filtered.filter((m) => (m.mod_loader || '').toLowerCase() === loaderFilter);
    }
    const installSearchQ = (modsState.searchQuery || '').toLowerCase();
    if (installSearchQ) {
      filtered = filtered.filter((m) => {
        const name = (m.display_name || m.mod_slug || m.name || '').toLowerCase();
        const slug = (m.mod_slug || '').toLowerCase();
        return name.includes(installSearchQ) || slug.includes(installSearchQ);
      });
    }

    if (filtered.length === 0) {
      list.innerHTML = '<p style="text-align:center;color:#999;">No mods installed</p>';
      applyModsViewMode();
      return;
    }

    // Group by loader, fabric first then forge then others
    const groups = {};
    filtered.forEach((mod) => {
      const loader = (mod.mod_loader || 'other').toLowerCase();
      if (!groups[loader]) groups[loader] = [];
      groups[loader].push(mod);
    });
    const loaderOrder = ['fabric', 'forge'];
    const allLoaders = [
      ...loaderOrder.filter((l) => groups[l]),
      ...Object.keys(groups).filter((l) => !loaderOrder.includes(l)),
    ];
    const showHeaders = allLoaders.length > 1;

    allLoaders.forEach((loader) => {
      if (showHeaders) {
        const header = document.createElement('div');
        header.className = 'installed-mods-loader-header';
        header.textContent = loader.charAt(0).toUpperCase() + loader.slice(1);
        list.appendChild(header);
      }
      groups[loader].forEach((mod) => list.appendChild(createModCard(mod, true)));
    });

    applyModsViewMode();
  };

  // --- Available Mods ---
  const renderAvailableMods = () => {
    const container = getEl('available-mods-list');
    if (!container) return;

    container.innerHTML = '';

    if (modsState.availableMods.length === 0) {
      if (modsState.lastError) {
        container.innerHTML = `<p style="text-align:center;color:#e06c6c;white-space:pre-wrap;">${modsState.lastError}</p>`;
      } else {
        container.innerHTML = '<p style="text-align:center;color:#999;">No mods found</p>';
      }
    } else {
      modsState.availableMods.forEach((mod) => {
        const card = createModCard(mod, false);
        container.appendChild(card);
      });
    }

    applyModsViewMode();
  };

  // --- Import Mod Handler ---
  const handleImportMod = (file) => {
    const fileName = file.name;

    // Build loader selection UI
    const content = document.createElement('div');
    const label = document.createElement('p');
    label.style.marginBottom = '8px';
    label.textContent = `Select the mod loader for "${fileName}":`;

    const select = document.createElement('select');
    select.className = 'mod-version-select';
    select.style.cssText = 'width:100%;margin-top:4px;max-width:100%;';
    ['Fabric', 'Forge'].forEach((l) => {
      const opt = document.createElement('option');
      opt.value = l.toLowerCase();
      opt.textContent = l;
      select.appendChild(opt);
    });

    content.appendChild(label);
    content.appendChild(select);

    showMessageBox({
      title: 'Import Mod',
      customContent: content,
      buttons: [
        {
          label: 'Import',
          classList: ['primary'],
          onClick: async () => {
            const modLoader = select.value;
            const formData = new FormData();
            formData.append('mod_loader', modLoader);
            formData.append('jar_name', fileName);
            formData.append('jar_file', file);

            try {
              const response = await fetch('/api/mods/import', {
                method: 'POST',
                body: formData,
              });
              const result = await response.json();

              if (result && result.ok) {
                showMessageBox({
                  title: 'Import Successful',
                  message: `Successfully imported <strong>${fileName}</strong> for ${modLoader}.`,
                  buttons: [{ label: 'OK' }],
                });
                loadInstalledMods();
              } else {
                showMessageBox({
                  title: 'Import Error',
                  message: result.error || 'Failed to import mod.',
                  buttons: [{ label: 'OK' }],
                });
              }
            } catch (err) {
              console.error('Failed to import mod:', err);
            }
          },
        },
        { label: 'Cancel' },
      ],
    });
  };

  // --- Mod Card ---
  const createModCard = (mod, isInstalled) => {
    const card = document.createElement('div');
    card.className = 'version-card mod-card';
    card.classList.add('unselectable', isInstalled ? 'section-installed' : 'section-available');

    if (isInstalled && mod.disabled) {
      card.classList.add('mod-card-disabled');
    }

    const icon = document.createElement('img');
    icon.className = 'version-image mod-image';
    icon.src = mod.icon_url || 'assets/images/java_icon.png';
    icon.onerror = () => { icon.src = 'assets/images/java_icon.png'; };

    const info = document.createElement('div');
    info.className = 'version-info';

    const headerRow = document.createElement('div');
    headerRow.className = 'version-header-row';

    const name = document.createElement('div');
    name.className = 'version-display';
    name.textContent = mod.mod_name || mod.name || 'Unknown Mod';

    const desc = document.createElement('div');
    desc.className = 'version-folder';
    desc.textContent = mod.description || mod.summary || '';

    headerRow.appendChild(name);
    info.appendChild(headerRow);
    info.appendChild(desc);

    // Version dropdown for installed mods
    if (isInstalled && Array.isArray(mod.versions) && mod.versions.length > 0) {
      const versionRow = document.createElement('div');
      versionRow.className = 'mod-version-row';

      const versionLabel = document.createElement('span');
      versionLabel.className = 'mod-version-label';
      versionLabel.textContent = 'Version:';

      const versionSelect = document.createElement('select');
      versionSelect.className = 'mod-version-select';
      mod.versions.forEach((v) => {
        const opt = document.createElement('option');
        opt.value = v.version_label;
        const loaderTag = v.mod_loader ? ` [${v.mod_loader}]` : '';
        opt.textContent = v.version_label + loaderTag;
        if (v.version_label === mod.active_version) opt.selected = true;
        versionSelect.appendChild(opt);
      });
      versionSelect.addEventListener('change', async (e) => {
        e.stopPropagation();
        try {
          const res = await api('/api/mods/set-active-version', 'POST', {
            mod_slug: mod.mod_slug,
            mod_loader: mod.mod_loader,
            version_label: versionSelect.value,
          });
          if (res && res.ok) {
            loadInstalledMods();
          }
        } catch (err) {
          console.error('Failed to set active version:', err);
        }
      });

      versionRow.appendChild(versionLabel);
      versionRow.appendChild(versionSelect);
      info.appendChild(versionRow);
    }

    const badgeRow = document.createElement('div');
    badgeRow.className = 'version-badge-row';

    if (isInstalled) {
      const stateBadge = document.createElement('span');
      if (mod.disabled) {
        stateBadge.className = 'version-badge paused';
        stateBadge.textContent = 'DISABLED';
      } else if (mod.is_imported) {
        stateBadge.className = 'version-badge imported';
        stateBadge.textContent = 'IMPORTED';
      } else {
        stateBadge.className = 'version-badge installed';
        stateBadge.textContent = 'INSTALLED';
      }
      badgeRow.appendChild(stateBadge);
    }

    // Show active version's mod_loader as badge
    if (isInstalled && mod.versions) {
      const activeVer = mod.versions.find(v => v.version_label === mod.active_version);
      if (activeVer && activeVer.mod_loader) {
        const loaderBadge = document.createElement('span');
        loaderBadge.className = 'version-badge lite';
        loaderBadge.textContent = String(activeVer.mod_loader).toUpperCase();
        badgeRow.appendChild(loaderBadge);
      }
    }

    if (!isInstalled) {
      const providerBadge = document.createElement('span');
      providerBadge.className = 'version-badge nonofficial';
      providerBadge.textContent = (mod.provider || modsState.provider || 'unknown').toUpperCase();
      badgeRow.appendChild(providerBadge);
    }

    const categories = Array.isArray(mod.categories) ? mod.categories : [];
    if (categories.length > 0) {
      const catBadge = document.createElement('span');
      catBadge.className = 'version-badge size';
      catBadge.textContent = String(categories[0] || '').slice(0, 18).toUpperCase();
      badgeRow.appendChild(catBadge);
    }

    // Delete icon button (placed before badges in the card row)
    const deleteIconContainer = document.createElement('div');
    deleteIconContainer.className = 'mod-card-delete-icon';
    if (isInstalled) {
      const delBtn = document.createElement('div');
      delBtn.className = 'icon-button';
      const delImg = document.createElement('img');
      delImg.alt = 'delete';
      delImg.src = 'assets/images/unfilled_delete.png';
      imageAttachErrorPlaceholder(delImg, 'assets/images/placeholder.png');
      delBtn.appendChild(delImg);
      delBtn.addEventListener('mouseenter', () => { delImg.src = 'assets/images/filled_delete.png'; });
      delBtn.addEventListener('mouseleave', () => { delImg.src = 'assets/images/unfilled_delete.png'; });
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteMod(mod);
      });
      deleteIconContainer.appendChild(delBtn);
    }

    const actions = document.createElement('div');
    actions.className = 'version-actions';

    if (isInstalled) {
      const toggleBtn = document.createElement('button');
      toggleBtn.className = mod.disabled ? 'primary' : 'mild';
      toggleBtn.textContent = mod.disabled ? 'Enable' : 'Disable';
      toggleBtn.onclick = (e) => {
        e.stopPropagation();
        toggleModDisabled(mod);
      };
      actions.appendChild(toggleBtn);
    }

    card.appendChild(icon);
    card.appendChild(info);
    if (isInstalled) card.appendChild(deleteIconContainer);
    card.appendChild(badgeRow);
    card.appendChild(actions);

    if (!isInstalled) {
      card.style.cursor = 'pointer';
      card.addEventListener('click', () => {
        showModDetailModal(mod);
      });
    }

    return card;
  };

  // --- Mod Detail Modal (replaces Install button) ---
  const showModDetailModal = async (mod) => {
    const modName = mod.name || mod.mod_name || 'Unknown Mod';
    const detailProvider = (mod.provider || modsState.provider || '').toLowerCase();

    const resolveDetailLink = (rawHref) => {
      if (!rawHref) return '';
      const href = String(rawHref).trim();
      if (!href) return '';
      if (href.startsWith('http://') || href.startsWith('https://')) return href;
      if (href.startsWith('//')) return `https:${href}`;
      if (href.startsWith('www.')) return `https://${href}`;
      if (href.startsWith('/')) {
        if (detailProvider === 'curseforge') return `https://www.curseforge.com${href}`;
        if (detailProvider === 'modrinth') return `https://modrinth.com${href}`;
      }
      return '';
    };

    const escapeHtml = (txt) => String(txt || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');

    const markdownInlineToHtml = (line) => {
      let out = escapeHtml(line);

      // Linked image: [![alt](img)](url)
      out = out.replace(/\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)/g,
        '<a href="$3"><img src="$2" alt="$1"></a>');
      // Image: ![alt](img)
      out = out.replace(/!\[([^\]]*)\]\(([^)]+)\)/g,
        '<img src="$2" alt="$1">');
      // Link: [text](url)
      out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
        '<a href="$2">$1</a>');

      // Strong / emphasis
      out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      out = out.replace(/__([^_]+)__/g, '<strong>$1</strong>');
      out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
      out = out.replace(/_([^_]+)_/g, '<em>$1</em>');

      // Inline code
      out = out.replace(/`([^`]+)`/g, '<code>$1</code>');

      return out;
    };

    const renderModrinthMarkdown = (md) => {
      const lines = String(md || '').replace(/\r\n/g, '\n').split('\n');
      const chunks = [];
      let listItems = [];
      let inCodeFence = false;
      let codeFenceLang = '';
      let codeFenceLines = [];

      const flushList = () => {
        if (!listItems.length) return;
        chunks.push(`<ul>${listItems.join('')}</ul>`);
        listItems = [];
      };

      const flushCodeFence = () => {
        if (!inCodeFence) return;
        const langClass = codeFenceLang ? ` class="language-${escapeHtml(codeFenceLang)}"` : '';
        chunks.push(`<pre class="mod-detail-codeblock"><code${langClass}>${escapeHtml(codeFenceLines.join('\n'))}</code></pre>`);
        inCodeFence = false;
        codeFenceLang = '';
        codeFenceLines = [];
      };

      for (const rawLine of lines) {
        const line = rawLine.trim();

        if (inCodeFence) {
          if (/^```/.test(line)) {
            flushCodeFence();
          } else {
            codeFenceLines.push(rawLine);
          }
          continue;
        }

        const fenceStart = line.match(/^```\s*([a-zA-Z0-9_+-]*)\s*$/);
        if (fenceStart) {
          flushList();
          inCodeFence = true;
          codeFenceLang = (fenceStart[1] || '').trim().toLowerCase();
          codeFenceLines = [];
          continue;
        }

        if (!line) {
          flushList();
          continue;
        }

        // Preserve trusted raw HTML block tags from Modrinth bodies so they
        // render correctly instead of being escaped inside <p>...</p>.
        if (/^<\/?(?:h[1-6]|p|ul|ol|li|hr|blockquote|pre|code|img|table|thead|tbody|tr|td|th|div|br|details|summary)\b/i.test(line)) {
          flushList();
          chunks.push(line);
          continue;
        }

        if (/^[-*_]{3,}$/.test(line)) {
          flushList();
          chunks.push('<hr>');
          continue;
        }

        const heading = line.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
          flushList();
          const level = heading[1].length;
          chunks.push(`<h${level}>${markdownInlineToHtml(heading[2])}</h${level}>`);
          continue;
        }

        const li = line.match(/^[-*]\s+(.+)$/);
        if (li) {
          listItems.push(`<li>${markdownInlineToHtml(li[1])}</li>`);
          continue;
        }

        flushList();
        chunks.push(`<p>${markdownInlineToHtml(line)}</p>`);
      }

      flushList();
      flushCodeFence();
      return chunks.join('');
    };

    // Build the modal content container
    const content = document.createElement('div');
    content.className = 'mod-detail-content';

    const loadingMsg = document.createElement('p');
    loadingMsg.textContent = 'Loading mod details...';
    loadingMsg.style.color = '#999';
    content.appendChild(loadingMsg);

    showMessageBox({
      title: modName,
      customContent: content,
      buttons: [{ label: 'Close' }],
    });

    // Fetch detail + versions in parallel
    try {
      const [detailRes, versionsRes] = await Promise.all([
        api('/api/mods/detail', 'POST', {
          provider: mod.provider || modsState.provider,
          mod_id: mod.mod_id,
        }),
        api('/api/mods/versions', 'POST', {
          provider: mod.provider || modsState.provider,
          mod_id: mod.mod_id,
          game_version: '',
          mod_loader: '',
        }),
      ]);

      content.innerHTML = '';

      // --- Description ---
      const description = (detailRes && detailRes.ok && detailRes.body) ? detailRes.body : (mod.description || mod.summary || '');
      if (description) {
        const descSection = document.createElement('div');
        descSection.className = 'mod-detail-description';
        // CurseForge body is HTML; Modrinth body is Markdown.
        if (detailProvider === 'modrinth') {
          descSection.innerHTML = renderModrinthMarkdown(description);
        } else if (description.includes('<') && description.includes('>')) {
          descSection.innerHTML = description;
        } else {
          descSection.textContent = description;
        }

        // Redirect all links to the system browser instead of navigating pywebview
        descSection.querySelectorAll('a[href]').forEach((a) => {
          a.setAttribute('target', '_blank');
          const resolvedHref = resolveDetailLink(a.getAttribute('href'));
          if (resolvedHref) a.setAttribute('data-external-url', resolvedHref);
          a.addEventListener('click', (ev) => {
            ev.preventDefault();
            const href = a.getAttribute('data-external-url') || resolveDetailLink(a.getAttribute('href'));
            if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
              window.open(href, '_blank');
            }
          });
        });

        content.appendChild(descSection);
      }

      // --- Gallery/Screenshots ---
      const gallery = (detailRes && detailRes.ok && Array.isArray(detailRes.gallery)) ? detailRes.gallery : [];
      const screenshots = (detailRes && detailRes.ok && Array.isArray(detailRes.screenshots)) ? detailRes.screenshots : [];
      const images = gallery.length > 0 ? gallery : screenshots;

      if (images.length > 0) {
        const galSection = document.createElement('div');
        galSection.className = 'mod-detail-gallery';

        const galTitle = document.createElement('h4');
        galTitle.textContent = 'Screenshots';
        galTitle.style.marginBottom = '8px';
        galSection.appendChild(galTitle);

        const galRow = document.createElement('div');
        galRow.className = 'mod-detail-gallery-row';

        images.slice(0, 6).forEach((img) => {
          const imgUrl = typeof img === 'string' ? img : (img.url || img.thumbnailUrl || '');
          if (!imgUrl) return;
          const imgEl = document.createElement('img');
          imgEl.src = imgUrl;
          imgEl.className = 'mod-detail-screenshot';
          imgEl.onerror = () => { imgEl.style.display = 'none'; };
          imgEl.title = 'Click to enlarge';
          imgEl.addEventListener('click', () => {
            let lightbox = document.getElementById('screenshot-lightbox');
            if (!lightbox) {
              lightbox = document.createElement('div');
              lightbox.id = 'screenshot-lightbox';
              lightbox.className = 'screenshot-lightbox';
              const lbImg = document.createElement('img');
              lbImg.className = 'screenshot-lightbox-img';
              lightbox.appendChild(lbImg);
              lightbox.addEventListener('click', () => { lightbox.classList.remove('active'); });
              document.body.appendChild(lightbox);
            }
            lightbox.querySelector('img').src = imgUrl;
            lightbox.classList.add('active');
          });
          galRow.appendChild(imgEl);
        });

        galSection.appendChild(galRow);
        content.appendChild(galSection);
      }

      // --- Stats ---
      if (detailRes && detailRes.ok) {
        const statsRow = document.createElement('div');
        statsRow.className = 'mod-detail-stats';
        const downloads = detailRes.downloads || mod.download_count || 0;
        const cats = Array.isArray(detailRes.categories) ? detailRes.categories : (mod.categories || []);
        statsRow.innerHTML = `<span>Downloads: ${Number(downloads).toLocaleString()}</span>`;
        if (cats.length > 0) {
          statsRow.innerHTML += ` <span>Categories: ${cats.join(', ')}</span>`;
        }
        content.appendChild(statsRow);
      }

      // --- Versions list with filters ---
      const allVersions = (versionsRes && versionsRes.ok && Array.isArray(versionsRes.versions)) ? versionsRes.versions : [];

      if (allVersions.length > 0) {
        const verSection = document.createElement('div');
        verSection.className = 'mod-detail-versions';

        const verTitle = document.createElement('h4');
        verTitle.textContent = `Versions (${allVersions.length})`;
        verTitle.style.marginBottom = '8px';
        verSection.appendChild(verTitle);

        // Filters row
        const filterRow = document.createElement('div');
        filterRow.className = 'mod-detail-version-filters';

        // Loader filter
        const loaderSet = new Set();
        allVersions.forEach((v) => {
          (v.loaders || []).forEach((l) => loaderSet.add(String(l).toLowerCase()));
        });
        const loaderFilter = document.createElement('select');
        loaderFilter.innerHTML = '<option value="">All Loaders</option>';
        Array.from(loaderSet).sort().forEach((l) => {
          const o = document.createElement('option');
          o.value = l;
          o.textContent = l.charAt(0).toUpperCase() + l.slice(1);
          loaderFilter.appendChild(o);
        });

        // Game version filter
        const gvSet = new Set();
        allVersions.forEach((v) => {
          (v.game_versions || []).forEach((g) => gvSet.add(g));
        });
        const gvFilter = document.createElement('select');
        gvFilter.innerHTML = '<option value="">All MC Versions</option>';
        Array.from(gvSet).sort((a, b) => b.localeCompare(a, undefined, { numeric: true })).forEach((g) => {
          const o = document.createElement('option');
          o.value = g;
          o.textContent = g;
          gvFilter.appendChild(o);
        });

        filterRow.appendChild(loaderFilter);
        filterRow.appendChild(gvFilter);

        // Pre-select dropdowns to match the active search filters
        const activeLoader = (modsState.modLoader || '').toLowerCase();
        const activeGV = modsState.gameVersion || '';
        if (activeLoader && loaderFilter.querySelector(`option[value="${activeLoader}"]`)) {
          loaderFilter.value = activeLoader;
        }
        if (activeGV && gvFilter.querySelector(`option[value="${activeGV}"]`)) {
          gvFilter.value = activeGV;
        }

        verSection.appendChild(filterRow);

        // Scrollable versions list
        const verList = document.createElement('div');
        verList.className = 'mod-detail-version-list';

        const renderVersionList = () => {
          verList.innerHTML = '';
          const selLoader = loaderFilter.value;
          const selGV = gvFilter.value;

          let filtered = allVersions;
          if (selLoader) {
            filtered = filtered.filter((v) => (v.loaders || []).some((l) => String(l).toLowerCase() === selLoader));
          }
          if (selGV) {
            filtered = filtered.filter((v) => (v.game_versions || []).includes(selGV));
          }

          if (filtered.length === 0) {
            verList.innerHTML = '<p style="text-align:center;color:#999;padding:8px;">No versions match filters</p>';
            return;
          }

          const recommendedIdx = (() => {
            let idx = filtered.findIndex((v) => (v.version_type || '').toLowerCase() === 'release');
            if (idx === -1) idx = filtered.findIndex((v) => (v.version_type || '').toLowerCase() === 'beta');
            if (idx === -1) idx = filtered.findIndex((v) => (v.version_type || '').toLowerCase() === 'alpha');
            return idx;
          })();

          filtered.forEach((ver, idx) => {
            const isRecommended = idx === recommendedIdx && recommendedIdx !== -1;
            const row = document.createElement('div');
            row.className = 'mod-detail-version-row' + (isRecommended ? ' recommended' : '');

            const verName = document.createElement('span');
            verName.className = 'mod-detail-version-name';
            verName.textContent = ver.version_number || ver.display_name || ver.file_name || '?';

            const verMeta = document.createElement('span');
            verMeta.className = 'mod-detail-version-meta';
            const gvText = (ver.game_versions || []).slice(0, 3).join(', ');
            const loaderText = (ver.loaders || []).join(', ');
            verMeta.textContent = [gvText, loaderText].filter(Boolean).join(' | ');

            const vtype = (ver.version_type || 'release').toLowerCase();
            const vtypeBadge = document.createElement('span');
            vtypeBadge.className = 'mod-version-type-badge mod-version-type-' + vtype;
            vtypeBadge.textContent = vtype === 'release' ? 'R' : vtype === 'beta' ? 'B' : 'A';
            vtypeBadge.title = vtype.charAt(0).toUpperCase() + vtype.slice(1);

            const installBtn = document.createElement('button');
            // Check if this version is already installed
            const versionStr = ver.version_number || ver.display_name || 'unknown';
            const isVersionInstalled = modsState.installedMods.some((m) =>
              m.mod_slug === (mod.mod_slug || mod.slug) &&
              m.versions && m.versions.some((iv) => iv.version_label === versionStr)
            );

            if (isVersionInstalled) {
              installBtn.className = 'important';
              installBtn.textContent = 'Reinstall';
            } else {
              installBtn.className = 'primary';
              installBtn.textContent = 'Install';
            }
            installBtn.style.fontSize = '11px';
            installBtn.style.padding = '3px 8px';
            installBtn.addEventListener('click', () => {
              // Determine mod_loader from version loaders or current filter
              const modLoader = selLoader || (ver.loaders && ver.loaders[0]) || modsState.modLoader || 'fabric';
              installMod(mod, ver, modLoader, installBtn);
            });

            row.appendChild(vtypeBadge);
            row.appendChild(verName);
            row.appendChild(verMeta);
            if (isRecommended) {
              const starImg = document.createElement('img');
              starImg.src = 'assets/images/filled_favorite.png';
              starImg.title = 'Recommended (latest release)';
              starImg.style.cssText = 'width:14px;height:14px;object-fit:contain;flex-shrink:0;';
              row.appendChild(starImg);
            }
            row.appendChild(installBtn);
            verList.appendChild(row);
          });
        };

        loaderFilter.addEventListener('change', renderVersionList);
        gvFilter.addEventListener('change', renderVersionList);
        renderVersionList();

        verSection.appendChild(verList);
        content.appendChild(verSection);
      } else {
        const noVer = document.createElement('p');
        noVer.textContent = 'No versions available for this mod.';
        noVer.style.color = '#999';
        content.appendChild(noVer);
      }
    } catch (err) {
      console.error('Failed to load mod details:', err);
      content.innerHTML = '<p style="color:#ff4141;">Failed to load mod details.</p>';
    }
  };

  const installMod = async (mod, version, modLoader, installBtn) => {
    try {
      if (installBtn) {
        installBtn.disabled = true;
        installBtn.textContent = 'Installing...';
      }

      const res = await api('/api/mods/install', 'POST', {
        provider: mod.provider || modsState.provider,
        mod_id: mod.mod_id,
        mod_slug: mod.mod_slug,
        mod_name: mod.name || mod.mod_name,
        mod_loader: modLoader || modsState.modLoader || 'fabric',
        download_url: version.download_url,
        file_name: version.file_name,
        description: mod.summary || mod.description || '',
        icon_url: mod.icon_url || '',
        version: version.version_number || version.display_name || 'unknown',
      });

      if (res && res.ok) {
        if (installBtn) {
          installBtn.disabled = false;
          installBtn.textContent = 'Installed';
          installBtn.className = '';
          installBtn.style.color = '#4ade80';
          installBtn.style.fontWeight = 'bold';
          installBtn.style.border = 'none';
          installBtn.style.background = 'transparent';
          installBtn.style.cursor = 'default';
        }
        loadInstalledMods();
      } else {
        if (installBtn) {
          installBtn.disabled = false;
          installBtn.textContent = 'Install';
          installBtn.className = 'primary';
        }
      }
    } catch (err) {
      console.error('Failed to install mod:', err);
      if (installBtn) {
        installBtn.disabled = false;
        installBtn.textContent = 'Install';
        installBtn.className = 'primary';
      }
    }
  };

  const toggleModDisabled = async (mod) => {
    const newState = !mod.disabled;

    // Prevent enabling a mod that is blocked by an active modpack
    if (!newState) {
      // Trying to enable — check if any active modpack includes this mod
      const blockingPack = modsState.installedModpacks.find((p) =>
        !p.disabled && (p.mods || []).some((pm) => pm.mod_slug === mod.mod_slug)
      );
      if (blockingPack) {
        showMessageBox({
          title: 'Cannot Enable',
          message: `This mod is managed by the modpack <strong>${blockingPack.name || blockingPack.slug}</strong>. Disable or delete that modpack first.`,
          buttons: [{ label: 'OK' }],
        });
        return;
      }
    }

    const doToggle = async () => {
      try {
        const res = await api('/api/mods/toggle', 'POST', {
          mod_slug: mod.mod_slug,
          mod_loader: mod.mod_loader,
          disabled: newState,
        });
        if (res && res.ok) {
          loadInstalledMods();
        } else {
          showMessageBox({
            title: 'Error',
            message: res.error || 'Failed to toggle mod.',
            buttons: [{ label: 'OK' }],
          });
        }
      } catch (err) {
        console.error('Failed to toggle mod:', err);
      }
    };

    doToggle();
  };

  const deleteMod = (mod) => {
    const versions = Array.isArray(mod.versions) ? mod.versions : [];

    const doDelete = async (versionLabel) => {
      try {
        const payload = { mod_slug: mod.mod_slug, mod_loader: mod.mod_loader };
        if (versionLabel) payload.version_label = versionLabel;

        const res = await api('/api/mods/delete', 'POST', payload);
        if (res && res.ok) {
          const what = versionLabel ? `${mod.mod_name} v${versionLabel}` : mod.mod_name;
          loadInstalledMods();
        } else {
          showMessageBox({
            title: 'Error',
            message: res.error || 'Failed to delete mod.',
            buttons: [{ label: 'OK' }],
          });
        }
      } catch (err) {
        console.error('Failed to delete mod:', err);
      }
    };

    if (versions.length > 1) {
      // Build a select dropdown so the user can pick which version (or all) to delete
      const content = document.createElement('div');

      const label = document.createElement('p');
      label.style.marginBottom = '8px';
      label.textContent = `${mod.mod_name} has ${versions.length} installed versions. Choose what to delete:`;

      const select = document.createElement('select');
      select.className = 'mod-version-select';
      select.style.cssText = 'width:100%;margin-top:4px;max-width:100%;';

      const allOpt = document.createElement('option');
      allOpt.value = '';
      allOpt.textContent = 'Delete entire mod (all versions)';
      select.appendChild(allOpt);

      versions.forEach((v) => {
        const opt = document.createElement('option');
        opt.value = v.version_label;
        const loaderTag = v.mod_loader ? ` [${v.mod_loader}]` : '';
        opt.textContent = `Delete version: ${v.version_label}${loaderTag}`;
        select.appendChild(opt);
      });

      content.appendChild(label);
      content.appendChild(select);

      showMessageBox({
        title: 'Delete Mod',
        customContent: content,
        buttons: [
          {
            label: 'Delete',
            classList: ['danger'],
            onClick: () => doDelete(select.value || null),
          },
          { label: 'Cancel' },
        ],
      });
    } else {
      showMessageBox({
        title: 'Delete Mod',
        message: `Are you sure you want to delete <strong>${mod.mod_name}</strong>? This cannot be undone!`,
        buttons: [
          { label: 'Delete', classList: ['danger'], onClick: () => doDelete(null) },
          { label: 'Cancel' },
        ],
      });
    }
  };

  // ---------------- Modpack Functions ----------------

  const createModpackCard = (pack) => {
    const card = document.createElement('div');
    card.className = 'version-card mod-card modpack-card section-installed unselectable';
    if (pack.disabled) card.classList.add('mod-card-disabled');

    const icon = document.createElement('img');
    icon.className = 'version-image mod-image';
    icon.src = pack.icon_url || 'assets/images/java_icon.png';
    icon.onerror = () => { icon.src = 'assets/images/java_icon.png'; };

    const info = document.createElement('div');
    info.className = 'version-info';

    const headerRow = document.createElement('div');
    headerRow.className = 'version-header-row';

    const name = document.createElement('div');
    name.className = 'version-display';
    name.textContent = pack.name || pack.slug || 'Unknown Modpack';

    const desc = document.createElement('div');
    desc.className = 'version-folder';
    desc.textContent = pack.description || '';

    headerRow.appendChild(name);
    info.appendChild(headerRow);
    info.appendChild(desc);

    const badgeRow = document.createElement('div');
    badgeRow.className = 'version-badge-row';

    const stateBadge = document.createElement('span');
    if (pack.disabled) {
      stateBadge.className = 'version-badge paused';
      stateBadge.textContent = 'DISABLED';
    } else {
      stateBadge.className = 'version-badge modpack';
      stateBadge.textContent = 'MODPACK';
    }
    badgeRow.appendChild(stateBadge);

    if (pack.mod_loader) {
      const loaderBadge = document.createElement('span');
      loaderBadge.className = 'version-badge lite';
      loaderBadge.textContent = String(pack.mod_loader).toUpperCase();
      badgeRow.appendChild(loaderBadge);
    }

    // Delete icon
    const deleteIconContainer = document.createElement('div');
    deleteIconContainer.className = 'mod-card-delete-icon';
    const delBtn = document.createElement('div');
    delBtn.className = 'icon-button';
    const delImg = document.createElement('img');
    delImg.alt = 'delete';
    delImg.src = 'assets/images/unfilled_delete.png';
    imageAttachErrorPlaceholder(delImg, 'assets/images/placeholder.png');
    delBtn.appendChild(delImg);
    delBtn.addEventListener('mouseenter', () => { delImg.src = 'assets/images/filled_delete.png'; });
    delBtn.addEventListener('mouseleave', () => { delImg.src = 'assets/images/unfilled_delete.png'; });
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteModpack(pack);
    });
    deleteIconContainer.appendChild(delBtn);

    // Actions
    const actions = document.createElement('div');
    actions.className = 'version-actions';
    const toggleBtn = document.createElement('button');
    toggleBtn.className = pack.disabled ? 'primary' : 'mild';
    toggleBtn.textContent = pack.disabled ? 'Enable' : 'Disable';
    toggleBtn.onclick = (e) => {
      e.stopPropagation();
      toggleModpackDisabled(pack);
    };
    actions.appendChild(toggleBtn);

    card.appendChild(icon);
    card.appendChild(info);
    card.appendChild(deleteIconContainer);
    card.appendChild(badgeRow);
    card.appendChild(actions);

    card.style.cursor = 'pointer';
    card.addEventListener('click', () => showModpackDetailModal(pack));

    return card;
  };

  const showModpackDetailModal = (pack) => {
    const content = document.createElement('div');
    content.className = 'mod-detail-content';

    if (pack.description) {
      const descEl = document.createElement('p');
      descEl.textContent = pack.description;
      descEl.style.color = '#ccc';
      descEl.style.marginBottom = '12px';
      content.appendChild(descEl);
    }

    const statsRow = document.createElement('div');
    statsRow.className = 'mod-detail-stats';
    statsRow.innerHTML = `<span>Loader: ${(pack.mod_loader || '').toUpperCase()}</span> <span>Version: ${pack.version || 'N/A'}</span> <span>Mods: ${(pack.mods || []).length}</span>`;
    content.appendChild(statsRow);

    const modsList = pack.mods || [];
    if (modsList.length > 0) {
      const modsSection = document.createElement('div');
      modsSection.style.marginTop = '12px';

      const modsTitle = document.createElement('h4');
      modsTitle.textContent = `Mods (${modsList.length})`;
      modsTitle.style.marginBottom = '8px';
      modsSection.appendChild(modsTitle);

      const modsListEl = document.createElement('div');
      modsListEl.className = 'mod-detail-version-list';

      modsList.forEach((m) => {
        const row = document.createElement('div');
        row.className = 'mod-detail-version-row';
        row.style.gap = '8px';

        const iconEl = document.createElement('img');
        iconEl.style.cssText = 'width:28px;height:28px;object-fit:cover;flex-shrink:0;';
        iconEl.src = m.icon_url || 'assets/images/java_icon.png';
        iconEl.onerror = () => { iconEl.src = 'assets/images/java_icon.png'; };

        const nameEl = document.createElement('span');
        nameEl.className = 'mod-detail-version-name';
        nameEl.textContent = m.mod_name || m.mod_slug || 'Unknown';

        const metaEl = document.createElement('span');
        metaEl.className = 'mod-detail-version-meta';
        metaEl.textContent = m.version_label || '';

        row.appendChild(iconEl);
        row.appendChild(nameEl);
        row.appendChild(metaEl);
        modsListEl.appendChild(row);
      });

      modsSection.appendChild(modsListEl);
      content.appendChild(modsSection);
    }

    showMessageBox({
      title: pack.name || pack.slug || 'Modpack',
      customContent: content,
      buttons: [{ label: 'Close' }],
    });
  };

  const toggleModpackDisabled = async (pack) => {
    const newState = !pack.disabled;
    try {
      const res = await api('/api/modpacks/toggle', 'POST', {
        slug: pack.slug,
        disabled: newState,
      });
      if (res && res.ok) {
        loadInstalledMods();
      } else {
        showMessageBox({
          title: 'Error',
          message: res.error || 'Failed to toggle modpack.',
          buttons: [{ label: 'OK' }],
        });
      }
    } catch (err) {
      console.error('Failed to toggle modpack:', err);
    }
  };

  const deleteModpack = (pack) => {
    showMessageBox({
      title: 'Delete Modpack',
      message: `Are you sure you want to delete modpack <strong>${pack.name || pack.slug}</strong>? This cannot be undone!`,
      buttons: [
        {
          label: 'Delete',
          classList: ['danger'],
          onClick: async () => {
            try {
              const res = await api('/api/modpacks/delete', 'POST', { slug: pack.slug });
              if (res && res.ok) {
                loadInstalledMods();
              } else {
                showMessageBox({
                  title: 'Error',
                  message: res.error || 'Failed to delete modpack.',
                  buttons: [{ label: 'OK' }],
                });
              }
            } catch (err) {
              console.error('Failed to delete modpack:', err);
            }
          },
        },
        { label: 'Cancel' },
      ],
    });
  };

  // --- Import Modpack Handler ---
  const handleImportModpack = (file) => {
    const formData = new FormData();
    formData.append('hlmp_file', file);

    fetch('/api/modpacks/import', { method: 'POST', body: formData })
      .then((r) => r.json())
      .then((result) => {
        if (result && result.ok) {
          let msg = `Successfully imported modpack <strong>${result.name || ''}</strong>.`;
          if (result.disabled_standalone && result.disabled_standalone.length > 0) {
            msg += `<br><br>The following standalone mods were disabled because they conflict with the modpack:<br>` +
              result.disabled_standalone.map((s) => `• ${s}`).join('<br>');
          }
          showMessageBox({
            title: 'Import Successful',
            message: msg,
            buttons: [{ label: 'OK' }],
          });
          loadInstalledMods();
        } else {
          showMessageBox({
            title: 'Import Error',
            message: result.error || 'Failed to import modpack.',
            buttons: [{ label: 'OK' }],
          });
        }
      })
      .catch((err) => {
        console.error('Failed to import modpack:', err);
        showMessageBox({
          title: 'Import Error',
          message: 'Network error while importing modpack.',
          buttons: [{ label: 'OK' }],
        });
      });
  };

  // --- Export Modpack Wizard (3-step) ---
  const showExportModpackWizard = () => {
    // Step 1: Loader selection
    const step1Content = document.createElement('div');
    const step1Label = document.createElement('p');
    step1Label.style.marginBottom = '8px';
    step1Label.textContent = 'Select the mod loader for this modpack:';

    const loaderSelect = document.createElement('select');
    loaderSelect.className = 'mod-version-select';
    loaderSelect.style.cssText = 'width:100%;margin-top:4px;max-width:100%;';
    ['Fabric', 'Forge'].forEach((l) => {
      const opt = document.createElement('option');
      opt.value = l.toLowerCase();
      opt.textContent = l;
      loaderSelect.appendChild(opt);
    });

    step1Content.appendChild(step1Label);
    step1Content.appendChild(loaderSelect);

    showMessageBox({
      title: 'Export Modpack',
      customContent: step1Content,
      buttons: [
        {
          label: 'Next',
          classList: ['primary'],
          onClick: () => showExportStep2(loaderSelect.value),
        },
        { label: 'Cancel' },
      ],
    });
  };

  const showExportStep2 = (modLoader) => {
    // Step 2: Mod selection
    const modsForLoader = modsState.installedMods.filter(
      (m) => (m.mod_loader || '').toLowerCase() === modLoader
    );

    if (modsForLoader.length === 0) {
      showMessageBox({
        title: 'Export Modpack',
        message: `No ${modLoader} mods installed. Install some mods first.`,
        buttons: [{ label: 'OK' }],
      });
      return;
    }

    const step2Content = document.createElement('div');
    const step2Label = document.createElement('p');
    step2Label.style.marginBottom = '8px';
    step2Label.textContent = `Select mods to include (${modsForLoader.length} ${modLoader} mods available):`;
    step2Content.appendChild(step2Label);

    const selectAll = document.createElement('label');
    selectAll.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px;cursor:pointer;font-size:12px;color:#9ca3af;';
    const selectAllCb = document.createElement('input');
    selectAllCb.type = 'checkbox';
    selectAll.appendChild(selectAllCb);
    selectAll.appendChild(document.createTextNode('Select All'));
    step2Content.appendChild(selectAll);

    const modListEl = document.createElement('div');
    modListEl.style.cssText = 'max-height:300px;overflow-y:auto;border:1px solid #1f2937;padding:8px;';

    const modEntries = [];

    modsForLoader.forEach((mod) => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid #1f2937;';

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = true;

      const label = document.createElement('span');
      label.style.cssText = 'flex:1;font-size:13px;color:#e5e7eb;';
      label.textContent = mod.mod_name || mod.mod_slug;

      const versionSel = document.createElement('select');
      versionSel.className = 'mod-version-select';
      versionSel.style.cssText = 'max-width:140px;font-size:11px;';
      (mod.versions || []).forEach((v) => {
        const opt = document.createElement('option');
        opt.value = v.version_label;
        opt.textContent = v.version_label;
        if (v.version_label === mod.active_version) opt.selected = true;
        versionSel.appendChild(opt);
      });

      row.appendChild(cb);
      row.appendChild(label);
      row.appendChild(versionSel);
      modListEl.appendChild(row);

      modEntries.push({ mod, checkbox: cb, versionSelect: versionSel });
    });

    selectAllCb.addEventListener('change', () => {
      modEntries.forEach((e) => { e.checkbox.checked = selectAllCb.checked; });
    });

    step2Content.appendChild(modListEl);

    showMessageBox({
      title: 'Export Modpack',
      customContent: step2Content,
      buttons: [
        {
          label: 'Back',
          onClick: () => showExportModpackWizard(),
        },
        {
          label: 'Next',
          classList: ['primary'],
          onClick: () => {
            const selected = modEntries
              .filter((e) => e.checkbox.checked)
              .map((e) => ({
                mod_slug: e.mod.mod_slug,
                version_label: e.versionSelect.value,
                mod_name: e.mod.mod_name || e.mod.mod_slug,
              }));
            if (selected.length === 0) {
              showMessageBox({
                title: 'Export Modpack',
                message: 'Select at least one mod.',
                buttons: [{ label: 'OK', onClick: () => showExportStep2(modLoader) }],
              });
              return;
            }
            showExportStep3(modLoader, selected);
          },
        },
        { label: 'Cancel' },
      ],
    });
  };

  const showExportStep3 = (modLoader, selectedMods) => {
    const step3Content = document.createElement('div');

    const makeField = (labelText, inputType, maxLen, placeholder) => {
      const wrap = document.createElement('div');
      wrap.style.marginBottom = '10px';
      const lbl = document.createElement('label');
      lbl.style.cssText = 'display:block;font-size:12px;color:#9ca3af;margin-bottom:4px;';
      lbl.textContent = labelText;
      wrap.appendChild(lbl);
      if (inputType === 'textarea') {
        const ta = document.createElement('textarea');
        ta.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;background:#3c3f41;border:1px solid #1f2937;color:#e5e7eb;resize:vertical;min-height:60px;';
        ta.maxLength = maxLen;
        ta.placeholder = placeholder || '';
        wrap.appendChild(ta);
        return { wrap, input: ta };
      }
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;background:#3c3f41;border:1px solid #1f2937;color:#e5e7eb;';
      inp.maxLength = maxLen;
      inp.placeholder = placeholder || '';
      wrap.appendChild(inp);
      return { wrap, input: inp };
    };

    const nameField = makeField('Modpack Name (required, 1-64 chars)', 'text', 64, 'My Modpack');
    const versionField = makeField('Version (required, 1-16 chars)', 'text', 16, '1.0.0');
    const descField = makeField('Description (optional)', 'textarea', 8192, 'A modpack description...');

    step3Content.appendChild(nameField.wrap);
    step3Content.appendChild(versionField.wrap);
    step3Content.appendChild(descField.wrap);

    // Image upload
    const imgWrap = document.createElement('div');
    imgWrap.style.marginBottom = '10px';
    const imgLabel = document.createElement('label');
    imgLabel.style.cssText = 'display:block;font-size:12px;color:#9ca3af;margin-bottom:4px;';
    imgLabel.textContent = 'Modpack Icon (optional, square PNG recommended)';
    imgWrap.appendChild(imgLabel);

    const imgRow = document.createElement('div');
    imgRow.style.cssText = 'display:flex;align-items:center;gap:10px;';

    const imgPreview = document.createElement('img');
    imgPreview.style.cssText = 'width:64px;height:64px;object-fit:cover;border:1px solid #1f2937;display:none;';

    const imgInput = document.createElement('input');
    imgInput.type = 'file';
    imgInput.accept = 'image/png,image/jpeg';
    imgInput.style.fontSize = '12px';

    let imageBase64 = null;
    imgInput.addEventListener('change', () => {
      const file = imgInput.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        imageBase64 = e.target.result.split(',')[1]; // strip data:... prefix
        imgPreview.src = e.target.result;
        imgPreview.style.display = 'block';
      };
      reader.readAsDataURL(file);
    });

    imgRow.appendChild(imgPreview);
    imgRow.appendChild(imgInput);
    imgWrap.appendChild(imgRow);
    step3Content.appendChild(imgWrap);

    const summary = document.createElement('p');
    summary.style.cssText = 'font-size:12px;color:#9ca3af;margin-top:8px;';
    summary.textContent = `${selectedMods.length} mod${selectedMods.length !== 1 ? 's' : ''} selected · ${modLoader}`;
    step3Content.appendChild(summary);

    showMessageBox({
      title: 'Export Modpack',
      customContent: step3Content,
      buttons: [
        {
          label: 'Back',
          onClick: () => showExportStep2(modLoader),
        },
        {
          label: 'Export',
          classList: ['primary'],
          onClick: async () => {
            const packName = nameField.input.value.trim();
            const packVersion = versionField.input.value.trim();
            const packDesc = descField.input.value.trim();

            if (!packName || packName.length > 64) {
              showMessageBox({ title: 'Error', message: 'Name must be 1-64 characters.', buttons: [{ label: 'OK', onClick: () => showExportStep3(modLoader, selectedMods) }] });
              return;
            }
            if (/[<>:"/\\|?*]/.test(packName)) {
              showMessageBox({ title: 'Error', message: 'Name contains forbidden characters.', buttons: [{ label: 'OK', onClick: () => showExportStep3(modLoader, selectedMods) }] });
              return;
            }
            if (!packVersion || packVersion.length > 16) {
              showMessageBox({ title: 'Error', message: 'Version must be 1-16 characters.', buttons: [{ label: 'OK', onClick: () => showExportStep3(modLoader, selectedMods) }] });
              return;
            }

            try {
              const res = await api('/api/modpacks/export', 'POST', {
                name: packName,
                version: packVersion,
                description: packDesc,
                mod_loader: modLoader,
                mods: selectedMods,
                image_data: imageBase64 || null,
              });

              if (res && res.ok && res.hlmp_data) {
                const fileName = res.filename || `${packName}.hlmp`;
                const bytes = Uint8Array.from(atob(res.hlmp_data), c => c.charCodeAt(0));
                const blob = new Blob([bytes], { type: 'application/octet-stream' });

                // Use showSaveFilePicker for a native Save As dialog if available
                if (window.showSaveFilePicker) {
                  try {
                    const fileHandle = await window.showSaveFilePicker({
                      suggestedName: fileName,
                      types: [{
                        description: 'Histolauncher Modpack (.hlmp)',
                        accept: { 'application/octet-stream': ['.hlmp'] },
                      }],
                    });
                    const writable = await fileHandle.createWritable();
                    await writable.write(blob);
                    await writable.close();
                  } catch (saveErr) {
                    // User cancelled the dialog — do nothing
                    if (saveErr.name !== 'AbortError') console.error('Save failed:', saveErr);
                    return;
                  }
                } else {
                  // Fallback: browser auto-download to default Downloads folder
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = fileName;
                  document.body.appendChild(a);
                  a.click();
                  document.body.removeChild(a);
                  URL.revokeObjectURL(url);
                }

                showMessageBox({
                  title: 'Export Successful',
                  message: `Modpack <strong>${packName}</strong> exported successfully.`,
                  buttons: [{ label: 'OK' }],
                });
              } else {
                showMessageBox({
                  title: 'Export Error',
                  message: (res && res.error) || 'Failed to export modpack.',
                  buttons: [{ label: 'OK' }],
                });
              }
            } catch (err) {
              console.error('Failed to export modpack:', err);
              showMessageBox({
                title: 'Export Error',
                message: 'Network error while exporting modpack.',
                buttons: [{ label: 'OK' }],
              });
            }
          },
        },
        { label: 'Cancel' },
      ],
    });
  };

  // ---------------- Global init ----------------

  document.addEventListener('DOMContentLoaded', () => {
    // Intercept all external link clicks globally so pywebview never navigates away
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

      // --- Recognise mod-page links and open them inline ---
      // CurseForge: https://www.curseforge.com/minecraft/mc-mods/{slug}
      const cfMatch = normalizedHref.match(/curseforge\.com\/minecraft\/mc-mods\/([^/?#]+)/i);
      if (cfMatch) {
        const slug = cfMatch[1];
        const displayName = slug.charAt(0).toUpperCase() + slug.slice(1);
        try {
          const searchRes = await api('/api/mods/search', 'POST', {
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
              mod_id: picked.mod_id,
              provider: 'curseforge',
              name: picked.name || displayName,
            });
            return;
          }
        } catch (e) {
          console.error('Failed to resolve CurseForge slug link:', e);
        }

        // Fallback: open in external browser if we cannot resolve the slug.
        window.open(normalizedHref, '_blank');
        return;
      }
      // Modrinth: https://modrinth.com/mod/{slug}  or  https://modrinth.com/plugin/{slug}
      const mrMatch = normalizedHref.match(/modrinth\.com\/(?:mod|plugin|datapack)\/([^/?#]+)/i);
      if (mrMatch) {
        const slug = mrMatch[1];
        const displayName = slug.charAt(0).toUpperCase() + slug.slice(1);
        showModDetailModal({ mod_id: slug, provider: 'modrinth', name: displayName });
        return;
      }

      // All other external links — open in system browser
      window.open(normalizedHref, '_blank');
    }, true);

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
    initModsPage();
    updateSettingsValidationUI();
    init();
  });
})();
