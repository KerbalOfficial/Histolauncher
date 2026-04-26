// ui/modules/version-controls.js

import { state } from './state.js';
import { api, createOperationId, requestOperationCancel } from './api.js';
import { $$, getEl, bindKeyboardActivation } from './dom-utils.js';
import { showMessageBox, showLoadingOverlay, hideLoadingOverlay } from './modal.js';
import { unicodeList } from './config.js';
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
      triggers.forEach((trigger) => {
        trigger.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      });
      const indicator = toggle.querySelector('.section-dropdown-indicator');
      if (indicator) {
        indicator.textContent = expanded ? unicodeList.dropdown_open : unicodeList.dropdown_close;
      }
      body.classList.toggle('hidden', !expanded);
    };

    const handleToggle = () => {
      const expanded = toggle.getAttribute('aria-expanded') !== 'false';
      setExpanded(!expanded);
    };

    triggers.forEach((trigger) => {
      trigger.addEventListener('click', handleToggle);
      bindKeyboardActivation(trigger);
    });

    toggle.dataset.dropdownBound = '1';
    setExpanded(true);
  });
};

export const handleExportVersions = async () => {
  // Check if a version is selected
  if (!state.selectedVersion) {
    showMessageBox({ title: 'Export Error', message: 'Please select a version to export first!', buttons: [{ label: 'OK' }] });
    return;
  }

  try {
    // Parse state.selectedVersion (format: "Category/folder")
    const [category, folder] = state.selectedVersion.split('/');

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
        <div class="export-version-modal">
          <div class="export-version-target">
            Exporting <b>${category}/${folder}</b>
          </div>

          <div class="export-version-options">
            <div class="export-version-options-title">Include Options</div>

            <label class="export-version-option-row">
              <input type="checkbox" id="export-loaders" checked>
              <span>Include installed Mod Loaders</span>
            </label>

            <label class="export-version-option-row">
              <input type="checkbox" id="export-assets" checked>
              <span>Include assets</span>
            </label>

            <label class="export-version-option-row">
              <input type="checkbox" id="export-config">
              <span>Local version configuration & saves</span>
            </label>
          </div>

          <div class="export-version-compression-wrap">
            <label for="export-compression" class="export-version-options-title">Compression Level</label>

            <select id="export-compression" class="export-version-compression-select">
              <option value="quick">Fast</option>
              <option value="standard" selected>Regular</option>
              <option value="full">Maximum</option>
            </select>

            <div id="compression-hint" class="export-version-hint">
              Balanced speed and file size
            </div>
          </div>
        </div>
      `;

      showMessageBox({
        title: 'Export Version',
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

      const operationId = createOperationId('version_export');
      let cancelRequested = false;

      showLoadingOverlay('Exporting version...', {
        buttons: [
          {
            label: 'Cancel',
            classList: ['danger'],
            closeOnClick: false,
            onClick: async (_values, controls) => {
              if (cancelRequested) return;
              cancelRequested = true;
              controls.update({
                message: 'Cancelling export... If a save dialog opened, close it to finish cancelling.',
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
          showMessageBox({ title: 'Export Cancelled', message: 'You cancelled the export', buttons: [{ label: 'OK' }] });
        } else {
          showMessageBox({ title: 'Export Error', message: result.error || 'Failed to export version', buttons: [{ label: 'OK' }] });
        }
        return;
      }

      const fileSize = (result.size_bytes / 1024 / 1024).toFixed(2);
      showMessageBox({ title: 'Export Successful!', message: `File saved to:<br><b>${result.filepath}</b><br><br>File size<br><b>${fileSize} MB</b>`, buttons: [{ label: 'OK' }] });
      await _deps.init();
    });
  } catch (e) {
    hideLoadingOverlay();
    console.error('Export error:', e);
    showMessageBox({ title: 'Export Error', message: 'An error occurred during export:<br><br>' + e.message, buttons: [{ label: 'OK' }] });
  }
};

export const handleImportVersions = () => {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.hlvdf';
  input.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    try {
      const filename = file.name;

      // Extract version name from filename - remove .hlvdf extension if present
      const versionName = filename.endsWith('.hlvdf') ? filename.slice(0, -6) : filename;

      if (!versionName || versionName.length === 0) {
        hideLoadingOverlay();

        showMessageBox({
          title: 'Import Error',
          message: 'Invalid filename. Please use a valid .hlvdf file.',
          buttons: [{ label: 'OK' }]
        });
        return;
      }

      // Use FormData to send file directly (no base64 conversion needed)
      const operationId = createOperationId('version_import');
      let cancelRequested = false;
      const formData = new FormData();
      formData.append('version_name', versionName);
      formData.append('zip_file', file); // The File object directly
      formData.append('operation_id', operationId);

      showLoadingOverlay('Importing version...', {
        buttons: [
          {
            label: 'Cancel',
            classList: ['danger'],
            closeOnClick: false,
            onClick: async (_values, controls) => {
              if (cancelRequested) return;
              cancelRequested = true;
              controls.update({
                message: 'Cancelling import...',
                buttons: [],
              });
              await requestOperationCancel(operationId);
            },
          },
        ],
      });

      // Send to backend using FormData (multipart/form-data encoding)
      // The browser will handle streaming large files without converting to strings
      _deps.debug('Sending import request with file size:', file.size);

      try {
        const response = await fetch('/api/versions/import', {
          method: 'POST',
          body: formData
          // Note: Don't set Content-Type header - browser will set it with boundary
        });

        const result = await response.json();

        hideLoadingOverlay();

        if (!result.ok) {
          if (result.cancelled || String(result.error || '').toLowerCase().includes('cancelled')) {
            showMessageBox({
              title: 'Import Cancelled',
              message: 'You cancelled the import.',
              buttons: [{ label: 'OK' }]
            });
            return;
          }
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
        await _deps.init();
      } catch (e) {
        hideLoadingOverlay();

        console.error('Import error:', e);
        showMessageBox({
          title: 'Import Error',
          message: 'An error occurred during import: ' + e.message,
          buttons: [{ label: 'OK' }]
        });
      }
    } catch (e) {
      hideLoadingOverlay();
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
