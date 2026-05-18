// ui/modules/pagination.js

const buildPageItems = (current, total) => {
  const pages = [];
  pages.push(1);
  if (current > 3) pages.push('...');
  for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
    pages.push(i);
  }
  if (current < total - 2) pages.push('...');
  if (total > 1) pages.push(total);
  return pages;
};

let activeJumpPopover = null;

const closePageJumpPopover = () => {
  if (!activeJumpPopover) return;
  if (typeof activeJumpPopover._cleanup === 'function') activeJumpPopover._cleanup();
  activeJumpPopover.remove();
  activeJumpPopover = null;
};

const showPageJumpPopover = (anchor, current, total, onPageChange) => {
  closePageJumpPopover();

  const popover = document.createElement('div');
  popover.className = 'mods-page-jump-popover';

  const input = document.createElement('input');
  input.type = 'number';
  input.min = '1';
  input.max = String(total);
  input.value = String(current);
  input.setAttribute('aria-label', 'Jump to page');
  popover.appendChild(input);

  const goBtn = document.createElement('button');
  goBtn.type = 'button';
  goBtn.className = 'mods-page-btn primary';
  goBtn.textContent = 'Go';
  popover.appendChild(goBtn);

  const submit = () => {
    const page = Number.parseInt(String(input.value || '').trim(), 10);
    if (Number.isFinite(page) && page >= 1 && page <= total && page !== current) {
      closePageJumpPopover();
      onPageChange(page);
      return;
    }
    closePageJumpPopover();
  };

  goBtn.addEventListener('click', submit);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      submit();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      closePageJumpPopover();
    }
  });

  popover.addEventListener('mousedown', (event) => event.stopPropagation());
  const closeOnOutsideClick = (event) => {
    if (!(event.target instanceof Node) || popover.contains(event.target) || anchor.contains(event.target)) return;
    closePageJumpPopover();
    document.removeEventListener('mousedown', closeOnOutsideClick, true);
  };
  document.addEventListener('mousedown', closeOnOutsideClick, true);
  popover._cleanup = () => document.removeEventListener('mousedown', closeOnOutsideClick, true);

  document.body.appendChild(popover);
  activeJumpPopover = popover;

  const rect = anchor.getBoundingClientRect();
  const popoverRect = popover.getBoundingClientRect();
  const padding = 8;
  const left = Math.max(padding, Math.min(rect.left, window.innerWidth - popoverRect.width - padding));
  const top = Math.max(padding, Math.min(rect.bottom + 6, window.innerHeight - popoverRect.height - padding));
  popover.style.left = `${Math.round(left)}px`;
  popover.style.top = `${Math.round(top)}px`;

  input.focus();
  input.select();
};

export const renderCommonPagination = (container, total, current, onPageChange) => {
  if (!container) return;
  container.innerHTML = '';

  if (total <= 1) return;

  const createPageBtn = (label, page, isActive, isDisabled) => {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.className = 'mods-page-btn';
    if (isActive) btn.classList.add('active');
    if (isDisabled) btn.disabled = true;
    btn.addEventListener('click', () => {
      if (page !== current && !isDisabled) {
        onPageChange(page);
      }
    });
    return btn;
  };

  container.appendChild(createPageBtn('<', current - 1, false, current <= 1));

  const pages = buildPageItems(current, total);
  pages.forEach((p) => {
    if (p === '...') {
      const ellipsisBtn = document.createElement('button');
      ellipsisBtn.type = 'button';
      ellipsisBtn.className = 'mods-page-ellipsis mods-page-ellipsis-btn';
      ellipsisBtn.textContent = '...';
      ellipsisBtn.title = 'Jump to page';
      ellipsisBtn.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        showPageJumpPopover(ellipsisBtn, current, total, onPageChange);
      });
      container.appendChild(ellipsisBtn);
    } else {
      container.appendChild(createPageBtn(String(p), p, p === current, false));
    }
  });

  container.appendChild(createPageBtn('>', current + 1, false, current >= total));
};
