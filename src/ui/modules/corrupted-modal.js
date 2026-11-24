// ui/modules/corrupted-modal.js

import { api } from './api.js';
import { showMessageBox } from './modal.js';
import { debug } from './home.js';
import { t } from './i18n.js';
import { escapeInfoHtml } from './string-utils.js';
import { startInstallForFolder } from './install.js';

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


const showVersionPickerModal = ({ list, idPrefix, title, prompt, buttons }) => new Promise((resolve) => {
  if (!list || list.length === 0) {
    resolve();
    return;
  }

  const idFor = (v) => `${idPrefix}-${v.category}-${v.folder}`.replace(/\s+/g, '-').toLowerCase();

  let checkboxHtml = '<div class="row" style="display:grid;gap:8px;max-height:300px;overflow-y:auto;padding:8px 0;">';

  list.forEach((v) => {
    const id = idFor(v);

    checkboxHtml += `
      <label class="corrupted-version-item">
        <input type="checkbox" id="${id}" data-version-id="${id}">
        <span style="font-size:13px;">${escapeInfoHtml(v.folder)} (${escapeInfoHtml(v.category)})</span>
      </label>
    `;
  });

  checkboxHtml += '</div>';

  const message = `
    <div style="padding: 8px 0;">
      <p style="margin: 0 0 12px 0; color: var(--color-text-muted); font-size: 13px;">
        ${prompt}
      </p>
      ${checkboxHtml}
    </div>
  `;

  showMessageBox({
    title,
    message,
    onClose: () => setTimeout(resolve, 0),
    buttons: [
      ...buttons.map((b) => ({
        label: b.label,
        classList: b.classList,
        onClick: () => {
          const checked = new Set(
            [...document.querySelectorAll('input[data-version-id]:checked')]
              .map((el) => el.getAttribute('data-version-id'))
          );
          const selected = list.filter((v) => checked.has(idFor(v)));
          if (selected.length > 0) b.onSelected(selected);
        },
      })),
      { label: t('common.cancel') },
    ],
  });
});

const deleteVersions = async (versions) => {
  const showDeleteError = (error) => showMessageBox({
    title: t('common.error'),
    message: t('versions.corrupted.deleteFailed', { error: escapeInfoHtml(error || t('common.unknownError')) }),
    buttons: [{ label: t('common.ok') }],
  });

  try {
    const deleteResult = await api('/api/delete-corrupted-versions', 'POST', {
      versions: versions.map(({ category, folder }) => ({ category, folder })),
    });

    if (deleteResult.ok) {
      debug(`[corrupted] Deleted ${deleteResult.deleted.length} version(s)`);
      lastCorruptedSignature = '';
      await _deps.refreshInitialData();
    } else {
      console.error('[corrupted] Delete failed:', deleteResult.error);
      showDeleteError(deleteResult.error);
    }
  } catch (e) {
    console.error('[corrupted] Error deleting:', e);
    showDeleteError(e.message);
  }
};

const redownloadVersions = async (versions) => {
  const failed = [];
  for (const v of versions) {
    const key = await startInstallForFolder(v.folder, v.category, v.full_assets !== false, { forceRedownload: true });
    if (!key) failed.push(v.folder);
  }

  await _deps.refreshInitialData();
  const versionsTab = document.querySelector('.sidebar-item[data-page="versions"]');
  if (versionsTab) versionsTab.click();

  if (failed.length > 0) {
    showMessageBox({
      title: t('common.error'),
      message: t('versions.vulnerable.redownloadFailed', { versions: escapeInfoHtml(failed.join(', ')) }),
      buttons: [{ label: t('common.ok') }],
    });
  }
};

const showCorruptedVersionsModal = (corruptedList) => showVersionPickerModal({
  list: corruptedList,
  idPrefix: 'corrupted',
  title: t('versions.corrupted.title'),
  prompt: t('versions.corrupted.prompt'),
  buttons: [
    { label: t('versions.corrupted.deleteSelected'), classList: ['danger'], onSelected: deleteVersions },
  ],
});

export const checkForVulnerableVersions = async () => {
  try {
    const result = await api('/api/vulnerable-versions');
    if (!result.ok || !result.vulnerable || result.vulnerable.length === 0) return;
    await showVersionPickerModal({
      list: result.vulnerable,
      idPrefix: 'vulnerable',
      title: t('versions.vulnerable.title'),
      prompt: t('versions.vulnerable.prompt'),
      buttons: [
        { label: t('versions.vulnerable.redownloadSelected'), classList: ['primary'], onSelected: redownloadVersions },
        { label: t('versions.corrupted.deleteSelected'), classList: ['danger'], onSelected: deleteVersions },
      ],
    });
  } catch (e) {
    console.error('[vulnerable] Error checking vulnerable versions:', e);
  }
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
        await showCorruptedVersionsModal(result.corrupted);
      }
    } catch (e) {
      console.error('[corrupted] Error checking corrupted versions:', e);
    } finally {
      corruptedCheckPromise = null;
    }
  })();

  return corruptedCheckPromise;
};
