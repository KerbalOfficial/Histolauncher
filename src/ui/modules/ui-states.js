export const createEmptyState = (message, { isError = false } = {}) => {
  const element = document.createElement('p');
  element.className = isError
    ? 'mods-empty-state mods-empty-state-error'
    : 'mods-empty-state';
  element.textContent = message;
  return element;
};

export const createInlineLoadingState = (
  message,
  { centered = false } = {}
) => {
  const element = document.createElement('div');
  element.className = centered
    ? 'inline-loading-state inline-loading-state-centered'
    : 'inline-loading-state';

  const icon = document.createElement('img');
  icon.className = 'inline-loading-state-icon';
  icon.src = 'assets/images/settings.gif';
  icon.alt = '';
  icon.setAttribute('aria-hidden', 'true');

  const label = document.createElement('span');
  label.className = 'inline-loading-state-label';
  label.textContent = message;

  element.appendChild(icon);
  element.appendChild(label);
  return element;
};