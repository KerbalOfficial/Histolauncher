// ui/modules/install.js

import { state } from './state.js';
import {
  INSTALL_POLL_MS_ACTIVE,
  INSTALL_POLL_MS_PAUSED,
  INSTALL_POLL_MS_BACKOFF_BASE,
  INSTALL_POLL_MS_BACKOFF_MAX,
} from './config.js';

const _deps = {};
for (const k of ['debug', 'init', 'loadAvailableVersions', 'refreshInitialData', 'renderAllVersionSections']) {
  Object.defineProperty(_deps, k, {
    configurable: true,
    enumerable: true,
    get() { throw new Error(`install.js: dep "${k}" was not configured. Call setInstallDeps() first.`); },
  });
}

export const setInstallDeps = (deps) => {
  for (const k of Object.keys(deps)) {
    Object.defineProperty(_deps, k, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: deps[k],
    });
  }
};

// ---------------- Install handling ----------------

export const startInstallForFolder = async (folder, category, fullDownloadMode, options = {}) => {
  if (!folder || typeof folder !== 'string' || folder.trim().length === 0) {
    console.error('startInstallForFolder: missing folder');
    return null;
  }
  if (!category || typeof category !== 'string') {
    category = 'release';
  }

  const fullFlag = !!fullDownloadMode;
  const forceRedownload = !!(options && options.forceRedownload);
  const baseKey = `${category.toLowerCase()}/${folder}`;
  const extraFlags = forceRedownload ? { force_redownload: true, redownload: true } : {};

  const payloads = [
    { version: folder, category, full_assets: fullFlag, ...extraFlags },
    { folder, category, full_assets: fullFlag, ...extraFlags },
    { version_key: baseKey, full_assets: fullFlag, ...extraFlags },
    { key: baseKey, full_assets: fullFlag, ...extraFlags },
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

export const cancelInstallForVersionKey = async (versionKeyEncoded) => {
  if (!versionKeyEncoded) return;
  try {
    const res = await fetch(`/api/cancel/${versionKeyEncoded}`, {
      method: 'POST',
    });
    const json = await res.json().catch(() => null);
    _deps.debug('cancel response', json);

    state.versionsList = state.versionsList.map((x) => {
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

    if (state.activeInstallPollers[versionKeyEncoded]) {
      if (typeof state.activeInstallPollers[versionKeyEncoded] === 'function') {
        state.activeInstallPollers[versionKeyEncoded]();
      } else {
        clearTimeout(state.activeInstallPollers[versionKeyEncoded]);
      }
      delete state.activeInstallPollers[versionKeyEncoded];
    }

    // Rehydrate from backend so cards move to correct sections immediately.
    await _deps.init();
  } catch (e) {
    console.warn('cancel failed', e);
  }
};

export const pauseInstallForVersionKey = async (versionKeyEncoded) => {
  if (!versionKeyEncoded) return;
  try {
    const res = await fetch(`/api/pause/${versionKeyEncoded}`, {
      method: 'POST',
    });
    const json = await res.json().catch(() => null);
    _deps.debug('pause response', json);
  } catch (e) {
    console.warn('pause failed', e);
  }
};

export const resumeInstallForVersionKey = async (versionKeyEncoded) => {
  if (!versionKeyEncoded) return;
  try {
    const res = await fetch(`/api/resume/${versionKeyEncoded}`, {
      method: 'POST',
    });
    const json = await res.json().catch(() => null);
    _deps.debug('resume response', json);
  } catch (e) {
    console.warn('resume failed', e);
  }
};

export const handleInstallClick = async (v, card, installBtn, fullDownloadMode, options = {}) => {
  const folder = v.folder;
  const category = v.category || 'Release';
  const forceRedownload = !!(options && options.forceRedownload);

  if (!folder || !folder.trim()) {
      installBtn.textContent = 'Error';
      setTimeout(() => {
          const isLowDataMode = state.settingsState.low_data_mode === "1";
            installBtn.textContent = forceRedownload ? 'Redownload' : (isLowDataMode ? 'Quick Download' : 'Full Download');
      }, 1500);
      return;
  }

  installBtn.disabled = true;
  installBtn.textContent = 'Starting...';
  card.classList.add('installing');

  const rawVersionKey = await startInstallForFolder(
      folder,
      category,
      fullDownloadMode,
      { forceRedownload }
  );
  if (!rawVersionKey) {
    card.classList.remove('installing');
    installBtn.disabled = false;
    installBtn.textContent = forceRedownload ? 'Redownload' : 'Download';
    return;
  }

  const encodedKey = encodeURIComponent(rawVersionKey);
  const normalizedInstallKey = `${String(category || '').toLowerCase()}/${folder}`;

  const installingVersion = {
    ...v,
    _installKey: encodedKey,
    installing: true,
    full_install: fullDownloadMode,
    _progressText: 'Starting...',
    _progressOverall: 0,
  };

  let convertedInstallingCard = false;
  const toInstallingCard = (x) => ({
    ...x,
    installed: false,
    installing: true,
    is_remote: false,
    source: 'installing',
    _installKey: encodedKey,
    full_install: fullDownloadMode,
    image_url: x.image_url || v.image_url,
    _progressText: 'Starting...',
    _progressOverall: 0,
  });

  state.versionsList = state.versionsList.map((x) => {
    const key = `${String(x.category || '').toLowerCase()}/${x.folder || ''}`;
    if (key !== normalizedInstallKey) return x;

    if (x.is_remote) {
      return {
        ...x,
        installing: false,
        _installKey: null,
        _progressText: null,
        _progressOverall: 0,
        suppress_available_while_installing: true,
      };
    }

    if (!convertedInstallingCard && (!forceRedownload || x.installed)) {
      convertedInstallingCard = true;
      return toInstallingCard(x);
    }

    return x;
  });

  if (!convertedInstallingCard) {
    state.versionsList.push(toInstallingCard(installingVersion));
  }

  _deps.renderAllVersionSections();
  startPollingForInstall(encodedKey, installingVersion);
};

// ---------------- Polling for install progress ----------------

export const updateVersionInListByKey = (versionKeyEncoded, updater) => {
  const decodedKey = decodeURIComponent(versionKeyEncoded);
  state.versionsList = state.versionsList.map((x) => {
    const matchesKey =
      (x._installKey && x._installKey === versionKeyEncoded) ||
      (x.installing && `${x.category}/${x.folder}` === decodedKey);
    return matchesKey ? updater(x) : x;
  });
};

export const findVersionByInstallKey = (versionKeyEncoded) => {
  const byInstallKey = state.versionsList.find((x) => x._installKey === versionKeyEncoded);
  if (byInstallKey) return byInstallKey;
  const decodedKey = decodeURIComponent(versionKeyEncoded);
  return state.versionsList.find((x) => x.installing && `${x.category}/${x.folder}` === decodedKey);
};

export const updateCardProgressUI = (vMeta, pct, text, options = {}) => {
  const { paused, statusLabel, pausedColor } = options;
  const cardId = vMeta._cardFullId || `${vMeta.category}/${vMeta.folder}`;
  const card = document.querySelector(
    `.version-card[data-full-id="${cardId}"]`
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

export const refreshVersionsAfterTerminalInstall = async () => {
  try {
    const refreshed = await _deps.refreshInitialData({ preserveAvailableData: true });
    const loadedAvailable = await _deps.loadAvailableVersions({ reload: true });
    if (!refreshed && !loadedAvailable) _deps.renderAllVersionSections();
  } catch (e) {
    _deps.renderAllVersionSections();
  }
};

export const startPollingForInstall = (versionKeyEncoded, vMeta) => {
  if (!versionKeyEncoded) return;
  if (state.activeInstallPollers[versionKeyEncoded]) return;

  state.activeInstallPollers[versionKeyEncoded] = true; // placeholder

  const startStream = () => {
    const eventSource = new EventSource(`/api/stream/install/${versionKeyEncoded}`);

    const cleanup = () => {
      eventSource.close();
      delete state.activeInstallPollers[versionKeyEncoded];
    };
    state.activeInstallPollers[versionKeyEncoded] = cleanup; // store cleanup func

    eventSource.onmessage = async (event) => {
      try {
        const s = JSON.parse(event.data);
        if (!s) return;

        const status = s.status;

        const pct = s.overall_percent || 0;
        const bytesDone = s.bytes_done || 0;
        const bytesTotal = s.bytes_total || 0;

        const mbDone = bytesDone / (1024 * 1024);
        const mbTotal = bytesTotal / (1024 * 1024);

        let text = '';
        let keepPolling = true;

        const currentVMeta = findVersionByInstallKey(versionKeyEncoded);
        if (!currentVMeta) {
          cleanup();
          return;
        }

        const previousPct = Number(currentVMeta._progressOverall || 0);
        const previousTotal = Number(currentVMeta._progressBytesTotal || 0);
        let stablePct = Number(pct || 0);
        if (bytesTotal <= previousTotal) {
          stablePct = Math.max(previousPct, stablePct);
        }

        if (status === 'downloading' || status === 'installing' || status === 'running' || status === 'starting') {
          currentVMeta.paused = false;
          const wholePct = Math.round(stablePct);
          const roundedMbDone = Math.round(mbDone);
          const roundedMbTotal = Math.round(mbTotal);
          text =
            bytesTotal > 0
              ? `${wholePct}% (${roundedMbDone} MB / ${roundedMbTotal} MB)`
              : bytesDone > 0
              ? `${wholePct}% (${roundedMbDone} MB)`
              : `${wholePct}%`;

          updateVersionInListByKey(versionKeyEncoded, (x) => ({
            ...x,
            paused: false,
            _progressText: text,
            _progressOverall: stablePct,
            _progressBytesTotal: bytesTotal,
          }));

          updateCardProgressUI(currentVMeta, stablePct, text, {
            paused: false,
            statusLabel: 'Installing',
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
        }

        const renderPct = status === 'installed' ? 100 : stablePct;
        if (status !== 'downloading' && status !== 'starting' && status !== 'paused') {
          updateCardProgressUI(currentVMeta, renderPct, text, {
            keepInstalling: keepPolling,
          });
        }

        if (!keepPolling) {
          cleanup();
          if (status === 'installed' || status === 'failed' || status === 'cancelled') {
            await refreshVersionsAfterTerminalInstall();
          }
        }
      } catch (error) {
        console.warn('install stream update failed', error);
      }
    };

    eventSource.onerror = (e) => {
      // Stream error handling
    };
  };

  startStream();
};
