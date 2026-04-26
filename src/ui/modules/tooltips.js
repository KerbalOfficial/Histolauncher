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

const addFormattedLine = (parent, line) => {
  const firstParenIndex = line.indexOf('(');
  const colonIndex = line.indexOf(': ');

  if (colonIndex !== -1 && (firstParenIndex === -1 || colonIndex < firstParenIndex)) {
    const label = line.substring(0, colonIndex);
    const value = line.substring(colonIndex + 2);

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

  const lines = text.split('\\n');
  lines.forEach((line, index) => {
    addFormattedLine(tooltip, line);

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
    updateTooltipPosition(currentTooltip, event.clientX + 10, event.clientY);
  };

  const hideHandler = () => {
    hideTooltip();
    element.removeEventListener('mousemove', mouseMoveHandler);
    element.removeEventListener('mouseleave', hideHandler);
  };

  element.addEventListener('mousemove', mouseMoveHandler);
  element.addEventListener('mouseleave', hideHandler);

  updateTooltipPosition(currentTooltip, e.clientX + 10, e.clientY);
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
        updateTooltipPosition(currentTooltip, e.clientX + 10, e.clientY);
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
        updateTooltipPosition(currentTooltip, e.clientX + 10, e.clientY);
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
