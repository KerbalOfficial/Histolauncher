// ui/modules/settings-autosave.js

import { state } from './state.js';
import { getEl } from './dom-utils.js';
import {
  ADD_PROFILE_OPTION,
  JAVA_RUNTIME_INSTALL_OPTION,
  JAVA_RUNTIME_PATH,
} from './config.js';
import { api } from './api.js';
import { showMessageBox } from './modal.js';
import { showJavaInstallChooser } from './java-installer.js';
import { APPEARANCE_SETTING_KEYS, applyAppearanceSettings } from './appearance.js';
import { setLauncherLanguage, t } from './i18n.js';
import { escapeInfoHtml } from './string-utils.js';
import {
  getCustomStorageDirectoryPath,
  isTruthySetting,
  normalizeStorageDirectoryMode,
  refreshCustomStorageDirectoryValidation,
  renderProfilesSelect,
  renderScopeProfilesSelect,
  showCreateProfileModal,
  showCreateScopeProfileModal,
  showDeleteProfileModal,
  showDeleteScopeProfileModal,
  showRenameProfileModal,
  showRenameScopeProfileModal,
  switchProfile,
  switchScopeProfile,
  syncStorageDirectoryUI,
  updateProfileDeleteButtonState,
  updateScopeProfileDeleteButtonState,
  updateScopeProfileEditButtonState,
} from './profiles.js';
import { setModsDeps } from './mods.js';
import { setAutoSaveSetting as setWorldsAutoSaveSetting } from './worlds.js';
import { refreshWorldsStorageContext } from './worlds.js';
import { updateSettingsValidationUI } from './launch.js';
import {
  debug,
  refreshJavaRuntimeOptions,
  showHistolauncherAccountSettingsModal,
  updateHomeInfo,
  updateSettingsAccountSettingsButtonVisibility,
  updateSettingsPlayerPreview,
} from './home.js';
import { showMicrosoftSkinEditorModal } from './skin-editor.js';

let javaRuntimeRefreshListenerBound = false;

const _deps = {};
for (const k of ['init']) {
  Object.defineProperty(_deps, k, {
    configurable: true,
    enumerable: true,
    get() {
      throw new Error('settings-autosave.js dep "' + k + '" not initialized; call setSettingsAutosaveDeps() first');
    },
  });
}

export function setSettingsAutosaveDeps(deps) {
  for (const [k, v] of Object.entries(deps)) {
    Object.defineProperty(_deps, k, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: v,
    });
  }
}


const normalizeAccountType = (value) => {
  if (value === 'Histolauncher') return 'Histolauncher';
  if (value === 'Microsoft') return 'Microsoft';
  return 'Local';
};

const isOnlineAccountType = (value) => normalizeAccountType(value) !== 'Local';

const settingsProfilePayload = (patch = {}) => ({
  ...patch,
  _profile_id: state.profilesState.activeProfile || 'default',
});

const accountTypeLabel = (value) => {
  const normalized = normalizeAccountType(value);
  if (normalized === 'Histolauncher') return t('settings.account.typeHistolauncher');
  if (normalized === 'Microsoft') return t('settings.account.typeMicrosoft');
  return t('settings.account.typeLocal');
};

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const copyTextToClipboard = async (text) => {
  const value = String(text || '');
  if (!value) return false;

  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch (err) {
      console.warn('Navigator clipboard write failed:', err);
    }
  }

  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', 'readonly');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } catch (err) {
    console.warn('Fallback clipboard copy failed:', err);
  } finally {
    textarea.remove();
  }
  return copied;
};

const buildMicrosoftLoginContent = (deviceCode) => {
  const wrap = document.createElement('div');
  wrap.style.display = 'flex';
  wrap.style.flexDirection = 'column';
  wrap.style.gap = '10px';

  const instruction = document.createElement('div');
  instruction.textContent = t('settings.account.microsoft.useCodeInstruction');
  wrap.appendChild(instruction);

  const code = document.createElement('div');
  code.textContent = String(deviceCode.user_code || '').trim();
  code.style.fontSize = '24px';
  code.style.fontWeight = '700';
  code.style.letterSpacing = '0';
  code.style.padding = '10px 12px';
  code.style.border = '1px solid var(--color-border-soft)';
  code.style.background = 'var(--color-surface-code-block)';
  code.style.textAlign = 'center';
  code.style.userSelect = 'all';
  wrap.appendChild(code);

  const uri = document.createElement('div');
  uri.textContent = String(deviceCode.verification_uri || 'https://www.microsoft.com/link');
  uri.style.fontSize = '12px';
  uri.style.color = 'var(--color-text-muted)';
  uri.style.overflowWrap = 'anywhere';
  wrap.appendChild(uri);

  const status = document.createElement('div');
  status.id = 'microsoft-login-status';
  status.textContent = t('settings.account.microsoft.waitingApproval');
  status.style.fontSize = '12px';
  status.style.color = 'var(--color-text-muted)';
  wrap.appendChild(status);

  return wrap;
};

const setMicrosoftLoginStatus = (message) => {
  const status = getEl('microsoft-login-status');
  if (status) status.textContent = message;
};

const connectMicrosoftAccount = async ({ accountSelect, usernameInput, usernameRow, previousType }) => {
  let cancelled = false;
  const restorePreviousAccountType = () => {
    const restored = normalizeAccountType(previousType);
    if (accountSelect) accountSelect.value = restored;
    state.settingsState.account_type = restored;
    updateHomeInfo();
  };

  try {
    const deviceCode = await api('/api/account/microsoft/device-code', 'POST', {});
    if (!deviceCode || !deviceCode.ok || !deviceCode.device_code) {
      restorePreviousAccountType();
      showMessageBox({
        title: t('settings.account.microsoft.loginTitle'),
        message: (deviceCode && deviceCode.error) || t('settings.account.microsoft.failedStart'),
        buttons: [{ label: t('common.ok') }],
      });
      return;
    }

    const openUrl = deviceCode.verification_uri_complete || deviceCode.verification_uri || 'https://www.microsoft.com/link';
    const controls = showMessageBox({
      title: t('settings.account.microsoft.loginTitle'),
      customContent: buildMicrosoftLoginContent(deviceCode),
      buttons: [
        {
          label: t('settings.account.microsoft.openMicrosoft'),
          classList: ['primary'],
          closeOnClick: false,
          onClick: () => {
            window.open(openUrl, '_blank');
          },
        },
        {
          label: t('common.cancel'),
          onClick: () => {
            cancelled = true;
            restorePreviousAccountType();
          },
        },
      ],
    });

    let interval = Math.max(2, Number(deviceCode.interval || 5));
    while (!cancelled) {
      await delay(interval * 1000);
      if (cancelled) return;

      const poll = await api('/api/account/microsoft/poll', 'POST', {
        device_code: deviceCode.device_code,
        interval,
      });

      if (poll && poll.ok && poll.authenticated) {
        if (controls && controls.close) controls.close();
        state.settingsState.account_type = 'Microsoft';
        state.settingsState.username = poll.username || state.settingsState.username;
        state.settingsState.uuid = poll.uuid || state.settingsState.uuid;
        state.localUsernameModified = false;
        if (usernameRow) usernameRow.style.display = 'none';
        if (usernameInput) usernameInput.disabled = true;
        await _deps.init();
        return;
      }

      if (poll && poll.pending) {
        interval = Math.max(2, Number(poll.interval || interval));
        setMicrosoftLoginStatus(t('settings.account.microsoft.waitingApproval'));
        continue;
      }

      cancelled = true;
      restorePreviousAccountType();
      const errorMsg = (poll && poll.error) || t('settings.account.microsoft.failedLogin');
      showMessageBox({ title: t('settings.account.microsoft.loginTitle'), message: errorMsg, buttons: [{ label: t('common.ok') }] });
      return;
    }
  } catch (e) {
    cancelled = true;
    restorePreviousAccountType();
    showMessageBox({
      title: t('settings.account.microsoft.loginTitle'),
      message: t('settings.account.connectionFailed', { error: e.message || e }),
      buttons: [{ label: t('common.ok') }],
    });
  }
};


export const autoSaveSetting = (key, value) => {
  state.settingsState[key] = value;
  const refreshWorldsAfterSave = key === 'storage_directory' || key === 'custom_storage_directory';
  if (APPEARANCE_SETTING_KEYS.has(key)) {
    applyAppearanceSettings(state.settingsState);
  }
  if (key === 'launcher_language') {
    setLauncherLanguage(value).catch((err) => {
      console.warn('Failed to apply launcher language:', err);
    });
  }
  if (key === 'player_preview_mode') {
    updateSettingsPlayerPreview();
  }
  if (key === 'storage_directory' || key === 'custom_storage_directory') {
    syncStorageDirectoryUI();
  }
  updateHomeInfo();
  if (key === 'username' && isOnlineAccountType(state.settingsState.account_type)) {
    return Promise.resolve();
  }
  const savePromise = api('/api/settings', 'POST', settingsProfilePayload({ [key]: value }));
  if (refreshWorldsAfterSave) {
    savePromise.finally(() => {
      refreshWorldsStorageContext();
    });
  }
  return savePromise;
};

setWorldsAutoSaveSetting(autoSaveSetting);

setModsDeps({
  autoSaveSetting,
  isTruthySetting,
  renderScopeProfilesSelect,
  showCreateScopeProfileModal,
  showDeleteScopeProfileModal,
  showRenameScopeProfileModal,
  switchScopeProfile,
  updateScopeProfileDeleteButtonState,
  updateScopeProfileEditButtonState,
});

export const initSettingsInputs = () => {
  if (!javaRuntimeRefreshListenerBound) {
    javaRuntimeRefreshListenerBound = true;
    window.addEventListener('histolauncher:java-runtimes-refreshed', () => {
      refreshJavaRuntimeOptions(true).catch((err) => {
        console.warn('Failed to update Java runtime dropdown after refresh:', err);
      });
    });
  }

  const saveCheckboxSettingAndReinit = async (key, checked) => {
    const val = checked ? "1" : "0";
    state.settingsState[key] = val;
    updateHomeInfo();
    await api('/api/settings', 'POST', settingsProfilePayload({ [key]: val }));
    await _deps.init();
  };

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
      state.localUsernameModified = true;
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

  const resolutionInputHandler = (key) => (e) => {
    let value = String(e.target.value || '').replace(/[^0-9]/g, '');
    if (value) {
      value = String(Math.max(1, Math.min(Number(value), 99999)));
    }
    e.target.value = value;
    autoSaveSetting(key, value || (key === 'game_resolution_width' ? '854' : '480'));
  };

  const resolutionWidthInput = getEl('settings-resolution-width');
  if (resolutionWidthInput) {
    resolutionWidthInput.addEventListener('input', resolutionInputHandler('game_resolution_width'));
  }

  const resolutionHeightInput = getEl('settings-resolution-height');
  if (resolutionHeightInput) {
    resolutionHeightInput.addEventListener('input', resolutionInputHandler('game_resolution_height'));
  }

  const gameFullscreenInput = getEl('settings-game-fullscreen');
  if (gameFullscreenInput) {
    gameFullscreenInput.addEventListener('change', (e) => {
      autoSaveSetting('game_fullscreen', e.target.checked ? '1' : '0');
    });
  }

  const demoModeInput = getEl('settings-demo-mode');
  if (demoModeInput) {
    demoModeInput.addEventListener('change', (e) => {
      autoSaveSetting('game_demo_mode', e.target.checked ? '1' : '0');
    });
  }

  const launcherThemeSelect = getEl('settings-launcher-theme');
  if (launcherThemeSelect) {
    launcherThemeSelect.addEventListener('change', (e) => {
      autoSaveSetting('launcher_theme', e.target.value || 'dark');
    });
  }

  const launcherUiSizeSelect = getEl('settings-launcher-ui-size');
  if (launcherUiSizeSelect) {
    launcherUiSizeSelect.addEventListener('change', (e) => {
      const uiSize = ['small', 'normal', 'large', 'extra-large'].includes(e.target.value)
        ? e.target.value
        : 'normal';
      autoSaveSetting('launcher_ui_size', uiSize);
    });
  }

  const launcherLanguageSelect = getEl('settings-launcher-language');
  if (launcherLanguageSelect) {
    launcherLanguageSelect.addEventListener('change', (e) => {
      autoSaveSetting('launcher_language', e.target.value || 'en');
    });
  }

  const layoutDensitySelect = getEl('settings-layout-density');
  if (layoutDensitySelect) {
    layoutDensitySelect.addEventListener('change', (e) => {
      autoSaveSetting('layout_density', e.target.value === 'compact' ? 'compact' : 'comfortable');
    });
  }

  const compactSidebarInput = getEl('settings-compact-sidebar');
  if (compactSidebarInput) {
    compactSidebarInput.addEventListener('change', (e) => {
      autoSaveSetting('compact_sidebar', e.target.checked ? '1' : '0');
    });
  }

  const playerPreview3dInput = getEl('settings-player-preview-3d');
  if (playerPreview3dInput) {
    playerPreview3dInput.addEventListener('change', (e) => {
      autoSaveSetting('player_preview_mode', e.target.checked ? '3d' : '2d');
    });
  }

  const storageSelect = getEl('settings-storage-dir');
  if (storageSelect) {
    storageSelect.addEventListener('change', async (e) => {
      const val = normalizeStorageDirectoryMode(e.target.value);
      autoSaveSetting('storage_directory', val);
      await refreshCustomStorageDirectoryValidation();
    });
  }

  const selectStorageFolderBtn = getEl('settings-select-storage-folder-btn');
  if (selectStorageFolderBtn) {
    selectStorageFolderBtn.addEventListener('click', async () => {
      selectStorageFolderBtn.disabled = true;
      try {
        const res = await api('/api/storage-directory/select', 'POST', {
          current_path: getCustomStorageDirectoryPath(),
        });

        if (res && res.cancelled) {
          return;
        }

        if (!res || res.ok !== true) {
          const errorMessage = (res && (res.error || res.message)) ||
            t('settings.client.failedSelectCustomStorageDirectory');
          showMessageBox({
            title: t('settings.client.folderSelectionErrorTitle'),
            message: errorMessage,
            buttons: [{ label: t('common.ok') }],
          });
          await refreshCustomStorageDirectoryValidation();
          return;
        }

        state.settingsState = {
          ...state.settingsState,
          ...(res.settings || {}),
        };
        syncStorageDirectoryUI();
        refreshWorldsStorageContext();
        updateHomeInfo();
        updateSettingsValidationUI();
      } catch (err) {
        showMessageBox({
          title: t('settings.client.folderSelectionErrorTitle'),
          message: t('settings.client.failedSelectCustomStorageDirectoryWithError', { error: err.message || err }),
          buttons: [{ label: t('common.ok') }],
        });
        await refreshCustomStorageDirectoryValidation();
      } finally {
        selectStorageFolderBtn.disabled = false;
      }
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
    javaRuntimeSelect.addEventListener('change', async (e) => {
      const selected = String(e.target.value || '').trim();
      if (selected === JAVA_RUNTIME_INSTALL_OPTION) {
        const previousValue = String(state.settingsState.java_path || '').trim() || JAVA_RUNTIME_PATH;
        e.target.value = previousValue;
        e.target.disabled = true;
        try {
          const result = await showJavaInstallChooser();
          if (result && result.ok) {
            await refreshJavaRuntimeOptions(true);
          }
        } finally {
          e.target.disabled = false;
          if (e.target.value === JAVA_RUNTIME_INSTALL_OPTION) {
            e.target.value = previousValue;
          }
        }
        return;
      }

      autoSaveSetting('java_path', selected);
    });
  }

  const profileSelect = getEl('settings-profile-select');
  if (profileSelect) {
    profileSelect.addEventListener('change', async (e) => {
      const selected = String(e.target.value || '').trim();
      if (!selected) {
        renderProfilesSelect();
        return;
      }

      if (selected === ADD_PROFILE_OPTION) {
        e.target.value = state.profilesState.activeProfile;
        showCreateProfileModal();
        return;
      }

      if (selected === state.profilesState.activeProfile) {
        return;
      }

      await switchProfile(selected);
    });
  }

  const profileDeleteBtn = getEl('settings-profile-delete-btn');
  const profileDeleteIcon = getEl('settings-profile-delete-icon');
  const profileEditBtn = getEl('settings-profile-edit-btn');
  const profileEditIcon = getEl('settings-profile-edit-icon');
  if (profileEditBtn) {
    profileEditBtn.disabled = !state.profilesState.activeProfile;
    profileEditBtn.style.opacity = profileEditBtn.disabled ? '0.5' : '1';
    profileEditBtn.style.cursor = profileEditBtn.disabled ? 'not-allowed' : 'pointer';

    if (profileEditIcon) {
      profileEditBtn.addEventListener('mouseenter', () => {
        if (!profileEditBtn.disabled) profileEditIcon.src = 'assets/images/filled_pencil.png';
      });
      profileEditBtn.addEventListener('mouseleave', () => {
        profileEditIcon.src = 'assets/images/unfilled_pencil.png';
      });
    }

    profileEditBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (profileEditBtn.disabled) return;
      showRenameProfileModal();
    });
  }

  if (profileDeleteBtn) {
    if (profileDeleteIcon) {
      profileDeleteBtn.addEventListener('mouseenter', () => {
        if (!profileDeleteBtn.disabled) profileDeleteIcon.src = 'assets/images/filled_delete.png';
      });
      profileDeleteBtn.addEventListener('mouseleave', () => {
        profileDeleteIcon.src = 'assets/images/unfilled_delete.png';
      });
    }
    profileDeleteBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (profileDeleteBtn.disabled) return;
      showDeleteProfileModal();
    });
    updateProfileDeleteButtonState();
  }

  const accountSelect = getEl('settings-account-type');
  const connectBtn = getEl('connect-account-btn');
  const disconnectBtn = getEl('disconnect-account-btn');
  const accountSettingsBtn = getEl('settings-account-settings-btn');
  const usernameRow = getEl('username-row');

  if (connectBtn) connectBtn.style.display = 'none';
  updateSettingsAccountSettingsButtonVisibility();

  if (accountSettingsBtn) {
    accountSettingsBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const accountType = normalizeAccountType(state.settingsState.account_type);
      if (accountType === 'Histolauncher') {
        showHistolauncherAccountSettingsModal();
        return;
      }
      if (accountType === 'Microsoft') {
        showMicrosoftSkinEditorModal();
      }
    });
  }

  if (accountSelect) {
    accountSelect.addEventListener('change', async (e) => {
      const previousType = normalizeAccountType(state.settingsState.account_type);
      const val = normalizeAccountType(e.target.value);
      e.target.value = val;
      const restorePreviousType = () => {
        const restored = normalizeAccountType(previousType);
        if (accountSelect) accountSelect.value = restored;
        state.settingsState.account_type = restored;
        updateHomeInfo();
      };
      const isConnected = previousType === 'Histolauncher' && !!state.settingsState.uuid;

      if (previousType === 'Histolauncher' && val === 'Local') {
        state.histolauncherUsername = state.settingsState.username;
      }

      if (val === 'Microsoft') {
        if (previousType === 'Microsoft' && !!state.settingsState.uuid) {
          if (usernameRow) usernameRow.style.display = 'none';
          if (usernameInput) usernameInput.disabled = true;
          state.settingsState.account_type = 'Microsoft';
          updateSettingsAccountSettingsButtonVisibility();
          updateSettingsPlayerPreview();
          updateHomeInfo();
          return;
        }

        await connectMicrosoftAccount({
          accountSelect,
          usernameInput,
          usernameRow,
          previousType,
        });
        return;
      }

      if (val === 'Histolauncher') {
        if (isConnected) {
          if (state.localUsernameModified && state.histolauncherUsername) {
            state.settingsState.username = state.histolauncherUsername;
            if (usernameInput) usernameInput.value = state.histolauncherUsername;
            state.localUsernameModified = false;
            updateHomeInfo();
          }
          if (usernameRow) usernameRow.style.display = 'none';
          if (usernameInput) usernameInput.disabled = true;
          state.settingsState.account_type = 'Histolauncher';
          autoSaveSetting('account_type', 'Histolauncher');
          updateSettingsAccountSettingsButtonVisibility();
          updateSettingsPlayerPreview();
          return;
        }

        const signupLink = `<span style="color:var(--color-text-muted);font-size:12px;margin-left:6px">${t('settings.account.histolauncher.noAccount')} <a id="msgbox-signup-link" href="#">${t('settings.account.histolauncher.signUpHere')}</a></span>`;
        showMessageBox({
          title: t('settings.account.histolauncher.loginTitle'),
          message: t('settings.account.histolauncher.loginMessage', { signupLink }),
          inputs: [
            { name: 'username', type: 'text', placeholder: t('settings.account.histolauncher.usernamePlaceholder') },
            { name: 'password', type: 'password', placeholder: t('settings.account.histolauncher.passwordPlaceholder') },
          ],
          buttons: [
            {
              label: t('settings.account.histolauncher.loginButton'),
              classList: ['primary'],
              onClick: async (vals) => {
                try {
                  const username = (vals.username || '').trim();
                  const password = (vals.password || '').trim();
                  if (!username || !password) {
                    showMessageBox({ title: t('common.error'), message: t('settings.account.histolauncher.requiredCredentials'), buttons: [{ label: t('common.ok') }] });
                    restorePreviousType();
                    return;
                  }

                  const loginRes = await api('/api/account/login', 'POST', {
                    username,
                    password,
                  });
                  debug('[Login] Backend login response:', loginRes);

                  if (loginRes && loginRes.ok && loginRes.username && loginRes.uuid) {
                    state.settingsState.account_type = 'Histolauncher';
                    state.histolauncherUsername = loginRes.username;
                    state.localUsernameModified = false;
                    await _deps.init();
                  } else {
                    const errorMsg = (loginRes && loginRes.error) || t('settings.account.histolauncher.failedAuthenticate');
                    console.error('[Login] Error:', errorMsg);
                    showMessageBox({ title: t('common.error'), message: escapeInfoHtml(errorMsg), buttons: [{ label: t('common.ok') }] });
                    restorePreviousType();
                  }
                } catch (e) {
                  console.error('[Login] Exception:', e);
                  showMessageBox({ title: t('common.error'), message: t('settings.account.connectionFailed', { error: escapeInfoHtml(e.message || t('common.unknownError')) }), buttons: [{ label: t('common.ok') }] });
                  restorePreviousType();
                }
              },
            },
            {
              label: t('common.cancel'),
              onClick: () => {
                restorePreviousType();
              }
            }
          ],
        });

        setTimeout(() => {
          const a = getEl('msgbox-signup-link');
          if (a) a.addEventListener('click', (ev) => { ev.preventDefault(); window.open('https://histolauncher.org/signup', '_blank'); });
        }, 50);

        return;
      }

      if (val === 'Local') {
        if (isOnlineAccountType(previousType)) {
          const label = accountTypeLabel(previousType);
          showMessageBox({
            title: t('settings.account.disconnectTitle'),
            message: t('settings.account.disconnectConfirm', { account: label }),
            buttons: [
              {
                label: t('settings.account.disconnectButton'),
                classList: ['danger'],
                onClick: async () => {
                  if (previousType === 'Histolauncher') {
                    state.histolauncherUsername = state.settingsState.username;
                  }
                  state.settingsState.account_type = 'Local';
                  state.settingsState.uuid = '';
                  if (usernameInput) {
                    usernameInput.disabled = false;
                    usernameInput.value = state.settingsState.username || '';
                  }
                  if (disconnectBtn) disconnectBtn.style.display = 'none';
                  await api('/api/account/disconnect', 'POST', {});
                  await _deps.init();
                }
              },
              {
                label: t('common.cancel'),
                onClick: () => {
                  if (accountSelect) accountSelect.value = previousType;
                }
              }
            ]
          });
          return;
        }

        state.settingsState.account_type = 'Local';
        if (usernameInput) {
          usernameInput.disabled = false;
          usernameInput.value = state.settingsState.username || '';
        }
        if (disconnectBtn) disconnectBtn.style.display = 'none';
        autoSaveSetting('account_type', 'Local');
        await _deps.init();
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
        const deleted = Number(result.deleted || 0);
        const skipped = Number(result.skipped || 0);
        showMessageBox({
          title: t('settings.logs.clearedTitle'),
          message: skipped > 0
            ? t('settings.logs.clearedWithSkipped', { deleted, skipped })
            : t('settings.logs.clearedMessage', { deleted }),
          buttons: [{
            label: t('common.ok'),
            onClick: () => {}
          }]
        });
      } else {
        showMessageBox({
          title: t('common.error'),
          message: t('settings.logs.clearFailed', { error: result.error || t('common.unknownError') }),
          buttons: [{
            label: t('common.ok'),
            onClick: () => {}
          }]
        });
      }
    });
  }

  const copyDiagnosticsButton = getEl('copy-diagnostics-btn');
  if (copyDiagnosticsButton) {
    copyDiagnosticsButton.addEventListener('click', async () => {
      copyDiagnosticsButton.disabled = true;
      try {
        const result = await api('/api/diagnostics/report', 'POST', { include_text: true });
        if (!result || !result.ok) {
          throw new Error((result && result.error) || t('common.unknownError'));
        }
        const copied = await copyTextToClipboard(result.report_text || '');
        showMessageBox({
          title: copied ? t('settings.diagnostics.copiedTitle') : t('settings.diagnostics.copyFailedTitle'),
          message: copied
            ? t('settings.diagnostics.copiedMessage')
            : t('settings.diagnostics.copyFailedMessage'),
          buttons: [{
            label: t('common.ok'),
            onClick: () => {}
          }]
        });
      } catch (err) {
        showMessageBox({
          title: t('settings.diagnostics.failedTitle'),
          message: t('settings.diagnostics.failedMessage', { error: err.message || err }),
          buttons: [{
            label: t('common.ok'),
            onClick: () => {}
          }]
        });
      } finally {
        copyDiagnosticsButton.disabled = false;
      }
    });
  }

  const saveDiagnosticsButton = getEl('save-diagnostics-btn');
  if (saveDiagnosticsButton) {
    saveDiagnosticsButton.addEventListener('click', async () => {
      saveDiagnosticsButton.disabled = true;
      try {
        const result = await api('/api/diagnostics/report', 'POST', {
          include_text: false,
          save_to_disk: true,
        });
        if (!result || !result.ok) {
          throw new Error((result && result.error) || t('common.unknownError'));
        }
        if (result.cancelled) return;
        showMessageBox({
          title: t('settings.diagnostics.savedTitle'),
          message: t('settings.diagnostics.savedMessage', { path: result.display_path || result.saved_path || '' }),
          buttons: [{
            label: t('common.ok'),
            onClick: () => {}
          }]
        });
      } catch (err) {
        showMessageBox({
          title: t('settings.diagnostics.failedTitle'),
          message: t('settings.diagnostics.failedMessage', { error: err.message || err }),
          buttons: [{
            label: t('common.ok'),
            onClick: () => {}
          }]
        });
      } finally {
        saveDiagnosticsButton.disabled = false;
      }
    });
  }

  const lowDataInput = getEl('settings-low-data');
  if (lowDataInput) {
    lowDataInput.addEventListener('change', async (e) => {
      await saveCheckboxSettingAndReinit('low_data_mode', e.target.checked);
    });
  }

  const showThirdPartyInput = getEl('settings-show-third-party-versions');
  if (showThirdPartyInput) {
    showThirdPartyInput.addEventListener('change', async (e) => {
      await saveCheckboxSettingAndReinit('show_third_party_versions', e.target.checked);
    });
  }

  const discordRpcInput = getEl('settings-discord-rpc');
  if (discordRpcInput) {
    discordRpcInput.addEventListener('change', (e) => {
      autoSaveSetting('discord_rpc_enabled', e.target.checked ? '1' : '0');
    });
  }

  const desktopNotificationsInput = getEl('settings-desktop-notifications');
  if (desktopNotificationsInput) {
    desktopNotificationsInput.addEventListener('change', (e) => {
      autoSaveSetting('desktop_notifications_enabled', e.target.checked ? '1' : '0');
    });
  }

  const allowAllOverrideClasspathInput = getEl('settings-allow-override-classpath-all-modloaders');
  if (allowAllOverrideClasspathInput) {
    allowAllOverrideClasspathInput.addEventListener('change', async (e) => {
      await saveCheckboxSettingAndReinit('allow_override_classpath_all_modloaders', e.target.checked);
    });
  }
};
