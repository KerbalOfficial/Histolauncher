import { api } from './api.js';
import {
  hideLoadingOverlay,
  showLoadingOverlay,
  showMessageBox,
} from './modal.js';
import { escapeInfoHtml, formatBytes } from './string-utils.js';

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
      title: 'Java Download Error',
      message: 'Invalid Java version.',
      buttons: [{ label: 'OK', classList: ['primary'] }],
    });
    return { ok: false, error: 'Invalid Java version' };
  }

  showLoadingOverlay(`Downloading Java ${javaVersion}...`, {
    image: 'assets/images/java_icon.png',
    boxClassList: ['activity-box'],
  });

  try {
    const res = await api('/api/java-download', 'POST', { version: javaVersion });
    hideLoadingOverlay();

    if (!res || !res.ok) {
      showMessageBox({
        title: 'Java Download Error',
        message: escapeInfoHtml(res?.error || 'Failed to download Java.'),
        buttons: [{ label: 'OK', classList: ['primary'] }],
      });
      return res || { ok: false };
    }

    const actualVersion = parseJavaVersion(res.feature_version) || javaVersion;
    const fileName = escapeInfoHtml(res.file_name || 'Java installer');
    const path = escapeInfoHtml(res.path || '');
    const sizeText = formatBytes(Number(res.size || 0));
    const installed = res.installed === true;
    const installDir = escapeInfoHtml(res.install_dir || '');
    const runtimePath = escapeInfoHtml(res.runtime_path || '');
    const opened = res.opened !== false;
    const openError = escapeInfoHtml(res.open_error || '');
    const title = installed ? 'Java Runtime Installed' : (opened ? 'Java Installer Opened' : 'Java Downloaded');
    let message = installed
      ? `Java ${actualVersion} runtime installed.<br><br><b>${fileName}</b>`
      : `Java ${actualVersion} ${opened ? 'installer opened' : 'download finished'}.<br><br><b>${fileName}</b>`;
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
          label: 'OK',
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
      title: 'Java Download Error',
      message: escapeInfoHtml(err?.message || String(err || 'Failed to download Java.')),
      buttons: [{ label: 'OK', classList: ['primary'] }],
    });
    return { ok: false, error: err?.message || String(err || '') };
  }
};

const makeJavaCard = ({ option, meta, onPick }) => {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.style.cssText =
    `width:100%;background:#222;border:1px solid #111;border-left:3px solid ${option.recommended ? RECOMMENDED_ACCENT : JAVA_ACCENT};` +
    'padding:8px 12px;display:flex;justify-content:space-between;align-items:center;text-align:left;color:#e5e7eb;';

  const left = document.createElement('div');
  left.style.cssText = 'min-width:0;';

  const title = document.createElement('div');
  title.style.cssText = `color:${option.recommended ? RECOMMENDED_ACCENT : JAVA_ACCENT};font-weight:700;line-height:1.2;`;
  title.textContent = option.label || `Java ${option.version || ''}`.trim();

  const subtitle = document.createElement('div');
  subtitle.style.cssText = 'color:#aaa;font-size:12px;line-height:1.2;margin-top:2px;';
  subtitle.textContent = option.description || '';
  if (!subtitle.textContent) subtitle.style.display = 'none';

  const details = document.createElement('div');
  details.style.cssText = 'color:#666;font-size:11px;line-height:1.2;margin-top:2px;';
  details.textContent = [meta, option.recommended ? 'Recommended' : '']
    .filter(Boolean)
    .join(' | ');
  if (!details.textContent) details.style.display = 'none';

  left.appendChild(title);
  left.appendChild(subtitle);
  left.appendChild(details);
  btn.appendChild(left);

  btn.addEventListener('mouseenter', () => {
    btn.style.background = '#2a2a2a';
  });
  btn.addEventListener('mouseleave', () => {
    btn.style.background = '#222';
  });
  btn.addEventListener('click', () => {
    if (typeof onPick === 'function') onPick();
  });

  return btn;
};

export const showJavaInstallChooser = async () => {
  showLoadingOverlay('Loading Java runtimes...', {
    image: 'assets/images/java_icon.png',
    boxClassList: ['activity-box'],
  });

  let data = null;
  try {
    data = await api('/api/java-install-options', 'GET');
  } catch (err) {
    hideLoadingOverlay();
    showMessageBox({
      title: 'Java Install Error',
      message: escapeInfoHtml(err?.message || String(err || 'Failed to load Java runtimes.')),
      buttons: [{ label: 'OK', classList: ['primary'] }],
    });
    return false;
  }
  hideLoadingOverlay();

  if (!data || !data.ok) {
    showMessageBox({
      title: 'Java Install Error',
      message: escapeInfoHtml(data?.error || 'No Java runtime downloads are available for this system.'),
      buttons: [{ label: 'OK', classList: ['primary'] }],
    });
    return false;
  }

  const options = Array.isArray(data.options) ? data.options : [];
  if (!options.length) {
    showMessageBox({
      title: 'Java Install Error',
      message: 'No Java runtime downloads are available for this system.',
      buttons: [{ label: 'OK', classList: ['primary'] }],
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
      title: 'Install Java Runtime',
      customContent: wrap,
      image: 'assets/images/java_icon.png',
      buttons: [
        { label: 'Cancel', onClick: () => safeResolve(false) },
      ],
    });
  });
};