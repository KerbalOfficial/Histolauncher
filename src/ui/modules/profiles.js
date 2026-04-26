// ui/modules/profiles.js

import { state } from './state.js';
import { api } from './api.js';
import { getEl, toggleClass } from './dom-utils.js';
import { showMessageBox } from './modal.js';
import { ADD_PROFILE_OPTION } from './config.js';
import { updateSettingsValidationUI } from './launch.js';

const _deps = {};
for (const k of ['init']) {
  Object.defineProperty(_deps, k, {
    configurable: true,
    enumerable: true,
    get() { throw new Error(`profiles.js: dep "${k}" was not configured. Call setProfilesDeps() first.`); },
  });
}

export const setProfilesDeps = (deps) => {
  for (const k of Object.keys(deps)) {
    Object.defineProperty(_deps, k, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: deps[k],
    });
  }
};

// ---------------- DOM helpers ----------------

export const normalizeStorageDirectoryMode = (value) => {
  const mode = String(value || 'global').trim().toLowerCase();
  return ['global', 'version', 'custom'].includes(mode) ? mode : 'global';
};

export const normalizeVersionStorageOverrideMode = (value) => {
  const mode = String(value || 'default').trim().toLowerCase();
  return ['default', 'global', 'version', 'custom'].includes(mode)
    ? mode
    : 'default';
};

export const getCustomStorageDirectoryPath = () =>
  String(state.settingsState.custom_storage_directory || '').trim();

export const getCustomStorageDirectoryError = () => {
  if (normalizeStorageDirectoryMode(state.settingsState.storage_directory) !== 'custom') {
    return '';
  }
  const path = getCustomStorageDirectoryPath();
  if (!path) {
    return 'Custom storage directory is not set. Select a folder before launching.';
  }
  if (state.settingsState.custom_storage_directory_valid === false) {
    return String(
      state.settingsState.custom_storage_directory_error ||
        'Custom storage directory is invalid or no longer exists.'
    );
  }
  return '';
};

export const syncStorageDirectoryUI = () => {
  const storageSelect = getEl('settings-storage-dir');
  const customControls = getEl('settings-storage-custom-controls');
  const pathEl = getEl('settings-storage-path');
  const mode = normalizeStorageDirectoryMode(state.settingsState.storage_directory);
  const path = getCustomStorageDirectoryPath();
  const displayPath = path || 'None';
  const hasError = !!getCustomStorageDirectoryError();

  state.settingsState.storage_directory = mode;

  if (storageSelect) {
    storageSelect.value = mode;
  }
  toggleClass(customControls, 'hidden', mode !== 'custom');

  if (pathEl) {
    pathEl.textContent = displayPath;
    pathEl.title = displayPath;
    pathEl.classList.toggle('is-empty', !path);
    pathEl.classList.toggle('settings-storage-path-invalid', hasError);
  }
};

export const refreshCustomStorageDirectoryValidation = async () => {
  const mode = normalizeStorageDirectoryMode(state.settingsState.storage_directory);
  const path = getCustomStorageDirectoryPath();
  const requestId = ++state.storageDirectoryValidationRequestId;

  if (mode !== 'custom') {
    state.settingsState.custom_storage_directory_valid = true;
    state.settingsState.custom_storage_directory_error = '';
    syncStorageDirectoryUI();
    updateSettingsValidationUI();
    return { ok: true };
  }

  if (!path) {
    state.settingsState.custom_storage_directory_valid = false;
    state.settingsState.custom_storage_directory_error = 'Custom storage directory is not set. Select a folder before launching.';
    syncStorageDirectoryUI();
    updateSettingsValidationUI();
    return { ok: false };
  }

  try {
    const res = await api('/api/storage-directory/validate', 'POST', { path });
    if (requestId !== state.storageDirectoryValidationRequestId) {
      return res;
    }

    const normalizedPath = String((res && res.path) || path).trim();
    state.settingsState.custom_storage_directory = normalizedPath;
    state.settingsState.custom_storage_directory_valid = !!(res && res.ok);
    state.settingsState.custom_storage_directory_error = state.settingsState.custom_storage_directory_valid
      ? ''
      : String(
          (res && (res.error || res.message)) ||
            'Custom storage directory is invalid or no longer exists.'
        );
    syncStorageDirectoryUI();
    updateSettingsValidationUI();
    return res;
  } catch (err) {
    if (requestId !== state.storageDirectoryValidationRequestId) {
      return { ok: false, error: String(err && err.message ? err.message : err) };
    }
    state.settingsState.custom_storage_directory_valid = false;
    state.settingsState.custom_storage_directory_error =
      'Failed to validate the custom storage directory.';
    syncStorageDirectoryUI();
    updateSettingsValidationUI();
    return { ok: false, error: state.settingsState.custom_storage_directory_error };
  }
};

export const isTruthySetting = (value) => {
  return ['1', 'true', 'yes', 'on'].includes(String(value || '').trim().toLowerCase());
};

export const normalizeProfilesList = (profiles) => {
  const normalized = Array.isArray(profiles)
    ? profiles
        .map((p) => ({
          id: String((p && p.id) || '').trim(),
          name: String((p && p.name) || '').trim(),
        }))
        .filter((p) => p.id)
    : [];

  return normalized.length > 0 ? normalized : [{ id: 'default', name: 'Default' }];
};

export const applyProfilesState = (profiles, activeProfile) => {
  state.profilesState.profiles = normalizeProfilesList(profiles);
  const active = String(activeProfile || '').trim() || 'default';
  const exists = state.profilesState.profiles.some((p) => p.id === active);
  state.profilesState.activeProfile = exists ? active : state.profilesState.profiles[0].id;
};

export const getScopeStateRef = (scope) => {
  const key = String(scope || '').trim().toLowerCase();
  if (key === 'versions') return state.versionsProfilesState;
  if (key === 'mods') return state.modsProfilesState;
  return null;
};

export const getScopeApiBase = (scope) => {
  const key = String(scope || '').trim().toLowerCase();
  if (key === 'versions') return '/api/profiles/versions';
  if (key === 'mods') return '/api/profiles/mods';
  return null;
};

export const getScopeProfileSelectId = (scope) => {
  const key = String(scope || '').trim().toLowerCase();
  if (key === 'versions') return 'versions-profile-select';
  if (key === 'mods') return 'mods-profile-select';
  return null;
};

export const getScopeProfileDeleteButtonId = (scope) => {
  const key = String(scope || '').trim().toLowerCase();
  if (key === 'versions') return 'versions-profile-delete-btn';
  if (key === 'mods') return 'mods-profile-delete-btn';
  return null;
};

export const getScopeProfileEditButtonId = (scope) => {
  const key = String(scope || '').trim().toLowerCase();
  if (key === 'versions') return 'versions-profile-edit-btn';
  if (key === 'mods') return 'mods-profile-edit-btn';
  return null;
};

export const getScopeProfileDeleteIconId = (scope) => {
  const key = String(scope || '').trim().toLowerCase();
  if (key === 'versions') return 'versions-profile-delete-icon';
  if (key === 'mods') return 'mods-profile-delete-icon';
  return null;
};

export const getScopeProfileEditIconId = (scope) => {
  const key = String(scope || '').trim().toLowerCase();
  if (key === 'versions') return 'versions-profile-edit-icon';
  if (key === 'mods') return 'mods-profile-edit-icon';
  return null;
};

export const getScopeLabel = (scope) => {
  const key = String(scope || '').trim().toLowerCase();
  if (key === 'versions') return 'Versions';
  if (key === 'mods') return 'Addons';
  return 'Scope';
};

export const applyScopeProfilesState = (scope, profiles, activeProfile) => {
  const stateRef = getScopeStateRef(scope);
  if (!stateRef) return;

  stateRef.profiles = normalizeProfilesList(profiles);
  const active = String(activeProfile || '').trim() || 'default';
  const exists = stateRef.profiles.some((p) => p.id === active);
  stateRef.activeProfile = exists ? active : stateRef.profiles[0].id;
};

export const renderScopeProfilesSelect = (scope) => {
  const stateRef = getScopeStateRef(scope);
  const selectId = getScopeProfileSelectId(scope);
  if (!stateRef || !selectId) return;

  const select = getEl(selectId);
  if (!select) return;

  select.innerHTML = '';
  stateRef.profiles.forEach((profile) => {
    const opt = document.createElement('option');
    opt.value = profile.id;
    opt.textContent = profile.name || profile.id;
    if (profile.id === stateRef.activeProfile) opt.style.fontWeight = 'bold';
    select.appendChild(opt);
  });

  const addOpt = document.createElement('option');
  addOpt.value = ADD_PROFILE_OPTION;
  addOpt.textContent = '+ Add new profile';
  addOpt.style.fontStyle = 'italic';
  addOpt.style.color = 'rgba(255, 255, 255, 0.5)';
  select.appendChild(addOpt);

  select.value = stateRef.activeProfile;
  updateScopeProfileDeleteButtonState(scope);
  updateScopeProfileEditButtonState(scope);
};

export const updateScopeProfileEditButtonState = (scope) => {
  const stateRef = getScopeStateRef(scope);
  const editBtnId = getScopeProfileEditButtonId(scope);
  if (!stateRef || !editBtnId) return;

  const editBtn = getEl(editBtnId);
  if (!editBtn) return;

  const canEdit = !!stateRef.activeProfile && stateRef.activeProfile !== 'default';
  editBtn.disabled = !canEdit;
  editBtn.style.opacity = canEdit ? '1' : '0.5';
  editBtn.style.cursor = canEdit ? 'pointer' : 'not-allowed';
};

export const updateScopeProfileDeleteButtonState = (scope) => {
  const stateRef = getScopeStateRef(scope);
  const deleteBtnId = getScopeProfileDeleteButtonId(scope);
  if (!stateRef || !deleteBtnId) return;

  const deleteBtn = getEl(deleteBtnId);
  if (!deleteBtn) return;

  const canDelete = stateRef.profiles.length > 1 && stateRef.activeProfile !== 'default';
  deleteBtn.disabled = !canDelete;
  deleteBtn.style.opacity = canDelete ? '1' : '0.5';
  deleteBtn.style.cursor = canDelete ? 'pointer' : 'not-allowed';
};

export const showDeleteScopeProfileModal = (scope) => {
  const stateRef = getScopeStateRef(scope);
  const apiBase = getScopeApiBase(scope);
  const scopeLabel = getScopeLabel(scope);
  if (!stateRef || !apiBase) return;

  const active = stateRef.profiles.find((p) => p.id === stateRef.activeProfile);
  const activeName = (active && active.name) || stateRef.activeProfile || 'profile';

  if (stateRef.activeProfile === 'default') {
    showMessageBox({
      title: 'Cannot Delete',
      message: 'The Default profile cannot be deleted.',
      buttons: [{ label: 'OK' }],
    });
    return;
  }

  showMessageBox({
    title: `Delete ${scopeLabel} Profile`,
    message: `Delete profile <b>${activeName}</b>?<br>This will delete all the data stored in the profile and cannot be undone!`,
    buttons: [
      {
        label: 'Delete',
        classList: ['danger'],
        onClick: async () => {
          const res = await api(`${apiBase}/delete`, 'POST', {
            profile_id: stateRef.activeProfile,
          });
          if (!res || !res.ok) {
            showMessageBox({
              title: 'Delete Failed',
              message: (res && res.error) || 'Failed to delete profile.',
              buttons: [{ label: 'OK' }],
            });
            return;
          }
          await _deps.init();
        },
      },
      { label: 'Cancel' },
    ],
  });
};

export const showRenameScopeProfileModal = (scope) => {
  const stateRef = getScopeStateRef(scope);
  const apiBase = getScopeApiBase(scope);
  const scopeLabel = getScopeLabel(scope);
  if (!stateRef || !apiBase) return;

  const active = stateRef.profiles.find((p) => p.id === stateRef.activeProfile);
  const activeName = (active && active.name) || stateRef.activeProfile || '';
  if (!stateRef.activeProfile) {
    renderScopeProfilesSelect(scope);
    return;
  }

  const content = document.createElement('div');

  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.textContent = `Rename active ${scopeLabel.toLowerCase()} profile (1-32 characters):`;

  const input = document.createElement('input');
  input.type = 'text';
  input.maxLength = 32;
  input.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;';
  input.value = activeName;

  content.appendChild(label);
  content.appendChild(input);

  showMessageBox({
    title: `Rename ${scopeLabel} Profile`,
    customContent: content,
    buttons: [
      {
        label: 'Save',
        classList: ['primary'],
        onClick: async () => {
          const name = String(input.value || '').trim();
          if (name.length < 1 || name.length > 32) {
            showMessageBox({
              title: 'Invalid Name',
              message: 'Profile name must be between 1 and 32 characters.',
              buttons: [{ label: 'OK', onClick: () => showRenameScopeProfileModal(scope) }],
            });
            return;
          }

          const res = await api(`${apiBase}/rename`, 'POST', {
            profile_id: stateRef.activeProfile,
            name,
          });
          if (!res || !res.ok) {
            showMessageBox({
              title: 'Rename Failed',
              message: (res && res.error) || 'Failed to rename profile.',
              buttons: [{ label: 'OK', onClick: () => showRenameScopeProfileModal(scope) }],
            });
            return;
          }

          await _deps.init();
        },
      },
      {
        label: 'Cancel',
        onClick: () => {
          renderScopeProfilesSelect(scope);
        },
      },
    ],
  });

  setTimeout(() => {
    input.focus();
    input.select();
  }, 30);
};

export const switchScopeProfile = async (scope, profileId) => {
  const apiBase = getScopeApiBase(scope);
  if (!apiBase) return;

  const res = await api(`${apiBase}/switch`, 'POST', { profile_id: profileId });
  if (!res || !res.ok) {
    showMessageBox({
      title: `${getScopeLabel(scope)} Profile Switch Failed`,
      message: (res && res.error) || 'Failed to switch profile.',
      buttons: [{ label: 'OK' }],
    });
    renderScopeProfilesSelect(scope);
    return;
  }

  await _deps.init();
};

export const showCreateScopeProfileModal = (scope) => {
  const apiBase = getScopeApiBase(scope);
  if (!apiBase) return;

  const scopeLabel = getScopeLabel(scope);
  const content = document.createElement('div');

  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.textContent = `Enter a ${scopeLabel.toLowerCase()} profile name (1-32 characters):`;

  const input = document.createElement('input');
  input.type = 'text';
  input.maxLength = 32;
  input.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;';
  input.placeholder = 'New profile name';

  content.appendChild(label);
  content.appendChild(input);

  showMessageBox({
    title: `Create ${scopeLabel} Profile`,
    customContent: content,
    buttons: [
      {
        label: 'Create',
        classList: ['primary'],
        onClick: async () => {
          const name = String(input.value || '').trim();
          if (name.length < 1 || name.length > 32) {
            showMessageBox({
              title: 'Invalid Name',
              message: 'Profile name must be between 1 and 32 characters.',
              buttons: [{ label: 'OK', onClick: () => showCreateScopeProfileModal(scope) }],
            });
            return;
          }

          const res = await api(`${apiBase}/create`, 'POST', { name });
          if (!res || !res.ok) {
            showMessageBox({
              title: 'Create Failed',
              message: (res && res.error) || 'Failed to create profile.',
              buttons: [{ label: 'OK', onClick: () => showCreateScopeProfileModal(scope) }],
            });
            return;
          }

          await _deps.init();
        },
      },
      {
        label: 'Cancel',
        onClick: () => {
          renderScopeProfilesSelect(scope);
        },
      },
    ],
  });

  setTimeout(() => {
    input.focus();
  }, 30);
};

export const renderProfilesSelect = () => {
  const select = getEl('settings-profile-select');
  if (!select) return;

  select.innerHTML = '';
  state.profilesState.profiles.forEach((profile) => {
    const opt = document.createElement('option');
    opt.value = profile.id;
    opt.textContent = profile.name || profile.id;
    if (profile.id === state.profilesState.activeProfile) opt.style.fontWeight = 'bold';
    select.appendChild(opt);
  });

  const addOpt = document.createElement('option');
  addOpt.value = ADD_PROFILE_OPTION;
  addOpt.textContent = '+ Add new profile';
  addOpt.style.fontStyle = 'italic';
  addOpt.style.color = 'rgba(255, 255, 255, 0.5)';
  select.appendChild(addOpt);

  select.value = state.profilesState.activeProfile;
  updateProfileDeleteButtonState();
  updateProfileEditButtonState();
};

export const updateProfileDeleteButtonState = () => {
  const deleteBtn = getEl('settings-profile-delete-btn');
  if (!deleteBtn) return;
  const canDelete = state.profilesState.profiles.length > 1 && state.profilesState.activeProfile !== 'default';
  deleteBtn.disabled = !canDelete;
  deleteBtn.style.opacity = canDelete ? '1' : '0.5';
  deleteBtn.style.cursor = canDelete ? 'pointer' : 'not-allowed';
};

export const updateProfileEditButtonState = () => {
  const editBtn = getEl('settings-profile-edit-btn');
  if (!editBtn) return;

  const canEdit = !!state.profilesState.activeProfile && state.profilesState.activeProfile !== 'default';
  editBtn.disabled = !canEdit;
  editBtn.style.opacity = canEdit ? '1' : '0.5';
  editBtn.style.cursor = canEdit ? 'pointer' : 'not-allowed';
};

export const switchProfile = async (profileId) => {
  const res = await api('/api/profiles/switch', 'POST', { profile_id: profileId });
  if (!res || !res.ok) {
    showMessageBox({
      title: 'Profile Switch Failed',
      message: (res && res.error) || 'Failed to switch profile.',
      buttons: [{ label: 'OK' }],
    });
    renderProfilesSelect();
    return;
  }
  await _deps.init();
};

export const showCreateProfileModal = () => {
  const content = document.createElement('div');

  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.textContent = 'Enter a profile name (1-32 characters):';

  const input = document.createElement('input');
  input.type = 'text';
  input.maxLength = 32;
  input.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;';
  input.placeholder = 'New profile name';

  content.appendChild(label);
  content.appendChild(input);

  showMessageBox({
    title: 'Create Profile',
    customContent: content,
    buttons: [
      {
        label: 'Create',
        classList: ['primary'],
        onClick: async () => {
          const name = String(input.value || '').trim();
          if (name.length < 1 || name.length > 32) {
            showMessageBox({
              title: 'Invalid Name',
              message: 'Profile name must be between 1 and 32 characters.',
              buttons: [{ label: 'OK', onClick: () => showCreateProfileModal() }],
            });
            return;
          }

          const res = await api('/api/profiles/create', 'POST', { name });
          if (!res || !res.ok) {
            showMessageBox({
              title: 'Create Failed',
              message: (res && res.error) || 'Failed to create profile.',
              buttons: [{ label: 'OK', onClick: () => showCreateProfileModal() }],
            });
            return;
          }

          await _deps.init();
        },
      },
      {
        label: 'Cancel',
        onClick: () => {
          renderProfilesSelect();
        },
      },
    ],
  });

  setTimeout(() => {
    input.focus();
  }, 30);
};

export const showDeleteProfileModal = () => {
  const active = state.profilesState.profiles.find((p) => p.id === state.profilesState.activeProfile);
  const activeName = (active && active.name) || state.profilesState.activeProfile || 'profile';

  if (state.profilesState.activeProfile === 'default') {
    showMessageBox({
      title: 'Cannot Delete',
      message: 'The Default profile cannot be deleted.',
      buttons: [{ label: 'OK' }],
    });
    return;
  }

  showMessageBox({
    title: 'Delete Profile',
    message: `Delete profile <b>${activeName}</b>?<br><i>This will delete all the data stored in the profile and cannot be undone!</i>` ,
    buttons: [
      {
        label: 'Delete',
        classList: ['danger'],
        onClick: async () => {
          const res = await api('/api/profiles/delete', 'POST', {
            profile_id: state.profilesState.activeProfile,
          });
          if (!res || !res.ok) {
            showMessageBox({
              title: 'Delete Failed',
              message: (res && res.error) || 'Failed to delete profile.',
              buttons: [{ label: 'OK' }],
            });
            return;
          }
          await _deps.init();
        },
      },
      { label: 'Cancel' },
    ],
  });
};

export const showRenameProfileModal = () => {
  const active = state.profilesState.profiles.find((p) => p.id === state.profilesState.activeProfile);
  const activeName = (active && active.name) || state.profilesState.activeProfile || '';

  if (!state.profilesState.activeProfile) {
    renderProfilesSelect();
    return;
  }

  const content = document.createElement('div');

  const label = document.createElement('p');
  label.style.marginBottom = '8px';
  label.textContent = 'Rename active profile (1-32 characters):';

  const input = document.createElement('input');
  input.type = 'text';
  input.maxLength = 32;
  input.style.cssText = 'width:100%;box-sizing:border-box;padding:6px 8px;';
  input.value = activeName;

  content.appendChild(label);
  content.appendChild(input);

  showMessageBox({
    title: 'Rename Profile',
    customContent: content,
    buttons: [
      {
        label: 'Save',
        classList: ['primary'],
        onClick: async () => {
          const name = String(input.value || '').trim();
          if (name.length < 1 || name.length > 32) {
            showMessageBox({
              title: 'Invalid Name',
              message: 'Profile name must be between 1 and 32 characters.',
              buttons: [{ label: 'OK', onClick: () => showRenameProfileModal() }],
            });
            return;
          }

          const res = await api('/api/profiles/rename', 'POST', {
            profile_id: state.profilesState.activeProfile,
            name,
          });
          if (!res || !res.ok) {
            showMessageBox({
              title: 'Rename Failed',
              message: (res && res.error) || 'Failed to rename profile.',
              buttons: [{ label: 'OK', onClick: () => showRenameProfileModal() }],
            });
            return;
          }

          await _deps.init();
        },
      },
      {
        label: 'Cancel',
        onClick: () => {
          renderProfilesSelect();
        },
      },
    ],
  });

  setTimeout(() => {
    input.focus();
    input.select();
  }, 30);
};
