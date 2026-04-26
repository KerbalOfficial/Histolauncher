// ui/modules/pagination.js

import { showMessageBox } from './modal.js';

const promptForPageJump = (current, total) => {
  if (total <= 1) return null;

  return new Promise((resolve) => {
    showMessageBox({
      title: `Jump to Page`,
      message: `Enter a page number (1-${total}):`,
      inputs: [
        {
          type: 'number',
          name: 'page',
          placeholder: `Enter page (1-${total})`,
          value: String(current)
        }
      ],
      buttons: [
        {
          label: 'Go',
          classList: ['primary'],
          onClick: (vals) => {
            const input = vals.page || '';
            const page = Number.parseInt(String(input).trim(), 10);
            if (Number.isFinite(page) && page >= 1 && page <= total) {
              resolve(page);
            } else {
              resolve(null);
            }
          }
        },
        {
          label: 'Cancel',
          onClick: () => resolve(null)
        }
      ]
    });
  });
};

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
      ellipsisBtn.addEventListener('click', async () => {
        const targetPage = await promptForPageJump(current, total);
        if (targetPage && targetPage !== current) {
          onPageChange(targetPage);
        }
      });
      container.appendChild(ellipsisBtn);
    } else {
      container.appendChild(createPageBtn(String(p), p, p === current, false));
    }
  });

  container.appendChild(createPageBtn('>', current + 1, false, current >= total));
};
