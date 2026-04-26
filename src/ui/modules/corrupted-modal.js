// ui/modules/corrupted-modal.js

import { api } from './api.js';
import { showMessageBox } from './modal.js';
import { debug } from './home.js';

let corruptedCheckPromise = null;
let lastCorruptedSignature = '';

const _deps = {};
for (const k of ['refreshInitialData']) {
  Object.defineProperty(_deps, k, {
    configurable: true,
    enumerable: true,
    get() {
      throw new Error('corrupted-modal.js dep "' + k + '" not initialized; call setCorruptedModalDeps() first');
    },
  });
}

export function setCorruptedModalDeps(deps) {
  for (const [k, v] of Object.entries(deps)) {
    Object.defineProperty(_deps, k, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: v,
    });
  }
}


const showCorruptedVersionsModal = (corruptedList) => {
  if (!corruptedList || corruptedList.length === 0) {
    return;
  }

  const selectedVersions = {};

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
                debug(`[corrupted] Deleted ${deleteResult.deleted.length} version(s)`);
                lastCorruptedSignature = '';
                await _deps.refreshInitialData();
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

export const checkForCorruptedVersions = async () => {
  if (corruptedCheckPromise) return corruptedCheckPromise;

  corruptedCheckPromise = (async () => {
    try {
      const result = await api('/api/corrupted-versions');
      if (result.ok && result.corrupted && result.corrupted.length > 0) {
        const signature = JSON.stringify(
          result.corrupted
            .map((v) => `${v.category || ''}/${v.folder || ''}`)
            .sort()
        );
        if (signature === lastCorruptedSignature) return;
        lastCorruptedSignature = signature;
        showCorruptedVersionsModal(result.corrupted);
      }
    } catch (e) {
      console.error('[corrupted] Error checking corrupted versions:', e);
    } finally {
      corruptedCheckPromise = null;
    }
  })();

  return corruptedCheckPromise;
};
