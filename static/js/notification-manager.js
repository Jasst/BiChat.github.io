/**
 * notification-manager.js — Полная система уведомлений
 * 🔔 Звук (без файлов), баннеры, нативные уведомления
 *
 * ИСПРАВЛЕНИЯ v2:
 * 1. _showNative: удалён requireInteraction:true — ломает iOS (уведомление не показывается)
 * 2. _showNative: new Notification() не работает надёжно на мобильных когда страница в фоне;
 *    используем registration.showNotification() через SW — единственный надёжный способ
 * 3. Добавлен throttle на showToastForMessage — не показывать тост каждые 100мс при burst
 */
(function() {
  'use strict';

  const NotificationManager = {
    audioCtx: null,
    userInteracted: false,
    originalTitle: document.title,
    blinkInterval: null,
    initialized: false,
    lastNotificationTime: new Map(),
    activeChatId: null,
    processedMessageIds: new Set(),

    config: {
      soundEnabled: true,
      notificationEnabled: true,
      blinkEnabled: true,
      throttleMs: 2000,
      maxTracked: 100,
      notificationTimeout: 8000,
      toastDuration: 5000
    },

    async init() {
      if (this.initialized) return;
      this.initialized = true;

      // Не запрашиваем разрешение автоматически – только по жесту
      // Отмечаем факт взаимодействия пользователя для звука
      const markInteraction = () => {
        if (this.userInteracted) return;
        this.userInteracted = true;
        this._ensureAudioContext();
        document.removeEventListener('click', markInteraction);
        document.removeEventListener('touchstart', markInteraction);
        document.removeEventListener('pointerdown', markInteraction);
        document.removeEventListener('keydown', markInteraction);
      };
      // pointerdown + keydown покрывают больше сценариев на мобильных PWA
      document.addEventListener('click', markInteraction, { passive: true });
      document.addEventListener('touchstart', markInteraction, { passive: true });
      document.addEventListener('pointerdown', markInteraction, { passive: true });
      document.addEventListener('keydown', markInteraction, { passive: true });
    }, // ← запятая

    async requestNotificationPermission() {
      if (!('Notification' in window)) return false;
      if (Notification.permission === 'granted') {
        if (window.initPushNotifications) window.initPushNotifications();
        return true;
      }
      if (Notification.permission === 'denied') return false;
      try {
        const permission = await Notification.requestPermission();
        if (permission === 'granted') {
          if (window.initPushNotifications) window.initPushNotifications();
          return true;
        }
      } catch (e) {
        console.debug('Notification request failed', e);
      }
      return false;
    }, // ← запятая

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
    }, // ← запятая

    setActiveChat(chatId) {
      this.activeChatId = chatId ? this._normalizeChatId(chatId) : null;
      this.stopBlink();
    }, // ← запятая

    isActiveChat(chatId) {
      if (document.visibilityState !== 'visible') return false;
      const current = this.activeChatId;
      const target = this._normalizeChatId(chatId);
      return !!(current && target && current === target);
    }, // ← запятая

    playSound(type = 'received') {
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
          sent:     { freq: 600,  duration: 0.1,  gain: 0.05 },
          default:  { freq: 800,  duration: 0.2,  gain: 0.1  }
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
    }, // ← запятая

    _normalizeChatId(chatId) {
      if (!chatId) return '';
      return chatId.startsWith('group:') ? chatId.slice(6) : chatId;
    }, // ← запятая

    handleIncomingMessage(msg) {
      if (!msg?.sender || !msg?.chatId) return;

      if (msg.messageId) {
        if (this.processedMessageIds.has(msg.messageId)) return;
        this.processedMessageIds.add(msg.messageId);
        if (this.processedMessageIds.size > this.config.maxTracked) {
          const iter = this.processedMessageIds.values();
          const deleteCount = Math.floor(this.config.maxTracked / 2);
          for (let i = 0; i < deleteCount; i++) {
            this.processedMessageIds.delete(iter.next().value);
          }
        }
      }

      if (this.isActiveChat(msg.chatId)) return;

      const now = Date.now();
      const lastTime = this.lastNotificationTime.get(msg.chatId) || 0;
      const shouldThrottle = (now - lastTime) < this.config.throttleMs;
      if (!shouldThrottle) {
        this.lastNotificationTime.set(msg.chatId, now);
        this.playSound('received');
        this.showToastForMessage(msg);
      }

      if (document.visibilityState !== 'visible') {
        this._showViaSW(msg);
        if (this.config.blinkEnabled) {
          this.startBlink(msg.preview || 'Новое сообщение');
        }
      }
    }, // ← запятая

    showToastForMessage(msg) {
      const senderName = (msg.sender?.slice(0, 12) || '?') + '…';
      // ИСПРАВЛЕНИЕ: используем msg.content (расшифрованный текст) или msg.preview
      const preview = msg.content || msg.preview || 'Новое сообщение';
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
          const params = new URLSearchParams({ start_with: chatId, name: senderName || 'Contact' });
          window.location.href = '/chat?' + params.toString();
        }
        toast.remove();
      };

      toast.querySelector('.in-app-close').onclick = (e) => {
        e.stopPropagation();
        toast.remove();
      };

      document.body.appendChild(toast);
      setTimeout(() => { if (toast.parentNode) toast.remove(); }, this.config.toastDuration);
    }, // ← запятая

    async _showViaSW(msg) {
      if (!this.config.notificationEnabled) return;
      if (!('serviceWorker' in navigator)) return;
      if (Notification.permission !== 'granted') return;

      try {
        const registration = await navigator.serviceWorker.ready;
        const senderName = (msg.sender?.slice(0, 12) || '?') + '…';
        const title = msg.isGroup ? `👥 ${senderName}` : `💬 ${senderName}`;
        const body = msg.content || 'Новое сообщение';
        const chatId = this._normalizeChatId(msg.chatId);

        await registration.showNotification(title, {
          body,
          icon: '/static/icon-192.png',
          badge: '/static/icon-192.png',
          tag: `msg-${chatId}`,
          renotify: true,
          silent: false,
          data: {
            url: msg.isGroup ? `/chat?group=${chatId}` : `/chat?address=${chatId}`,
            chatId: msg.chatId,
            isGroup: msg.isGroup
          }
        });
      } catch(e) {
        this._showNativeFallback(msg);
      }
    }, // ← запятая

    _showNativeFallback(msg) {
      if (!('Notification' in window) || Notification.permission !== 'granted') return;
      try {
        const senderName = (msg.sender?.slice(0, 12) || '?') + '…';
        const title = msg.isGroup ? `👥 ${senderName}` : `💬 ${senderName}`;
        const notif = new Notification(title, {
          body: msg.content || 'Новое сообщение',
          icon: '/static/icon-192.png',
          tag: `msg-${this._normalizeChatId(msg.chatId)}`,
          silent: true
        });
        notif.onclick = () => {
          window.focus();
          if (typeof window.selectConversation === 'function') {
            window.selectConversation(msg.chatId, senderName, msg.isGroup);
          }
          notif.close();
        };
        setTimeout(() => notif.close(), this.config.notificationTimeout);
      } catch (e) { /* ignore */ }
    }, // ← запятая

    startBlink(text) {
      if (this.blinkInterval) clearInterval(this.blinkInterval);
      let toggle = true;
      const orig = this.originalTitle;
      this.blinkInterval = setInterval(() => {
        if (document.visibilityState === 'visible') { this.stopBlink(); return; }
        document.title = toggle ? `🔔 ${text}` : orig;
        toggle = !toggle;
      }, 1000);
    }, // ← запятая

    stopBlink() {
      if (this.blinkInterval) { clearInterval(this.blinkInterval); this.blinkInterval = null; }
      document.title = this.originalTitle;
    }, // ← запятая

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
    }, // ← запятая

    _getToastIcon(type) {
      const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
      return icons[type] || icons.info;
    }, // ← запятая

    _escapeHtml(str) {
      const div = document.createElement('div');
      div.textContent = str || '';
      return div.innerHTML;
    }, // ← запятая

    configure(cfg) { this.config = { ...this.config, ...cfg }; }, // ← запятая

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