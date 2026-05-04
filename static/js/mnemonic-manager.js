/**
 * mnemonic-manager.js — Безопасное управление мнемоническими фразами
 * ✅ Защита от повторной загрузки + ФИКС копирования
 */

// === 🛡️ Защита от повторного объявления ===
if (typeof window.MnemonicManager !== 'undefined') {
  console.debug('ℹ️ MnemonicManager already loaded, skipping');
} else {
  (function() {
    const MnemonicManager = {
      _mnemonic: null,
      _clearTimer: null,
      _autoClearSeconds: 30,

      showInModal(mnemonic, modalId = 'mnemonicModal', displayId = 'modalMnemonic') {
        if (!mnemonic) return;
        this._mnemonic = mnemonic;
        const modal = document.getElementById(modalId);
        const display = document.getElementById(displayId);
        if (display) display.textContent = mnemonic;
        if (modal) {
          modal.classList.remove('hidden');
          modal.setAttribute('aria-hidden', 'false');
        }
        this._startAutoClear(modalId);
        this._preventEscClose(modalId, true);
      },

      hide(modalId = 'mnemonicModal') {
        this._stopAutoClear();
        this._wipe();
        const modal = document.getElementById(modalId);
        if (modal) {
          modal.classList.add('hidden');
          modal.setAttribute('aria-hidden', 'true');
          this._preventEscClose(modalId, false);
        }
        window.NotificationManager?.showToast('🧹 Mnemonic cleared from memory', 'success');
      },

      // ✅ ИСПРАВЛЕНО: надёжное копирование с фолбэком
      async copy(onSuccess, onError) {
        try {
          if (!this._mnemonic) {
            onError?.('Mnemonic not available');
            return false;
          }

          // ✅ Проверяем, доступен ли Utils из common.js
          if (typeof Utils !== 'undefined' && typeof Utils.copyToClipboard === 'function') {
            return await Utils.copyToClipboard(this._mnemonic, onSuccess, onError);
          }

          // ✅ Фолбэк: нативное копирование, если Utils недоступен
          console.log('📋 Using fallback clipboard method');
          const text = this._mnemonic;

          // Метод 1: navigator.clipboard (современные браузеры)
          if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
            onSuccess?.();
            return true;
          }

          // Метод 2: document.execCommand (устаревший, но работает везде)
          const textarea = document.createElement('textarea');
          textarea.value = text;
          textarea.style.position = 'fixed';
          textarea.style.opacity = '0';
          textarea.style.left = '-9999px';
          document.body.appendChild(textarea);
          textarea.select();
          const success = document.execCommand('copy');
          document.body.removeChild(textarea);

          if (success) {
            onSuccess?.();
            return true;
          } else {
            throw new Error('execCommand failed');
          }
        } catch (e) {
          console.error('❌ Copy failed:', e);
          onError?.(e.message || 'Copy failed');
          // Показываем ошибку пользователю, если есть NotificationManager
          window.NotificationManager?.showToast('Copy failed: ' + e.message, 'error');
          return false;
        }
      },

      download(filename = null) {
        if (!this._mnemonic) return false;
        try {
          const blob = new Blob([this._mnemonic], { type: 'text/plain' });
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          link.download = filename || `mnemonic-${Date.now()}.txt`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          setTimeout(() => URL.revokeObjectURL(url), 100);
          return true;
        } catch (e) {
          console.error('Download error:', e);
          window.NotificationManager?.showToast('Download failed', 'error');
          return false;
        }
      },

      _startAutoClear(modalId) {
        this._stopAutoClear();
        let seconds = this._autoClearSeconds;
        const countdown = document.getElementById('clearCountdown');
        this._clearTimer = setInterval(() => {
          seconds--;
          if (countdown) countdown.textContent = seconds;
          if (seconds <= 0) this.hide(modalId);
        }, 1000);
      },

      _stopAutoClear() {
        if (this._clearTimer) { clearInterval(this._clearTimer); this._clearTimer = null; }
      },

      _wipe() {
        if (this._mnemonic) {
          this._mnemonic = typeof this._mnemonic === 'string'
            ? this._mnemonic.split('').map(() => '\0').join('')
            : null;
        }
      },

      _preventEscClose(modalId, prevent) {
        const modal = document.getElementById(modalId);
        if (!modal) return;
        if (prevent) {
          const handler = (e) => { if (e.key === 'Escape') e.preventDefault(); };
          modal._escHandler = handler;
          document.addEventListener('keydown', handler, { passive: false });
        } else if (modal._escHandler) {
          document.removeEventListener('keydown', modal._escHandler);
          delete modal._escHandler;
        }
      }
    };

    // ✅ Экспорт в window
    window.MnemonicManager = MnemonicManager;
    console.log('✅ MnemonicManager loaded');
  })();
}