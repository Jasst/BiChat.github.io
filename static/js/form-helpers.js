/**
 * form-helpers.js — Дополнительные хелперы для форм
 * Для сложных форм с валидацией
 */

const AdvancedForms = {
  // Поле с авто-форматированием адреса (пробелы каждые 8 символов)
  attachAddressFormatter(input) {
    const format = (val) => val.replace(/[^a-fA-F0-9]/g, '').replace(/(.{8})/g, '$1 ').trim();

    input.addEventListener('input', (e) => {
      const cursor = e.target.selectionStart;
      const raw = e.target.value.replace(/\s/g, '');
      e.target.value = format(raw);
      // Восстанавливаем позицию курсора
      const spacesBefore = format(raw).slice(0, cursor).split(' ').length - 1;
      e.target.setSelectionRange(cursor + spacesBefore, cursor + spacesBefore);
    });

    input.addEventListener('blur', () => {
      input.value = input.value.replace(/\s/g, ''); // Убираем пробелы при отправке
    });
  },

  // Текстовое поле с авто-увеличением высоты
  attachAutoResize(textarea, { minHeight = 40, maxHeight = 200 } = {}) {
    const resize = () => {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, maxHeight) + 'px';
    };
    textarea.addEventListener('input', resize);
    textarea.style.minHeight = minHeight + 'px';
    resize(); // Первоначальный вызов
    return () => textarea.removeEventListener('input', resize);
  },

  // Группа чекбоксов с лимитом выбора
  attachCheckboxLimit(container, selector, max, onLimit) {
    DOM.queryAll(selector, container).forEach(cb => {
      cb.addEventListener('change', () => {
        const checked = DOM.queryAll(`${selector}:checked`, container);
        if (checked.length > max) {
          cb.checked = false;
          onLimit?.(max);
        }
      });
    });
  }
};

window.AdvancedForms = AdvancedForms;