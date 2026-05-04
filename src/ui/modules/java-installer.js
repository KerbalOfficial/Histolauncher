import { api } from './api.js';
import {
  hideLoadingOverlay,
  showLoadingOverlay,
  showMessageBox,
} from './modal.js';
import { escapeInfoHtml, formatBytes } from './string-utils.js';
import { t } from './i18n.js';

const JAVA_ACCENT = '#f89820';
const RECOMMENDED_ACCENT = '#1f84e2';

const parseJavaVersion = (value) => {
  const parsed = Number.parseInt(String(value || ''), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
};

const environmentLabel = (env = {}) => {
  const osName = String(env.os || env.platform || '').trim();
  const arch = String(env.architecture || env.machine || '').trim();
  return [osName, arch].filter(Boolean).join(' ');
};

const refreshDetectedJavaRuntimes = async () => {
  try {
    const result = await api('/api/java-runtimes-refresh', 'GET');
    window.dispatchEvent(new CustomEvent('histolauncher:java-runtimes-refreshed', {
      detail: result,
    }));
    return result;
  } catch (err) {
    console.warn('Failed to refresh Java runtime detection:', err);
    return { ok: false, error: err?.message || String(err || '') };
  }
};

export const installJavaRuntime = async (version) => {
  const javaVersion = parseJavaVersion(version);
  if (!javaVersion) {
    showMessageBox({
      title: t('java.download.errorTitle'),
      message: t('java.download.invalidVersion'),
      buttons: [{ label: t('common.ok'), classList: ['primary'] }],
    });
    return { ok: false, error: t('java.download.invalidVersionShort') };
  }

  showLoadingOverlay(t('java.download.downloading', { version: javaVersion }), {
    image: 'assets/images/java_icon.png',
    boxClassList: ['activity-box'],
  });

  try {
    const res = await api('/api/java-download', 'POST', { version: javaVersion });
    hideLoadingOverlay();

    if (!res || !res.ok) {
      showMessageBox({
        title: t('java.download.errorTitle'),
        message: escapeInfoHtml(res?.error || t('java.download.failed')),
        buttons: [{ label: t('common.ok'), classList: ['primary'] }],
      });
      return res || { ok: false };
    }

    const actualVersion = parseJavaVersion(res.feature_version) || javaVersion;
    const fileName = escapeInfoHtml(res.file_name || t('java.download.installerFallback'));
    const path = escapeInfoHtml(res.path || '');
    const sizeText = formatBytes(Number(res.size || 0));
    const installed = res.installed === true;
    const installDir = escapeInfoHtml(res.install_dir || '');
    const runtimePath = escapeInfoHtml(res.runtime_path || '');
    const opened = res.opened !== false;
    const openError = escapeInfoHtml(res.open_error || '');
    const title = installed
      ? t('java.download.runtimeInstalledTitle')
      : (opened ? t('java.download.installerOpenedTitle') : t('java.download.downloadedTitle'));
    let message = installed
      ? t('java.download.runtimeInstalledMessage', { version: actualVersion, file: fileName })
      : t(opened ? 'java.download.installerOpenedMessage' : 'java.download.downloadedMessage', { version: actualVersion, file: fileName });
    if (sizeText) message += `<br>${escapeInfoHtml(sizeText)}`;
    if (installDir) message += `<br><br>${installDir}`;
    if (runtimePath) message += `<br>${runtimePath}`;
    if (path && !installed) message += `<br><br>${path}`;
    if (!opened && openError) message += `<br><br>${openError}`;

    showMessageBox({
      title,
      message,
      image: 'assets/images/java_icon.png',
      buttons: [
        {
          label: t('common.ok'),
          classList: ['primary'],
          onClick: () => refreshDetectedJavaRuntimes(),
        },
      ],
    });
    refreshDetectedJavaRuntimes();
    return res;
  } catch (err) {
    hideLoadingOverlay();
    showMessageBox({
      title: t('java.download.errorTitle'),
      message: escapeInfoHtml(err?.message || String(err || t('java.download.failed'))),
      buttons: [{ label: t('common.ok'), classList: ['primary'] }],
    });
    return { ok: false, error: err?.message || String(err || '') };
  }
};

const makeJavaCard = ({ option, meta, onPick }) => {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.style.cssText =
    `width:100%;background:var(--color-surface-card);border:1px solid var(--color-border-strong);border-left:3px solid ${option.recommended ? RECOMMENDED_ACCENT : JAVA_ACCENT};` +
    'padding:8px 12px;display:flex;justify-content:space-between;align-items:center;text-align:left;color:var(--color-text-primary);';

  const left = document.createElement('div');
  left.style.cssText = 'min-width:0;';

  const title = document.createElement('div');
  title.style.cssText = `color:${option.recommended ? RECOMMENDED_ACCENT : JAVA_ACCENT};font-weight:700;line-height:1.2;`;
  title.textContent = option.label || `Java ${option.version || ''}`.trim();

  const subtitle = document.createElement('div');
  subtitle.style.cssText = 'color:var(--color-text-muted);font-size:12px;line-height:1.2;margin-top:2px;';
  subtitle.textContent = option.description || '';
  if (!subtitle.textContent) subtitle.style.display = 'none';

  const details = document.createElement('div');
  details.style.cssText = 'color:var(--color-text-dim);font-size:11px;line-height:1.2;margin-top:2px;';
  details.textContent = [meta, option.recommended ? t('java.install.recommended') : '']
    .filter(Boolean)
    .join(' | ');
  if (!details.textContent) details.style.display = 'none';

  left.appendChild(title);
  left.appendChild(subtitle);
  left.appendChild(details);
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

export const showJavaInstallChooser = async () => {
  showLoadingOverlay(t('java.install.loadingRuntimes'), {
    image: 'assets/images/java_icon.png',
    boxClassList: ['activity-box'],
  });

  let data = null;
  try {
    data = await api('/api/java-install-options', 'GET');
  } catch (err) {
    hideLoadingOverlay();
    showMessageBox({
      title: t('java.install.errorTitle'),
      message: escapeInfoHtml(err?.message || String(err || t('java.install.failedLoadRuntimes'))),
      buttons: [{ label: t('common.ok'), classList: ['primary'] }],
    });
    return false;
  }
  hideLoadingOverlay();

  if (!data || !data.ok) {
    showMessageBox({
      title: t('java.install.errorTitle'),
      message: escapeInfoHtml(data?.error || t('java.install.noDownloadsAvailable')),
      buttons: [{ label: t('common.ok'), classList: ['primary'] }],
    });
    return false;
  }

  const options = Array.isArray(data.options) ? data.options : [];
  if (!options.length) {
    showMessageBox({
      title: t('java.install.errorTitle'),
      message: t('java.install.noDownloadsAvailable'),
      buttons: [{ label: t('common.ok'), classList: ['primary'] }],
    });
    return false;
  }

  return new Promise((resolve) => {
    let resolved = false;
    let controls = null;
    const meta = environmentLabel(data.environment);

    const safeResolve = (value, closeBox = true) => {
      if (resolved) return;
      resolved = true;
      resolve(value);
      if (closeBox) {
        try {
          controls?.close?.();
        } catch (err) {
          console.warn('Failed to close Java install chooser:', err);
        }
      }
    };

    const wrap = document.createElement('div');
    wrap.style.cssText = 'max-height:60vh;overflow-y:auto;padding:10px;text-align:center;';

    const list = document.createElement('div');
    list.style.cssText = 'display:grid;gap:8px;';
    wrap.appendChild(list);

    options.forEach((option) => {
      list.appendChild(makeJavaCard({
        option,
        meta,
        onPick: async () => {
          try {
            controls?.close?.();
          } catch (err) {
            console.warn('Failed to close Java install chooser:', err);
          }
          const result = await installJavaRuntime(option.version);
          safeResolve(result, false);
        },
      }));
    });

    controls = showMessageBox({
      title: t('java.install.title'),
      customContent: wrap,
      image: 'assets/images/java_icon.png',
      buttons: [
        { label: t('common.cancel'), onClick: () => safeResolve(false) },
      ],
    });
  });
};