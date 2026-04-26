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


export const autoSaveSetting = (key, value) => {
  state.settingsState[key] = value;
  const refreshWorldsAfterSave = key === 'storage_directory' || key === 'custom_storage_directory';
  if (key === 'storage_directory' || key === 'custom_storage_directory') {
    syncStorageDirectoryUI();
  }
  updateHomeInfo();
  if (key === 'username' && state.settingsState.account_type === 'Histolauncher') {
    return Promise.resolve();
  }
  const savePromise = api('/api/settings', 'POST', { [key]: value });
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
    await api('/api/settings', 'POST', { [key]: val });
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
            'Failed to select a custom storage directory.';
          showMessageBox({
            title: 'Folder Selection Error',
            message: errorMessage,
            buttons: [{ label: 'OK' }],
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
          title: 'Folder Selection Error',
          message: `Failed to select a custom storage directory.<br><br>${err.message || err}`,
          buttons: [{ label: 'OK' }],
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
      if (state.settingsState.account_type !== 'Histolauncher') return;
      showHistolauncherAccountSettingsModal();
    });
  }

  if (accountSelect) {
    accountSelect.addEventListener('change', async (e) => {
      const val = e.target.value === 'Histolauncher' ? 'Histolauncher' : 'Local';
      const isConnected = state.settingsState.account_type === 'Histolauncher' && !!state.settingsState.uuid;

      if (state.settingsState.account_type === 'Histolauncher' && val === 'Local') {
        state.histolauncherUsername = state.settingsState.username;
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
                    const errorMsg = (loginRes && loginRes.error) || 'Failed to authenticate';
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
          if (a) a.addEventListener('click', (ev) => { ev.preventDefault(); window.open('https://histolauncher.org/signup', '_blank'); });
        }, 50);

        return;
      }

      if (val === 'Local') {
        if (state.settingsState.account_type === 'Histolauncher') {
          // Confirm disconnection
          showMessageBox({
            title: 'Disconnect Account',
            message: 'Are you sure you want to disconnect your Histolauncher account? You will need to log in again to use it.',
            buttons: [
              {
                label: 'Disconnect',
                classList: ['danger'],
                onClick: async () => {
                  state.histolauncherUsername = state.settingsState.username;
                  state.settingsState.account_type = 'Local';
                  state.settingsState.uuid = '';
                  if (usernameInput) {
                    usernameInput.disabled = false;
                    usernameInput.value = state.settingsState.username || '';
                  }
                  if (disconnectBtn) disconnectBtn.style.display = 'none';
                  await api('/api/settings', 'POST', {
                    account_type: 'Local',
                    uuid: ''
                  });
                  await _deps.init();
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
      await saveCheckboxSettingAndReinit('low_data_mode', e.target.checked);
    });
  }

  const fastDownloadInput = getEl('settings-fast-download');
  if (fastDownloadInput) {
    fastDownloadInput.addEventListener('change', async (e) => {
      await saveCheckboxSettingAndReinit('fast_download', e.target.checked);
    });
  }

  const showThirdPartyInput = getEl('settings-show-third-party-versions');
  if (showThirdPartyInput) {
    showThirdPartyInput.addEventListener('change', async (e) => {
      await saveCheckboxSettingAndReinit('show_third_party_versions', e.target.checked);
    });
  }

  const allowAllOverrideClasspathInput = getEl('settings-allow-override-classpath-all-modloaders');
  if (allowAllOverrideClasspathInput) {
    allowAllOverrideClasspathInput.addEventListener('change', async (e) => {
      await saveCheckboxSettingAndReinit('allow_override_classpath_all_modloaders', e.target.checked);
    });
  }
};
