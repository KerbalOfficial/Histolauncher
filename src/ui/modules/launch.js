// ui/modules/launch.js

import { state } from './state.js';
import { api } from './api.js';
import { getEl, setText, setHTML } from './dom-utils.js';
import {
  showMessageBox,
  showLoadingOverlay,
  hideLoadingOverlay,
  setLoadingOverlayText,
} from './modal.js';
import { LOADER_UI_ORDER, getLoaderUi, unicodeList } from './config.js';
import { initTooltips } from './tooltips.js';
import { installJavaRuntime } from './java-installer.js';
import { escapeInfoHtml } from './string-utils.js';
import { t } from './i18n.js';

const _deps = {};
for (const k of ['debug', 'getCustomStorageDirectoryError', 'getCustomStorageDirectoryPath', 'normalizeStorageDirectoryMode', 'refreshCustomStorageDirectoryValidation', 'updateHomeInfo']) {
  Object.defineProperty(_deps, k, {
    configurable: true,
    enumerable: true,
    get() { throw new Error(`launch.js: dep "${k}" was not configured. Call setLaunchDeps() first.`); },
  });
}

export const setLaunchDeps = (deps) => {
  for (const k of Object.keys(deps)) {
    Object.defineProperty(_deps, k, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: deps[k],
    });
  }
};

// -------- Settings Validation --------

export const validateRAMFormat = (ramStr) => {
  if (!ramStr || !ramStr.trim()) return false;
  // Match: digits only, or digits followed by single character (K, M, G, T)
  const match = ramStr.trim().match(/^(\d+)([KMGT])?$/i);
  return !!match;
};

export const parseRAMValue = (ramStr) => {
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

export const validateSettings = () => {
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

  if (_deps.normalizeStorageDirectoryMode(state.settingsState.storage_directory) === 'custom') {
    const storageError = _deps.getCustomStorageDirectoryError();
    if (storageError) {
      errors.storage_directory = true;
    }
  }

  return errors;
};

export const updateSettingsValidationUI = () => {
  const errors = validateSettings();

  // Helper to set indicator tooltip based on error type
  const setIndicatorTooltip = (indicator, errorKey, value) => {
    if (!indicator) return;

    let tooltip = '';
    if (errorKey === 'username') {
      const len = value.length;
      if (len === 0) {
        tooltip = t('settings.validation.username.empty');
      } else if (len < 3) {
        tooltip = t('settings.validation.username.tooShort', { length: len });
      } else if (len > 16) {
        tooltip = t('settings.validation.username.tooLong', { length: len });
      }
    } else if (errorKey === 'min_ram') {
      if (!value || value.trim() === '') {
        tooltip = t('settings.validation.ram.minEmpty');
      } else if (!validateRAMFormat(value)) {
        tooltip = t('settings.validation.ram.invalidFormat', { example: '16M' });
      } else {
        const minVal = parseRAMValue(value);
        if (minVal < 0) {
          tooltip = t('settings.validation.ram.minNegative');
        }
      }
    } else if (errorKey === 'max_ram') {
      if (!value || value.trim() === '') {
        tooltip = t('settings.validation.ram.maxEmpty');
      } else if (!validateRAMFormat(value)) {
        tooltip = t('settings.validation.ram.invalidFormat', { example: '4096M' });
      } else {
        const maxVal = parseRAMValue(value);
        const minRamStr = (getEl('settings-min-ram')?.value || '').trim();
        if (maxVal < 1) {
          tooltip = t('settings.validation.ram.maxTooLow');
        } else if (minRamStr && validateRAMFormat(minRamStr)) {
          const minVal = parseRAMValue(minRamStr);
          if (minVal > maxVal) {
            tooltip = t('settings.validation.ram.maxGreaterThanMin', { min: minRamStr, max: value });
          }
        }
      }
    } else if (errorKey === 'storage_directory') {
      tooltip = _deps.getCustomStorageDirectoryError();
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

  const storageSelect = getEl('settings-storage-dir');
  const storageRow = getEl('settings-storage-row');
  const storagePath = getEl('settings-storage-path');
  if (storageSelect && storageRow) {
    const indicator = storageRow.querySelector('.invalid-indicator');
    if (errors.storage_directory) {
      storageSelect.classList.add('invalid-setting');
      storageRow.classList.add('row-invalid');
      indicator?.classList.remove('hidden');
      setIndicatorTooltip(
        indicator,
        'storage_directory',
        _deps.getCustomStorageDirectoryPath()
      );
      storagePath?.classList.add('settings-storage-path-invalid');
    } else {
      storageSelect.classList.remove('invalid-setting');
      storageRow.classList.remove('row-invalid');
      indicator?.classList.add('hidden');
      storagePath?.classList.remove('settings-storage-path-invalid');
    }
  }

  // Update launch button disabled state
  const launchBtn = getEl('launch-btn');
  if (launchBtn) {
    launchBtn.disabled = Object.keys(errors).length > 0;
  }

  // Update home info to show validation warnings
  _deps.updateHomeInfo();

  // Reinitialize tooltips in case indicators have changed visibility
  initTooltips();
};

export const initLaunchButton = () => {
  const launchBtn = getEl('launch-btn');
  if (!launchBtn) return;

  launchBtn.addEventListener('click', async () => {
    if (_deps.normalizeStorageDirectoryMode(state.settingsState.storage_directory) === 'custom') {
      await _deps.refreshCustomStorageDirectoryValidation();
    }

    const validationErrors = validateSettings();
    if (Object.keys(validationErrors).length > 0) {
      setText('status', `${unicodeList.warning} ${t('launch.status.fixInvalidSettings')}`);
      return;
    }

    if (!state.selectedVersion) {
      setText(
        'status',
        `${unicodeList.warning} ${t('launch.status.selectVersionFirst')}`
      );
      return;
    }

    const meta = state.versionsList.find(
      (v) => `${v.category}/${v.folder}` === state.selectedVersion
    );
    if (!meta) {
      setText('status', `${unicodeList.warning} ${t('launch.status.versionMetadataMissing')}`);
      return;
    }

    if (meta.raw && meta.raw.launch_disabled) {
      const msg =
        meta.raw.launch_disabled_message ||
        `${unicodeList.warning} ${t('launch.status.versionCannotLaunch')}`;
      window.alert(msg);
      setText('status', `${unicodeList.warning} ${t('launch.status.failedToLaunch', { message: msg })}`);
      return;
    }

    const [category, folder] = state.selectedVersion.split('/');
    let selectedLoader = null;

    try {
      const loaderData = await api(`/api/loaders-installed/${category}/${folder}`);
      if (loaderData && loaderData.ok && loaderData.installed) {
        const installed = loaderData.installed;
        const hasLoaders = LOADER_UI_ORDER.some(
          (loaderType) => installed[loaderType] && installed[loaderType].length > 0
        );

        if (hasLoaders) {
          selectedLoader = await promptLoaderSelection(installed);
          if (selectedLoader === false) return;
        }
      }
    } catch (err) {
      console.warn('Failed to check loaders:', err);
    }

    showLoadingOverlay(t('launch.launching'), {
      image: 'assets/images/nether_block.gif',
      boxClassList: ['activity-box'],
    });

    const username = state.settingsState.username || 'Player';
    const launchData = { category, folder, username };
    if (selectedLoader) {
      launchData.loader = selectedLoader.type;
      launchData.loader_version = selectedLoader.version;
    }

    const res = await api('/api/launch', 'POST', launchData);

    if (!res.ok) {
      if (res.message && res.message.includes('\n')) {
        setHTML('status', res.message.replace(/\n/g, '<br>'));
      } else {
        setText('status', res.message);
      }
      hideLoadingOverlay();
      const javaDownloadMajor = Number.parseInt(
        String(res.java_download_major || res.java_required_major || ''),
        10,
      ) || 0;
      if (res.log_path) {
        await showCrashDialog(null, res.log_path, res.message || '');
      } else if (javaDownloadMajor > 0) {
        showMessageBox({
          title: t('launch.javaRequiredTitle'),
          message: String(res.message || t('launch.javaRequiredMessage')).replace(/\n/g, '<br>'),
          buttons: [
            {
              label: t('launch.downloadJava'),
              classList: ['important'],
              onClick: () => installJavaRuntime(javaDownloadMajor),
            },
            { label: t('common.ok'), onClick: () => {} },
          ],
        });
      }
      return;
    }

    const processId = res.process_id;
    let pollAttempts = 0;
    const maxPollAttempts = 600;
    let overlayClosedByWindow = false;

    const pollWindowVisibility = async () => {
      if (overlayClosedByWindow) return;

      try {
        const windowRes = await api(`/api/game_window_visible/${processId}`);
          _deps.debug(`[Window] Visibility check:`, windowRes);

        if (windowRes.ok && windowRes.visible) {
          _deps.debug('[Window] Game window is visible, closing overlay');
          overlayClosedByWindow = true;
          hideLoadingOverlay();
          setText('status', t('launch.status.minecraftOpened'));
          return;
        }
      } catch (err) {
        _deps.debug('[Window] Could not check visibility (normal if not on Windows):', err.message);
      }

      if (pollAttempts < maxPollAttempts && !overlayClosedByWindow) {
        setTimeout(pollWindowVisibility, 2000);
      }
    };

    const pollGameStatus = async () => {
      try {
        const statusRes = await api(`/api/launch_status/${processId}`);
        _deps.debug(`[Polling] Attempt ${pollAttempts}, Response:`, statusRes);

        if (statusRes.ok && statusRes.status === 'running') {
          pollAttempts++;

          if (!overlayClosedByWindow) {
            const elapsed = Math.floor(statusRes.elapsed || 0);
            const minutes = Math.floor(elapsed / 60);
            const seconds = elapsed % 60;
            const timeStr = minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
            setLoadingOverlayText(t('launch.launchingTimed', { time: timeStr }));
            setText('status', t('launch.launchingTimed', { time: timeStr }));
          }

          if (pollAttempts < maxPollAttempts) {
            setTimeout(pollGameStatus, 1000);
          } else {
            console.warn('[Polling] Max polling attempts reached');
            hideLoadingOverlay();
            setText('status', '');
          }
          return;
        }

        // Game has exited or crashed
        _deps.debug('[Polling] Game has exited with status:', statusRes.status);
        hideLoadingOverlay();

        if (statusRes.ok) {
          setText('status', '');
        } else {
          setText('status', t('launch.status.minecraftCrashedExit', { exitCode: statusRes.exit_code || t('common.unknown') }));
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
          hideLoadingOverlay();
          setText('status', '');
        }
      }
    };

    setText('status', t('launch.launching'));
    setTimeout(() => {
      pollGameStatus();
      pollWindowVisibility();
    }, 2000);
  });
};


export const showCrashDialog = async (processId, logPath, contextMessage = '') => {
  _deps.debug(`[showCrashDialog] Minecraft crashed. logPath: ${logPath}`);

  let crashDetails = '';
  let javaDownloadMajor = 0;
  const contextText = String(contextMessage || '').trim();
  if (contextText) {
    crashDetails += `<br><br>${escapeInfoHtml(contextText).replace(/\n/g, '<br>')}`;
  }

  if (logPath) {
    try {
      const crashRes = await api('/api/crash-log', 'POST', {
        log_path: logPath
      });

      if (crashRes.ok && crashRes.error_analysis) {
        const analysis = crashRes.error_analysis;
        if (analysis.has_error && analysis.message) {
          crashDetails += `<br><br><b style="color:var(--color-error-soft);">${analysis.message}</b><br>`;
          if (analysis.details) {
            crashDetails += `<i>${analysis.details}</i>`;
          }
          if (analysis.suggestion) {
            crashDetails += `<br><br><b>Suggestion:</b> ${analysis.suggestion}`;
          }
          if (analysis.error_type === 'JavaVersionMismatch') {
            javaDownloadMajor = Number.parseInt(
              String(analysis.download_java_major || analysis.required_java_major || ''),
              10,
            ) || 0;
          }
        }
      }
    } catch (err) {
      console.error('Error analyzing crash log:', err);
    }
  }

  const buttons = [
    {
      label: t('launch.openLogs'),
      onClick: () => viewCrashLogs(processId, logPath),
    },
  ];

  if (javaDownloadMajor > 0) {
    buttons.push({
      label: t('launch.downloadJava'),
      classList: ['important'],
      onClick: () => installJavaRuntime(javaDownloadMajor),
    });
  }

  buttons.push({
    label: t('common.ok'),
    classList: ['primary'],
    onClick: () => {},
  });

  let message = t('launch.crashMessage');
  if (crashDetails) {
    message += `\n\n${crashDetails}`;
  }

  showMessageBox({
    title: t('launch.crashTitle'),
    message: message,
    buttons: buttons,
    description: logPath
      ? t('launch.latestLog', { file: getFileName(logPath) })
      : t('launch.noLogFileFound'),
  });
};

export const viewCrashLogs = async (processId, logPath) => {
  try {
    if (!logPath) {
      showMessageBox({
        title: t('launch.logNotFoundTitle'),
        message: t('launch.noCrashLogForProcess'),
        buttons: [{
          label: t('common.ok'),
          onClick: () => {},
        }],
      });
      return;
    }

    // Debug logging
    _deps.debug(`[viewCrashLogs] Opening crash log: ${logPath}`);

    // Open the log file in the system's default app
    const openRes = await api('/api/open-crash-log', 'POST', {
      log_path: logPath
    });

    if (openRes.ok) {
      showMessageBox({
        title: t('launch.openingCrashLogTitle'),
        message: t('launch.openingCrashLogMessage', { file: logPath.split(/[\\/]/).pop() }),
        buttons: [{
          label: t('common.ok'),
          onClick: () => {},
        }],
      });
    } else {
      showMessageBox({
        title: t('common.error'),
        message: t('launch.failedToOpenCrashLog', { error: openRes.error || t('common.unknownError') }),
        buttons: [{
          label: t('common.ok'),
          onClick: () => {},
        }],
      });
    }
  } catch (err) {
    console.error('Error opening crash log:', err);
    showMessageBox({
      title: t('common.error'),
      message: `Error: ${err.message}`,
      buttons: [{
        label: t('common.ok'),
        onClick: () => {},
      }],
    });
  }
};

export const getFileName = (path) => {
  if (!path) return '';
  return path.split(/[\\/]/).pop();
};

export const promptLoaderSelection = (installed) => {
  return new Promise((resolve) => {
    let resolved = false;
    let controls = null;

    const safeResolve = (value) => {
      if (resolved) return;
      resolved = true;
      resolve(value);
      try {
        controls?.close?.();
      } catch (e) {
        // ignore
      }
    };

    const wrap = document.createElement('div');
    wrap.style.cssText = 'max-height:60vh;overflow-y:auto;padding:10px;text-align:center;';

    const hint = document.createElement('div');
    hint.style.cssText = 'color:var(--color-text-muted);font-size:12px;margin-bottom:12px;line-height:1.35;';
    hint.textContent = t('launch.loader.hint');
    wrap.appendChild(hint);

    const list = document.createElement('div');
    list.style.cssText = 'display:grid;gap:8px;';
    wrap.appendChild(list);

    const makeCard = ({ accent = '#777', title = '', subtitle = '', meta = '', onPick }) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.style.cssText =
        `width:100%;background:var(--color-surface-card);border:1px solid var(--color-border-strong);border-left:3px solid ${accent};` +
        'padding:8px 12px;display:flex;justify-content:space-between;align-items:center;text-align:left;color:var(--color-text-primary);';

      const left = document.createElement('div');
      left.style.cssText = 'min-width:0;';

      const titleEl = document.createElement('div');
      titleEl.style.cssText = `color:${accent};font-weight:700;line-height:1.2;`;
      titleEl.textContent = title || t('launch.loader.generic');

      const sub = document.createElement('div');
      sub.style.cssText = 'color:var(--color-text-muted);font-size:12px;line-height:1.2;margin-top:2px;';
      sub.textContent = subtitle || '';
      if (!subtitle) sub.style.display = 'none';

      const m = document.createElement('div');
      m.style.cssText = 'color:var(--color-text-dim);font-size:11px;line-height:1.2;margin-top:2px;';
      m.textContent = meta || '';
      if (!meta) m.style.display = 'none';

      left.appendChild(titleEl);
      left.appendChild(sub);
      left.appendChild(m);

      btn.appendChild(left);

      btn.addEventListener('mouseenter', () => {
        btn.style.background = 'var(--color-surface-card-hover)';
      });
      btn.addEventListener('mouseleave', () => {
        btn.style.background = 'var(--color-surface-card)';
      });
      btn.addEventListener('click', () => {
        if (typeof onPick === 'function') onPick();
      });

      return btn;
    };

    list.appendChild(makeCard({
      accent: '#ccc',
      title: t('launch.loader.vanilla'),
      subtitle: t('launch.loader.none'),
      meta: '',
      onPick: () => safeResolve(null),
    }));

    LOADER_UI_ORDER.forEach((loaderType) => {
      if (!installed[loaderType] || installed[loaderType].length === 0) return;
      const loaderUi = getLoaderUi(loaderType);
      installed[loaderType].forEach((loader) => {
        list.appendChild(makeCard({
          accent: loaderUi.accent || '#777',
          title: loaderUi.name,
          subtitle: String(loader.version || '').trim(),
          meta: loader.size_display ? String(loader.size_display) : '',
          onPick: () => safeResolve({ type: loaderType, version: loader.version }),
        }));
      });
    });

    controls = showMessageBox({
      title: t('launch.loader.title'),
      customContent: wrap,
      buttons: [
        { label: t('common.cancel'), onClick: () => safeResolve(false) },
      ],
    });
  });
};

