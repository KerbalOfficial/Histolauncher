// ui/modules/tooltips.js

let currentTooltip = null;

const hideTooltip = () => {
  if (currentTooltip) {
    currentTooltip.remove();
    currentTooltip = null;
  }
};

const parseParenthesesInElement = (parent, text) => {
  let lastIndex = 0;
  const regex = /\(([^)]*)\)/g;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parent.appendChild(document.createTextNode(text.substring(lastIndex, match.index)));
    }

    const parensSpan = document.createElement('span');
    parensSpan.className = 'tooltip-parens';
    parensSpan.textContent = match[0];
    parent.appendChild(parensSpan);

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parent.appendChild(document.createTextNode(text.substring(lastIndex)));
  }
};

const normalizeTooltipLines = (text) => String(text || '')
  .replace(/\r\n?/g, '\n')
  .replace(/\\r\\n/g, '\n')
  .replace(/\\n/g, '\n')
  .split('\n')
  .map((line) => line.replace(/\s+$/g, ''));

const addFormattedLine = (parent, line) => {
  if (!String(line || '').trim()) return;
  const firstParenIndex = line.indexOf('(');
  const colonMatch = line.match(/^([^:\n]{1,48}):\s+(.+)$/);
  const colonIndex = colonMatch ? colonMatch[1].length : -1;

  if (colonIndex !== -1 && (firstParenIndex === -1 || colonIndex < firstParenIndex)) {
    const label = colonMatch[1].trim();
    const value = colonMatch[2];

    const labelSpan = document.createElement('span');
    labelSpan.className = 'tooltip-label';
    labelSpan.textContent = label + ': ';
    parent.appendChild(labelSpan);

    const valueSpan = document.createElement('span');
    valueSpan.className = 'tooltip-value';
    parent.appendChild(valueSpan);

    parseParenthesesInElement(valueSpan, value);
  } else {
    parseParenthesesInElement(parent, line);
  }
};

const createTooltip = (text) => {
  const tooltip = document.createElement('div');
  tooltip.className = 'tooltip';

  const lines = normalizeTooltipLines(text);
  lines.forEach((line, index) => {
    if (String(line || '').trim()) {
      addFormattedLine(tooltip, line);
    } else {
      const spacer = document.createElement('span');
      spacer.className = 'tooltip-line-spacer';
      tooltip.appendChild(spacer);
    }

    if (index < lines.length - 1) {
      tooltip.appendChild(document.createElement('br'));
    }
  });

  document.body.appendChild(tooltip);
  return tooltip;
};

const updateTooltipPosition = (tooltip, x, y) => {
  tooltip.style.left = (x + 10) + 'px';
  tooltip.style.top = (y + 10) + 'px';
};

const showTooltip = (element, text, e) => {
  if (!text || !text.trim()) return;

  hideTooltip();

  currentTooltip = createTooltip(text);

  const mouseMoveHandler = (event) => {
    if (currentTooltip) {
      updateTooltipPosition(currentTooltip, event.clientX, event.clientY);
    }
  };

  const hideHandler = () => {
    hideTooltip();
    element.removeEventListener('mousemove', mouseMoveHandler);
    element.removeEventListener('mouseleave', hideHandler);
  };

  element.addEventListener('mousemove', mouseMoveHandler);
  element.addEventListener('mouseleave', hideHandler);

  updateTooltipPosition(currentTooltip, e.clientX, e.clientY);
};

const showTooltipAtElement = (element, text) => {
  if (!text || !text.trim()) return;
  hideTooltip();
  currentTooltip = createTooltip(text);
  const rect = element.getBoundingClientRect();
  updateTooltipPosition(currentTooltip, rect.right, rect.top + rect.height / 2);
};

export const initTooltips = () => {
  const infoBubbles = document.querySelectorAll('.info-bubble');

  infoBubbles.forEach((bubble) => {
    if (bubble.dataset && bubble.dataset.tooltipBound === '1') return;
    if (bubble.dataset) bubble.dataset.tooltipBound = '1';

    if (!bubble.hasAttribute('tabindex')) bubble.setAttribute('tabindex', '0');
    if (!bubble.hasAttribute('aria-label')) bubble.setAttribute('aria-label', 'More information');

    bubble.addEventListener('mouseenter', (e) => {
      const tooltip = bubble.getAttribute('data-tooltip');
      if (tooltip) {
        showTooltip(bubble, tooltip, e);
      }
    });

    bubble.addEventListener('focus', () => {
      const tooltip = bubble.getAttribute('data-tooltip');
      if (tooltip) {
        showTooltipAtElement(bubble, tooltip);
      }
    });

    bubble.addEventListener('mousemove', (e) => {
      if (currentTooltip) {
        updateTooltipPosition(currentTooltip, e.clientX, e.clientY);
      }
    });

    bubble.addEventListener('mouseleave', () => {
      hideTooltip();
    });

    bubble.addEventListener('blur', () => {
      hideTooltip();
    });

    bubble.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        hideTooltip();
      }
    });
  });

  const errorIndicators = document.querySelectorAll('.invalid-indicator:not(.hidden)');
  errorIndicators.forEach((indicator) => {
    if (indicator.dataset && indicator.dataset.tooltipBound === '1') return;
    if (indicator.dataset) indicator.dataset.tooltipBound = '1';

    if (!indicator.hasAttribute('tabindex')) indicator.setAttribute('tabindex', '0');
    if (!indicator.hasAttribute('aria-label')) indicator.setAttribute('aria-label', 'Validation warning');

    indicator.addEventListener('mouseenter', (e) => {
      const tooltip = indicator.title;
      if (tooltip) {
        showTooltip(indicator, tooltip, e);
      }
    });

    indicator.addEventListener('focus', () => {
      const tooltip = indicator.title;
      if (tooltip) {
        showTooltipAtElement(indicator, tooltip);
      }
    });

    indicator.addEventListener('mousemove', (e) => {
      if (currentTooltip) {
        updateTooltipPosition(currentTooltip, e.clientX, e.clientY);
      }
    });

    indicator.addEventListener('mouseleave', () => {
      hideTooltip();
    });

    indicator.addEventListener('blur', () => {
      hideTooltip();
    });

    indicator.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        hideTooltip();
      }
    });
  });
};
