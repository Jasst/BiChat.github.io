/**
 * notification-manager.js — Полная система уведомлений
 * 🔔 Звук (без файлов), баннеры, нативные уведомления
 */
(function() {
  'use strict';

  const NotificationManager = {
    // State
    audioCtx: null,
    userInteracted: false,          // ← флаг взаимодействия
    originalTitle: document.title,
    blinkInterval: null,
    initialized: false,
    lastNotificationTime: new Map(),
    activeChatId: null,
    processedMessageIds: new Set(),

    // Config
    config: {
      soundEnabled: true,
      notificationEnabled: true,
      blinkEnabled: true,
      throttleMs: 2000,
      maxTracked: 50,
      notificationTimeout: 8000,
      toastDuration: 5000
    },

    /** Инициализация (не требует взаимодействия) */
    async init() {
      if (this.initialized) return;
      this.initialized = true;

      // Отслеживаем первое взаимодействие пользователя – после него можно играть звук
      const markInteraction = () => {
        this.userInteracted = true;
        document.removeEventListener('click', markInteraction);
        document.removeEventListener('touchstart', markInteraction);
      };
      document.addEventListener('click', markInteraction, { once: true, passive: true });
      document.addEventListener('touchstart', markInteraction, { once: true, passive: true });

      // Запрос нативных уведомлений (можно без звука)
      if ('Notification' in window && Notification.permission === 'default') {
        try {
          await Notification.requestPermission();
        } catch (e) { /* ignore */ }
      }
    },

    /** Гарантирует наличие AudioContext и его активное состояние */
    _ensureAudioContext() {
      if (!this.audioCtx) {
        try {
          this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        } catch (e) {
          console.debug('ℹ️ Web Audio not available');
          return false;
        }
      }
      if (this.audioCtx.state === 'suspended') {
        this.audioCtx.resume().catch(() => {});
      }
      return this.audioCtx.state !== 'closed';
    },

    setActiveChat(chatId) {
      this.activeChatId = chatId ? this._normalizeChatId(chatId) : null;
      this.stopBlink();
    },

    isActiveChat(chatId) {
      if (document.visibilityState !== 'visible') return false;
      const current = this.activeChatId;
      const target = this._normalizeChatId(chatId);
      return !!(current && target && current === target);
    },

    /** Проигрывание короткого звукового сигнала (без файлов) */
    playSound(type = 'received') {
      // Без взаимодействия пользователя звук блокируется браузером
      if (!this.userInteracted) return;
      if (!this.config.soundEnabled) return;
      if (!this._ensureAudioContext()) return;

      try {
        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        osc.connect(gain);
        gain.connect(this.audioCtx.destination);

        const profiles = {
          received: { freq: 1000, duration: 0.15, gain: 0.08 },
          sent: { freq: 600, duration: 0.1, gain: 0.05 },
          default: { freq: 800, duration: 0.2, gain: 0.1 }
        };
        const { freq, duration, gain: g } = profiles[type] || profiles.default;

        osc.frequency.value = freq;
        osc.type = 'sine';
        gain.gain.setValueAtTime(g, this.audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, this.audioCtx.currentTime + duration);
        osc.start();
        osc.stop(this.audioCtx.currentTime + duration);
      } catch (e) {
        console.debug('ℹ️ Sound play failed:', e);
      }
    },

    _normalizeChatId(chatId) {
      if (!chatId) return '';
      return chatId.startsWith('group:') ? chatId.slice(6) : chatId;
    },

    /**
     * Главный обработчик входящего сообщения.
     * Показывает баннер, звук и опционально нативное уведомление.
     */
    handleIncomingMessage(msg) {
      if (!msg?.sender || !msg?.chatId) return;

      // Защита от повторной обработки одного и того же сообщения
      if (msg.messageId) {
        if (this.processedMessageIds.has(msg.messageId)) return;
        this.processedMessageIds.add(msg.messageId);
        if (this.processedMessageIds.size > 1000) {
          const iter = this.processedMessageIds.values();
          for (let i = 0; i < 500; i++) this.processedMessageIds.delete(iter.next().value);
        }
      }

      // Не показываем баннер и не играем звук, если пользователь прямо сейчас в этом чате
      if (this.isActiveChat(msg.chatId)) return;

      // Всегда играем звук (если было взаимодействие)
      this.playSound('received');

      // Всегда показываем внутренний баннер (toast)
      this.showToastForMessage(msg);

      // Нативное уведомление — только когда вкладка скрыта
      if (document.visibilityState !== 'visible') {
        this._showNative(msg);
        if (this.config.blinkEnabled) {
          this.startBlink(msg.preview || 'Новое сообщение');
        }
      }
    },

    showToastForMessage(msg) {
      const senderName = msg.sender?.slice(0, 12) + '…' || '';
      const preview = msg.content || 'Новое сообщение';
      const chatId = msg.chatId;
      const isGroup = msg.isGroup;

      document.querySelectorAll('.in-app-notification').forEach(el => el.remove());

      const toast = document.createElement('div');
      toast.className = 'in-app-notification';
      toast.innerHTML = `
        <div class="in-app-notification-content" style="cursor:pointer;">
          <div class="in-app-avatar">${(senderName[0] || '?').toUpperCase()}</div>
          <div class="in-app-body">
            <div class="in-app-sender">${this._escapeHtml(senderName)}</div>
            <div class="in-app-preview">${this._escapeHtml(preview)}</div>
          </div>
          <button class="in-app-close" aria-label="Close">&times;</button>
        </div>
      `;

      toast.querySelector('.in-app-notification-content').onclick = () => {
        if (typeof window.selectConversation === 'function') {
          window.selectConversation(chatId, senderName, isGroup);
        } else {
          const params = new URLSearchParams({ start_with: chatId, name: senderName });
          window.location.href = '/chat?' + params;
        }
        toast.remove();
      };
      toast.querySelector('.in-app-close').onclick = (e) => {
        e.stopPropagation();
        toast.remove();
      };

      document.body.appendChild(toast);

      setTimeout(() => {
        if (toast.parentNode) toast.remove();
      }, this.config.toastDuration);
    },

    _showNative(msg) {
      if (!('Notification' in window) || Notification.permission !== 'granted') return;
      if (!this.config.notificationEnabled) return;

      const senderName = msg.sender?.slice(0, 12) + '…' || '';
      const title = msg.isGroup ? `👥 ${senderName}` : `💬 ${senderName}`;
      const body = msg.content || 'Новое сообщение';

      try {
        const notif = new Notification(title, {
          body,
          icon: '/static/favicon.ico',
          tag: `msg-${this._normalizeChatId(msg.chatId)}`,
          requireInteraction: true,
          silent: true
        });
        notif.onclick = () => {
          window.focus();
          if (typeof window.selectConversation === 'function') {
            window.selectConversation(msg.chatId, senderName, msg.isGroup);
          } else {
            const params = new URLSearchParams({ start_with: msg.chatId, name: senderName });
            window.location.href = '/chat?' + params;
          }
          notif.close();
        };
        setTimeout(() => notif.close(), this.config.notificationTimeout);
      } catch (e) { /* ignore */ }
    },

    startBlink(text) {
      if (this.blinkInterval) clearInterval(this.blinkInterval);
      let toggle = true;
      const orig = this.originalTitle;
      this.blinkInterval = setInterval(() => {
        if (document.visibilityState === 'visible') {
          this.stopBlink();
          return;
        }
        document.title = toggle ? `🔔 ${text}` : orig;
        toggle = !toggle;
      }, 1000);
    },

    stopBlink() {
      if (this.blinkInterval) {
        clearInterval(this.blinkInterval);
        this.blinkInterval = null;
      }
      document.title = this.originalTitle;
    },

    showToast(message, type = 'info', duration = 4000) {
      document.querySelectorAll('.system-toast').forEach(n => n.remove());
      const toast = document.createElement('div');
      toast.className = `system-toast ${type}`;
      toast.setAttribute('role', 'alert');
      toast.innerHTML = `<span class="icon">${this._getToastIcon(type)}</span>
                         <span>${this._escapeHtml(message)}</span>
                         <button class="close">&times;</button>`;
      const close = () => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 200); };
      toast.querySelector('.close').onclick = close;
      document.body.appendChild(toast);
      setTimeout(close, duration);
    },

    _getToastIcon(type) {
      const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
      return icons[type] || icons.info;
    },

    _escapeHtml(str) {
      const div = document.createElement('div');
      div.textContent = str || '';
      return div.innerHTML;
    },

    configure(cfg) { this.config = { ...this.config, ...cfg }; },

    destroy() {
      this.stopBlink();
      if (this.audioCtx?.state !== 'closed') this.audioCtx?.close().catch(() => {});
      this.processedMessageIds.clear();
      this.initialized = false;
    }
  };

  window.NotificationManager = NotificationManager;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => NotificationManager.init());
  } else {
    NotificationManager.init();
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      NotificationManager.stopBlink();
      document.title = NotificationManager.originalTitle;
    }
  });

  window.addEventListener('beforeunload', () => NotificationManager.destroy());
})();