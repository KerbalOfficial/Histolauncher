// ui/modules/version-controls.js

import { state } from './state.js';
import { api, createOperationId, requestOperationCancel } from './api.js';
import { $$, getEl, bindKeyboardActivation } from './dom-utils.js';
import { showMessageBox, showLoadingOverlay, hideLoadingOverlay } from './modal.js';
import { unicodeList } from './config.js';
import { t } from './i18n.js';
import { escapeInfoHtml } from './string-utils.js';
import {
  setVersionsBulkMode,
  updateVersionsBulkActionsUI,
  bulkDeleteSelectedVersions,
} from './versions.js';

const _deps = {};
for (const k of ['autoSaveSetting', 'debug', 'init', 'loadAvailableVersions']) {
  Object.defineProperty(_deps, k, {
    configurable: true,
    enumerable: true,
    get() { throw new Error(`version-controls.js: dep "${k}" was not configured. Call setVersionControlsDeps() first.`); },
  });
}

export const setVersionControlsDeps = (deps) => {
  for (const k of Object.keys(deps)) {
    Object.defineProperty(_deps, k, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: deps[k],
    });
  }
};

// ---------------- View Toggle (Grid/List) ----------------

export const applyVersionsViewMode = () => {
  const viewMode = state.settingsState.versions_view || 'grid';
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

export const initVersionsViewToggle = () => {
  const gridBtn = getEl('view-grid-btn');
  const listBtn = getEl('view-list-btn');

  if (gridBtn) {
    gridBtn.addEventListener('click', () => {
      if (state.settingsState.versions_view !== 'grid') {
        state.settingsState.versions_view = 'grid';
        applyVersionsViewMode();
        _deps.autoSaveSetting('versions_view', 'grid');
      }
    });
  }

  if (listBtn) {
    listBtn.addEventListener('click', () => {
      if (state.settingsState.versions_view !== 'list') {
        state.settingsState.versions_view = 'list';
        applyVersionsViewMode();
        _deps.autoSaveSetting('versions_view', 'list');
      }
    });
  }

  applyVersionsViewMode();
};

export const initCollapsibleSections = () => {
  $$('.collapsible-section').forEach((section, index) => {
    const toggle = section.querySelector('.section-dropdown-toggle');
    const body = section.querySelector('.section-dropdown-body');
    const triggers = Array.from(section.querySelectorAll('.section-dropdown-trigger'));

    if (!toggle || !body) {
      return;
    }

    const key = section.id || `collapsible-section-${index}`;

    const setExpanded = (expanded, { persist = true } = {}) => {
      section.classList.toggle('collapsed', !expanded);
      toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      triggers.forEach((trigger) => {
        trigger.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      });
      const indicator = toggle.querySelector('.section-dropdown-indicator');
      if (indicator) {
        indicator.textContent = expanded ? unicodeList.dropdown_open : unicodeList.dropdown_close;
      }
      body.classList.toggle('hidden', !expanded);
      if (persist) state.collapsibleSectionExpanded[key] = !!expanded;
    };

    const hasStoredState = Object.prototype.hasOwnProperty.call(state.collapsibleSectionExpanded, key);
    const initialExpanded = hasStoredState ? !!state.collapsibleSectionExpanded[key] : true;

    if (toggle.dataset.dropdownBound === '1') {
      setExpanded(initialExpanded, { persist: false });
      return;
    }

    const handleToggle = () => {
      const expanded = toggle.getAttribute('aria-expanded') !== 'false';
      setExpanded(!expanded);
    };

    triggers.forEach((trigger) => {
      trigger.addEventListener('click', handleToggle);
      bindKeyboardActivation(trigger);
    });

    toggle.dataset.dropdownBound = '1';
    setExpanded(initialExpanded, { persist: false });
  });
};

export const handleExportVersions = async () => {
  // Check if a version is selected
  if (!state.selectedVersion) {
    showMessageBox({
      title: t('versions.export.errorTitle'),
      message: t('versions.export.selectVersionFirst'),
      buttons: [{ label: t('common.ok') }],
    });
    return;
  }

  try {
    // Parse state.selectedVersion (format: "Category/folder")
    const [category, folder] = state.selectedVersion.split('/');

    if (!category || !folder) {
      showMessageBox({
        title: t('versions.export.errorTitle'),
        message: t('versions.export.invalidSelection'),
        buttons: [{ label: t('common.ok') }],
      });
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
      const wrap = document.createElement('div');
      wrap.className = 'export-version-modal';

      const target = document.createElement('div');
      target.className = 'export-version-target';
      const targetMarker = '__TARGET_VERSION__';
      const targetText = t('versions.export.exportingTarget', { target: targetMarker });
      const targetParts = targetText.split(targetMarker);
      target.appendChild(document.createTextNode(targetParts[0] || ''));
      const targetName = document.createElement('b');
      targetName.textContent = `${category}/${folder}`;
      target.appendChild(targetName);
      target.appendChild(document.createTextNode(targetParts.slice(1).join(targetMarker)));
      wrap.appendChild(target);

      const optionsWrap = document.createElement('div');
      optionsWrap.className = 'export-version-options';
      const optionsTitle = document.createElement('div');
      optionsTitle.className = 'export-version-options-title';
      optionsTitle.textContent = t('versions.export.includeOptions');
      optionsWrap.appendChild(optionsTitle);

      const makeCheckboxRow = ({ id, checked, label }) => {
        const row = document.createElement('label');
        row.className = 'export-version-option-row';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.id = id;
        input.checked = checked;
        const text = document.createElement('span');
        text.textContent = label;
        row.appendChild(input);
        row.appendChild(text);
        optionsWrap.appendChild(row);
        return input;
      };

      const loadersInput = makeCheckboxRow({
        id: 'export-loaders',
        checked: true,
        label: t('versions.export.includeLoaders'),
      });
      const assetsInput = makeCheckboxRow({
        id: 'export-assets',
        checked: true,
        label: t('versions.export.includeAssets'),
      });
      const configInput = makeCheckboxRow({
        id: 'export-config',
        checked: false,
        label: t('versions.export.includeConfig'),
      });
      wrap.appendChild(optionsWrap);

      const compressionWrap = document.createElement('div');
      compressionWrap.className = 'export-version-compression-wrap';
      const compressionLabel = document.createElement('label');
      compressionLabel.htmlFor = 'export-compression';
      compressionLabel.className = 'export-version-options-title';
      compressionLabel.textContent = t('versions.export.compressionLevel');

      const compressionSelect = document.createElement('select');
      compressionSelect.id = 'export-compression';
      compressionSelect.className = 'export-version-compression-select';
      [
        ['quick', t('versions.export.compression.fast')],
        ['standard', t('versions.export.compression.regular')],
        ['full', t('versions.export.compression.maximum')],
      ].forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        option.selected = value === 'standard';
        compressionSelect.appendChild(option);
      });

      const compressionHint = document.createElement('div');
      compressionHint.id = 'compression-hint';
      compressionHint.className = 'export-version-hint';
      compressionHint.textContent = t('versions.export.compressionHint.standard');
      compressionSelect.addEventListener('change', (e) => {
        const hints = {
          quick: t('versions.export.compressionHint.quick'),
          standard: t('versions.export.compressionHint.standard'),
          full: t('versions.export.compressionHint.full')
        };
        compressionHint.textContent = hints[e.target.value] || '';
      });

      compressionWrap.appendChild(compressionLabel);
      compressionWrap.appendChild(compressionSelect);
      compressionWrap.appendChild(compressionHint);
      wrap.appendChild(compressionWrap);

      showMessageBox({
        title: t('versions.export.title'),
        customContent: wrap,
        buttons: [
          {
            label: t('common.export'),
            classList: ['primary'],
            onClick: async () => {
              exportOptions.include_loaders = loadersInput.checked;
              exportOptions.include_assets = assetsInput.checked;
              exportOptions.include_config = configInput.checked;
              exportOptions.compression = compressionSelect.value;
              resolve(true);
            }
          },
          {
            label: t('common.cancel'),
            onClick: () => resolve(false)
          }
        ]
      });
    }).then(async (confirmed) => {
      if (!confirmed) return;

      const operationId = createOperationId('version_export');
      let cancelRequested = false;

      showLoadingOverlay(t('versions.export.exporting'), {
        buttons: [
          {
            label: t('common.cancel'),
            classList: ['danger'],
            closeOnClick: false,
            onClick: async (_values, controls) => {
              if (cancelRequested) return;
              cancelRequested = true;
              controls.update({
                message: t('versions.export.cancelling'),
                buttons: [],
              });
              await requestOperationCancel(operationId);
            },
          },
        ],
      });

      const result = await api('/api/versions/export', 'POST', {
        category,
        folder,
        export_options: exportOptions,
        operation_id: operationId,
      });

      hideLoadingOverlay();

      if (!result.ok) {
        if (result.cancelled || String(result.error || '').toLowerCase().includes('cancelled')) {
          showMessageBox({ title: t('versions.export.cancelledTitle'), message: t('versions.export.cancelledMessage'), buttons: [{ label: t('common.ok') }] });
        } else {
          showMessageBox({ title: t('versions.export.errorTitle'), message: result.error || t('versions.export.failed'), buttons: [{ label: t('common.ok') }] });
        }
        return;
      }

      const fileSize = (result.size_bytes / 1024 / 1024).toFixed(2);
      showMessageBox({
        title: t('versions.export.successTitle'),
        message: t('versions.export.successMessage', { filepath: result.filepath, size: fileSize }),
        buttons: [{ label: t('common.ok') }],
      });
      await _deps.init();
    });
  } catch (e) {
    hideLoadingOverlay();
    console.error('Export error:', e);
    showMessageBox({ title: t('versions.export.errorTitle'), message: t('versions.export.unexpectedError', { error: e.message }), buttons: [{ label: t('common.ok') }] });
  }
};

export const handleImportVersions = async () => {
  const operationId = createOperationId('version_import');
  let cancelRequested = false;

  showLoadingOverlay(t('versions.import.importing'), {
    buttons: [
      {
        label: t('common.cancel'),
        classList: ['danger'],
        closeOnClick: false,
        onClick: async (_values, controls) => {
          if (cancelRequested) return;
          cancelRequested = true;
          controls.update({
            message: t('versions.import.cancelling'),
            buttons: [],
          });
          await requestOperationCancel(operationId);
        },
      },
    ],
  });

  try {
    _deps.debug('Opening backend version import picker');
    const result = await api('/api/versions/import-select', 'POST', {
      operation_id: operationId,
    });

    hideLoadingOverlay();

    if (!result || !result.ok) {
      const resultError = result && result.error ? result.error : '';
      if ((result && result.cancelled) || String(resultError).toLowerCase().includes('cancelled')) {
        showMessageBox({
          title: t('versions.import.cancelledTitle'),
          message: t('versions.import.cancelledMessage'),
          buttons: [{ label: t('common.ok') }]
        });
        return;
      }
      showMessageBox({
        title: t('versions.import.errorTitle'),
        message: resultError || t('versions.import.failed'),
        buttons: [{ label: t('common.ok') }]
      });
      return;
    }

    const versionName = result.folder || result.version_name || 'imported version';
    showMessageBox({
      title: t('versions.import.successTitle'),
      message: t('versions.import.successMessage', { version: escapeInfoHtml(versionName) }),
      buttons: [{ label: t('common.ok') }]
    });

    await _deps.init();
  } catch (e) {
    hideLoadingOverlay();
    console.error('Import error:', e);
    showMessageBox({
      title: t('versions.import.errorTitle'),
      message: t('versions.import.unexpectedError', { error: escapeInfoHtml(e.message) }),
      buttons: [{ label: t('common.ok') }]
    });
  }
};

export const initVersionsExportImport = () => {
  const exportBtn = getEl('export-versions-btn');
  const importBtn = getEl('import-versions-btn');
  const bulkToggleBtn = getEl('versions-bulk-toggle-btn');
  const bulkDeleteBtn = getEl('versions-bulk-delete-btn');
  const refreshBtn = getEl('versions-refresh-btn');

  if (exportBtn) {
    exportBtn.addEventListener('click', handleExportVersions);
  }

  if (importBtn) {
    importBtn.addEventListener('click', handleImportVersions);
  }

  if (bulkToggleBtn) {
    bulkToggleBtn.addEventListener('click', () => {
      setVersionsBulkMode(!state.versionsBulkState.enabled);
    });
  }

  if (bulkDeleteBtn) {
    bulkDeleteBtn.addEventListener('click', () => {
      bulkDeleteSelectedVersions({ skipConfirm: state.isShiftDown });
    });
  }

  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      state.versionsAvailablePage = 1;
      _deps.loadAvailableVersions({ force: true });
    });
  }

  updateVersionsBulkActionsUI();
};
