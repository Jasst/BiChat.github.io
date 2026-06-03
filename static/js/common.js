/**
 * common.js — Shared utilities for Dark Messenger
 * QR Scanner, Utils, DOM helpers, Security, Forms, Modals
 * ✅ Защита от повторной загрузки + ФИКСЫ для авто-добавления после сканирования
 * ✅ Добавлены глобальные модальные окна confirm/prompt
 * ✅ ИСПРАВЛЕН QR-сканер: увеличены таймауты, добавлен сброс по времени
 */

// === 🛡️ Защита от повторного объявления модулей ===
;(function(global) {
  if (global.DarkMsgCommonLoaded) {
    console.debug('ℹ️ common.js already loaded, skipping');
    return;
  }
  global.DarkMsgCommonLoaded = true;
  window.modalOpen = false;

// =============================================================================
// === 🛡️ Security Module ===
// =============================================================================
const Security = {
  wipeSensitive(data) {
    if (!data) return null;
    if (typeof data === 'string') {
      data = data.split('').map(() => '\0').join('');
    }
    return null;
  },

  generateSafeId(length = 16) {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let result = '';
    if (window.crypto?.getRandomValues) {
      const bytes = new Uint8Array(length);
      crypto.getRandomValues(bytes);
      for (let i = 0; i < length; i++) {
        result += chars[bytes[i] % chars.length];
      }
    } else {
      for (let i = 0; i < length; i++) {
        result += chars[Math.floor(Math.random() * chars.length)];
      }
    }
    return result;
  },

  isValidAddress(str) {
    return typeof str === 'string' && str.length === 64 && /^[a-fA-F0-9]{64}$/.test(str);
  },

  maskAddress(addr, visibleChars = 8) {
    if (!addr || addr.length <= visibleChars * 2) return addr;
    return addr.slice(0, visibleChars) + '…' + addr.slice(-visibleChars);
  }
};

// =============================================================================
// === 📋 Utilities ===
// =============================================================================
const Utils = {
  escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },

  escapeAttr(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#x27;');
  },

  async copyToClipboard(text, onSuccess, onError) {
    if (!text) { onError?.('Nothing to copy'); return false; }
    try {
      await navigator.clipboard.writeText(text);
      onSuccess?.();
      return true;
    } catch (e) {
      try {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        onSuccess?.();
        return true;
      } catch (fallbackErr) {
        onError?.(fallbackErr.message || 'Copy failed');
        return false;
      }
    }
  },

  formatTimestamp(ts) {
    if (!ts) return '';
    const date = new Date(ts * 1000);
    const now = new Date();
    const diff = now - date;
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return date.toLocaleDateString();
  },

  parseQRData(data) {
    if (!data) return null;
    if (Security.isValidAddress(data)) return data.toLowerCase();
    if (data.toLowerCase().startsWith('darkmsg:')) {
      const match = data.match(/darkmsg:([a-fA-F0-9]{64})/i);
      if (match?.[1]) return match[1].toLowerCase();
    }
    if (data.toLowerCase().startsWith('bitcoin:')) {
      const match = data.match(/bitcoin:([a-fA-F0-9]{64})/i);
      if (match?.[1]) return match[1].toLowerCase();
    }
    return null;
  },

  debounce(func, wait = 300) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => { clearTimeout(timeout); func(...args); };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }
};

// =============================================================================
// === 🎨 DOM Helpers ===
// =============================================================================
const DOM = {
  getById(id) { return document.getElementById(id); },
  query(selector, root = document) { return root.querySelector(selector); },
  queryAll(selector, root = document) { return Array.from(root.querySelectorAll(selector)); },

  on(selector, event, handler, options) {
    const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (el) el.addEventListener(event, handler, options);
    return () => el?.removeEventListener(event, handler, options);
  },

  delegate(parent, selector, event, handler) {
    const el = typeof parent === 'string' ? document.querySelector(parent) : parent;
    if (!el) return () => {};
    const listener = (e) => {
      const target = e.target.closest(selector);
      if (target && el.contains(target)) handler.call(target, e, target);
    };
    el.addEventListener(event, listener);
    return () => el.removeEventListener(event, listener);
  },

  toggleClass(el, className, force) {
    if (!el?.classList) return;
    el.classList.toggle(className, typeof force === 'boolean' ? force : undefined);
  },

  show(el) { el?.classList?.remove('hidden'); },
  hide(el) { el?.classList?.add('hidden'); },

  createElement(tag, { className, id, attributes = {}, text, html, children = [] } = {}) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (id) el.id = id;
    Object.entries(attributes).forEach(([k, v]) => el.setAttribute(k, v));
    if (text !== undefined) el.textContent = text;
    if (html) el.innerHTML = html;
    children.forEach(child => el.appendChild(child));
    return el;
  }
};

// =============================================================================
// === 🔲 Modal Manager ===
// =============================================================================
const ModalManager = {
  modals: new Map(),

  open(id, options = {}) {
    window.modalOpen = true;
    const modal = DOM.getById(id);
    if (!modal) return false;
    if (options.closeOthers) {
      this.modals.forEach((_, key) => { if (key !== id) this.close(key); });
    }
    DOM.show(modal);
    modal.setAttribute('aria-hidden', 'false');
    setTimeout(() => {
      const focusable = modal.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      focusable?.focus();
    }, 100);
    const onEsc = (e) => {
      if (e.key === 'Escape' && !options.preventEscClose) {
        e.preventDefault();
        this.close(id);
      }
    };
    document.addEventListener('keydown', onEsc);
    this.modals.set(id, { element: modal, onEsc });
    if (options.closeOnOverlay) {
      const overlayClick = (e) => { if (e.target === modal) this.close(id); };
      modal.addEventListener('click', overlayClick);
      this.modals.get(id).overlayClick = overlayClick;
    }
    options.onOpen?.(modal);
    return true;
  },

  close(id) {
    window.modalOpen = false;
    const modal = DOM.getById(id);
    if (!modal) return false;
    const data = this.modals.get(id);
    if (data?.onEsc) document.removeEventListener('keydown', data.onEsc);
    if (data?.overlayClick) modal.removeEventListener('click', data.overlayClick);
    DOM.hide(modal);
    modal.setAttribute('aria-hidden', 'true');
    this.modals.delete(id);
    data?.onClose?.(modal);
    return true;
  },

  initTriggers() {
    document.addEventListener('click', (e) => {
      const trigger = e.target.closest('[data-modal-trigger]');
      if (!trigger) return;
      e.preventDefault();
      const modalId = trigger.dataset.modalTrigger;
      const options = {
        closeOthers: trigger.dataset.closeOthers !== 'false',
        closeOnOverlay: trigger.dataset.closeOnOverlay !== 'false',
        preventEscClose: trigger.dataset.preventEscClose === 'true'
      };
      this.open(modalId, options);
    });
  }
};

// =============================================================================
// === 📝 Form Helpers ===
// =============================================================================
const FormHelpers = {
  validateAddress(value) {
    if (!value) return { valid: false, error: 'Address is required' };
    if (!Security.isValidAddress(value)) {
      return { valid: false, error: 'Must be 64 hex characters' };
    }
    return { valid: true };
  },

  validateName(value, { minLength = 1, maxLength = 100, allowSpecial = false } = {}) {
    if (!value?.trim()) return { valid: false, error: 'Name is required' };
    if (value.length < minLength) return { valid: false, error: `Min ${minLength} characters` };
    if (value.length > maxLength) return { valid: false, error: `Max ${maxLength} characters` };
    if (!allowSpecial && /[^a-zA-Z0-9\s\-_]/.test(value)) {
      return { valid: false, error: 'Only letters, numbers, spaces, - _ allowed' };
    }
    return { valid: true };
  },

  attachValidation(input, validator, errorEl) {
    const showError = (msg) => {
      if (errorEl) { errorEl.textContent = msg; DOM.show(errorEl); }
      input.setAttribute('aria-invalid', 'true');
    };
    const clearError = () => {
      if (errorEl) { errorEl.textContent = ''; DOM.hide(errorEl); }
      input.removeAttribute('aria-invalid');
    };
    input.addEventListener('blur', () => {
      const result = validator(input.value);
      result.valid ? clearError() : showError(result.error);
    });
    input.addEventListener('input', () => {
      if (input.getAttribute('aria-invalid') === 'true') {
        const result = validator(input.value);
        if (result.valid) clearError();
      }
    });
    return () => { clearError(); };
  },

  async handleSubmit(formEl, submitBtn, handler) {
    if (!formEl || !handler) return;
    formEl.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (submitBtn) {
        submitBtn.disabled = true;
        const originalText = submitBtn.textContent;
        submitBtn.dataset.originalText = originalText;
        submitBtn.textContent = submitBtn.dataset.loadingText || 'Processing…';
      }
      try {
        await handler(new FormData(formEl));
      } catch (err) {
        console.error('Form submit error:', err);
        window.NotificationManager?.showToast(err.message || 'Request failed', 'error');
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = submitBtn.dataset.originalText || 'Submit';
        }
      }
    });
  }
};

// =============================================================================
// === 📷 QR Scanner Module (✅ FULLY FIXED - improved waiting) ===
// =============================================================================
const QRScanner = {
  stream: null,
  animationFrame: null,
  active: false,
  _canvas: null,
  _ctx: null,
  _videoReadyTimeout: null,
  config: {
    videoWidth: 1280,
    videoHeight: 720,
    scanSize: 400,
    inversionAttempts: "attemptBoth",
    scanInterval: 100,
    videoWaitTimeout: 5000,    // 5 секунд максимум на готовность видео
    videoWaitInterval: 100     // проверка каждые 100 мс
  },

  open(options) {
    if (this.active) return;
    const { videoEl, resultEl, containerEl, onScan, onClose } = options;
    if (!videoEl || !containerEl) {
      console.error('QRScanner: missing video or container element');
      return;
    }
    this.active = true;
    DOM.show(containerEl);
    containerEl.classList.add('scanning');
    if (resultEl) { DOM.hide(resultEl); resultEl.textContent = ''; resultEl.style.color = ''; }

    if (!navigator.mediaDevices?.getUserMedia) {
      this._showError('Camera not supported in this browser', resultEl, onClose);
      return;
    }

    navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: this.config.videoWidth, min: 640 },
        height: { ideal: this.config.videoHeight, min: 480 }
      },
      audio: false
    })
    .then(stream => {
      if (!this.active) { this._stopStream(stream); return; }
      this.stream = stream;
      videoEl.srcObject = stream;
      return videoEl.play().catch(err => { console.error('Video play failed:', err); throw err; });
    })
    .then(() => {
      // Ждём, пока видео получит размеры, с таймаутом
      let attempts = 0;
      const maxAttempts = this.config.videoWaitTimeout / this.config.videoWaitInterval;
      const checkVideo = () => {
        if (!this.active) return;
        if (videoEl.videoWidth > 0 && videoEl.videoHeight > 0) {
          console.log('📹 Video ready:', videoEl.videoWidth, 'x', videoEl.videoHeight);
          this._startScanning({ videoEl, resultEl, onScan, containerEl });
        } else {
          attempts++;
          if (attempts >= maxAttempts) {
            console.warn('QRScanner: video not ready after timeout');
            this._showError('Camera not responding', resultEl, onClose);
            this.close({ containerEl, videoEl });
            return;
          }
          setTimeout(checkVideo, this.config.videoWaitInterval);
        }
      };
      checkVideo();
    })
    .catch(err => {
      console.error('QRScanner error:', err.name, err.message);
      let userMessage = 'Camera access denied';
      if (err.name === 'NotFoundError') userMessage = 'No camera found';
      if (err.name === 'NotReadableError') userMessage = 'Camera is busy';
      if (err.name === 'OverconstrainedError') userMessage = 'Camera settings not supported';
      this._showError(userMessage, resultEl, onClose);
    });
  },

  close(options = {}) {
    const { containerEl, videoEl, resultEl, onClose } = options;
    this.active = false;
    if (this.animationFrame) { cancelAnimationFrame(this.animationFrame); this.animationFrame = null; }
    if (this._videoReadyTimeout) { clearTimeout(this._videoReadyTimeout); this._videoReadyTimeout = null; }
    if (this.stream) { this._stopStream(this.stream); this.stream = null; }
    this._canvas = null;
    this._ctx = null;
    if (containerEl) { DOM.hide(containerEl); containerEl.classList.remove('scanning'); }
    if (videoEl) { videoEl.pause(); videoEl.srcObject = null; }
    if (resultEl) DOM.hide(resultEl);
    onClose?.();
  },

  _stopStream(stream) {
    if (stream?.getTracks) {
      stream.getTracks().forEach(track => { track.stop(); console.log('🔴 Camera track stopped:', track.label); });
    }
  },

  _showError(message, resultEl, onClose) {
    console.warn('QRScanner error shown to user:', message);
    window.NotificationManager?.showToast(message, 'error');
    if (resultEl) {
      resultEl.textContent = '⚠️ ' + message;
      resultEl.style.color = 'var(--status-error)';
      DOM.show(resultEl);
    }
    setTimeout(() => { if (!this.active) this.close({ onClose }); }, 3000);
  },

  _startScanning({ videoEl, resultEl, onScan, containerEl }) {
    if (!this.active || !videoEl) return;
    if (!this._canvas) {
        this._canvas = document.createElement('canvas');
        this._canvas.width = this.config.scanSize;
        this._canvas.height = this.config.scanSize;
        this._ctx = this._canvas.getContext('2d', { willReadFrequently: true });
    }
    const canvas = this._canvas;
    const ctx = this._ctx;
    const { scanSize, inversionAttempts, scanInterval } = this.config;
    let lastScanTime = 0;

    const scanFrame = () => {
      if (!this.active) return;
      const now = performance.now();
      if (now - lastScanTime < scanInterval) {
        this.animationFrame = requestAnimationFrame(scanFrame);
        return;
      }
      lastScanTime = now;

      if (videoEl.readyState !== videoEl.HAVE_ENOUGH_DATA || !videoEl.videoWidth || !videoEl.videoHeight) {
        this.animationFrame = requestAnimationFrame(scanFrame);
        return;
      }

      try {
        const videoW = videoEl.videoWidth;
        const videoH = videoEl.videoHeight;
        const size = Math.min(videoW, videoH) * 0.8;
        const sx = (videoW - size) / 2;
        const sy = (videoH - size) / 2;

        canvas.width = scanSize;
        canvas.height = scanSize;
        ctx.drawImage(videoEl, sx, sy, size, size, 0, 0, scanSize, scanSize);

        const imageData = ctx.getImageData(0, 0, scanSize, scanSize);
        const code = jsQR(imageData.data, scanSize, scanSize, { inversionAttempts });

        if (code?.data) {
          console.log('✅ QR found:', code.data.substring(0, 30) + '...');
          const address = Utils.parseQRData(code.data);
          if (address) {
            this.close({ containerEl, videoEl, resultEl });
            if (resultEl) {
              resultEl.textContent = '✓ Address scanned';
              resultEl.style.color = 'var(--status-success)';
              DOM.show(resultEl);
            }
            onScan?.(address);
            window.NotificationManager?.showToast('✓ Address scanned', 'success');
            return;
          } else {
            console.warn('⚠️ QR data not recognized as address:', code.data);
            if (resultEl) {
              resultEl.textContent = '⚠️ Not a valid address format';
              resultEl.style.color = 'var(--status-warning)';
              DOM.show(resultEl);
            }
          }
        }
      } catch (e) { console.debug('Scan frame error (non-critical):', e.message); }

      if (this.active) { this.animationFrame = requestAnimationFrame(scanFrame); }
    };
    this.animationFrame = requestAnimationFrame(scanFrame);
    console.log('🔍 QR scanning started');
  }
};

// =============================================================================
// === 🖥️ Global Modal Dialogs (Confirm / Prompt) ===
// =============================================================================

window.showConfirmModal = function(title, message) {
    return new Promise((resolve) => {
        const modalId = 'global-confirm-modal-' + Date.now();
        const modalHtml = `
            <div id="${modalId}" class="modal-overlay hidden" role="dialog" aria-modal="true">
                <div class="modal" style="max-width: 400px;">
                    <header class="modal-header">
                        <h3>${Utils.escapeHtml(title)}</h3>
                        <button class="modal-close" data-close>&times;</button>
                    </header>
                    <div class="modal-body">
                        <p>${Utils.escapeHtml(message)}</p>
                    </div>
                    <footer class="modal-footer">
                        <button class="btn btn-ghost" data-action="cancel">Cancel</button>
                        <button class="btn btn-primary" data-action="confirm">Confirm</button>
                    </footer>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const modalEl = document.getElementById(modalId);

        const close = (result) => {
            ModalManager.close(modalId);
            modalEl.remove();
            resolve(result);
        };

        ModalManager.open(modalId, { closeOnOverlay: false, preventEscClose: false });

        modalEl.querySelector('[data-close]')?.addEventListener('click', () => close(false));
        modalEl.querySelector('[data-action="cancel"]')?.addEventListener('click', () => close(false));
        modalEl.querySelector('[data-action="confirm"]')?.addEventListener('click', () => close(true));
    });
};

window.showPromptModal = function(title, placeholder, defaultValue = '') {
    return new Promise((resolve) => {
        const modalId = 'global-prompt-modal-' + Date.now();
        const modalHtml = `
            <div id="${modalId}" class="modal-overlay hidden" role="dialog" aria-modal="true">
                <div class="modal" style="max-width: 400px;">
                    <header class="modal-header">
                        <h3>${Utils.escapeHtml(title)}</h3>
                        <button class="modal-close" data-close>&times;</button>
                    </header>
                    <div class="modal-body">
                        <input type="text" id="prompt-input-${modalId}" class="input"
                               placeholder="${Utils.escapeHtml(placeholder)}"
                               value="${Utils.escapeHtml(defaultValue)}"
                               style="width: 100%;">
                    </div>
                    <footer class="modal-footer">
                        <button class="btn btn-ghost" data-action="cancel">Cancel</button>
                        <button class="btn btn-primary" data-action="ok">OK</button>
                    </footer>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const modalEl = document.getElementById(modalId);
        const input = modalEl.querySelector(`#prompt-input-${modalId}`);

        const close = (result) => {
            ModalManager.close(modalId);
            modalEl.remove();
            resolve(result);
        };

        ModalManager.open(modalId, { closeOnOverlay: false, preventEscClose: false });
        input?.focus();

        const handleOk = () => close(input?.value?.trim() || null);
        modalEl.querySelector('[data-close]')?.addEventListener('click', () => close(null));
        modalEl.querySelector('[data-action="cancel"]')?.addEventListener('click', () => close(null));
        modalEl.querySelector('[data-action="ok"]')?.addEventListener('click', handleOk);
        input?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleOk();
        });
    });
};

// =============================================================================
// === 📱 Mobile Sidebar Helpers ===
// =============================================================================
if (typeof window.toggleSidebar !== 'function') {
  window.toggleSidebar = function() {
    const sidebar = DOM.getById('sidebar');
    const overlay = DOM.getById('sidebarOverlay');
    DOM.toggleClass(sidebar, 'open');
    const isOpen = sidebar?.classList.contains('open');
    DOM.toggleClass(overlay, 'active', isOpen);
    document.body.style.overflow = isOpen ? 'hidden' : '';
  };
}
if (typeof window.closeSidebar !== 'function') {
  window.closeSidebar = function() {
    const sidebar = DOM.getById('sidebar');
    const overlay = DOM.getById('sidebarOverlay');
    sidebar?.classList.remove('open');
    overlay?.classList.remove('active');
    document.body.style.overflow = '';
  };
}

// =============================================================================
// === 🌐 Global Exports ===
// =============================================================================
window.Utils = Utils;
window.DOM = DOM;
window.Security = Security;
window.ModalManager = ModalManager;
window.FormHelpers = FormHelpers;
window.QRScanner = QRScanner;

// =============================================================================
// === 📷 QR Scanner Global Wrappers ===
// =============================================================================

window.openQRScannerInModal = () => QRScanner.open({
  videoEl: DOM.getById('qrVideoModal'),
  resultEl: DOM.getById('scanResultModal'),
  containerEl: DOM.getById('qrScannerContainerModal'),
  onScan: (addr) => {
    console.log('🎯 onScan called with:', addr);
    const el = DOM.getById('newChatAddress');
    if (el) {
      el.value = addr;
      console.log('✅ Address inserted into #newChatAddress');
      const resultEl = DOM.getById('scanResultModal');
      if (resultEl) {
        resultEl.textContent = '✓ Address scanned! Click "Start Chat" to begin';
        resultEl.style.color = 'var(--status-success)';
        DOM.show(resultEl);
      }
    }
  }
});

window.forceCloseQRScannerInModal = () => QRScanner.close({
  containerEl: DOM.getById('qrScannerContainerModal'),
  videoEl: DOM.getById('qrVideoModal')
});

window.openQRScanner = () => QRScanner.open({
  videoEl: DOM.getById('qrVideo'),
  resultEl: DOM.getById('scanResult'),
  containerEl: DOM.getById('qrScannerContainer'),
  onScan: async (addr) => {
    console.log('🎯 onScan called with:', addr);
    const addressEl = DOM.getById('contactAddress');
    const nameEl = DOM.getById('contactName');

    if (addressEl) addressEl.value = addr;

    if (nameEl && !nameEl.value.trim()) {
      nameEl.value = 'Contact_' + addr.slice(0, 8);
    }

    const resultEl = DOM.getById('scanResult');
    if (resultEl) {
      resultEl.textContent = '✓ Scanned! Adding contact...';
      resultEl.style.color = 'var(--status-success)';
      DOM.show(resultEl);
    }

    setTimeout(async () => {
      if (addressEl?.value && nameEl?.value && typeof window.addContact === 'function') {
        try {
          await window.addContact();
        } catch (e) {
          console.error('Auto-add contact failed:', e);
          window.NotificationManager?.showToast('Scan complete. Please click "Add" manually.', 'warning');
        }
      }
    }, 400);

    nameEl?.focus();
  }
});

window.forceCloseQRScanner = () => QRScanner.close({
  containerEl: DOM.getById('qrScannerContainer'),
  videoEl: DOM.getById('qrVideo')
});

// =============================================================================
// === 🧹 Cleanup ===
// =============================================================================
window.addEventListener('beforeunload', () => QRScanner.close());
document.addEventListener('visibilitychange', () => { if (document.hidden) QRScanner.close(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { QRScanner.close(); closeSidebar?.(); }
});
document.addEventListener('DOMContentLoaded', () => { ModalManager.initTriggers(); });

})(typeof window !== 'undefined' ? window : this);