/**
 * notification-manager.js — Fixed Notification System
 * 🔔 Handles desktop notifications, sounds, and title blinking
 */

(function() {
  'use strict';

  const NotificationManager = {
    // State
    audioCtx: null,
    originalTitle: document.title,
    blinkInterval: null,
    initialized: false,
    lastNotificationTime: new Map(),
    activeChatId: null,

    // Config
    config: {
      soundEnabled: true,
      notificationEnabled: true,
      blinkEnabled: true,
      throttleMs: 2000,
      maxTracked: 50,
      notificationTimeout: 8000
    },

    /**
     * Initialize notification system
     */
    async init() {
      if (this.initialized) return;
      this.initialized = true;

      // Initialize audio context on first interaction
      const initAudio = () => {
        if (this.audioCtx) return;
        try {
          this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
          console.log('🔊 AudioContext initialized');
        } catch (e) {
          console.debug('ℹ️ Web Audio not available');
        }
      };

      document.addEventListener('click', initAudio, { once: true, passive: true });
      document.addEventListener('touchstart', initAudio, { once: true, passive: true });

      // Request notification permission
      if ('Notification' in window && Notification.permission === 'default') {
        try {
          const result = await Notification.requestPermission();
          console.log('🔔 Notification permission:', result);
        } catch (e) {
          console.debug('ℹ️ Notification request failed:', e);
        }
      }

      console.log('✅ NotificationManager initialized');
    },

    /**
     * Set active chat to suppress notifications
     * @param {string|null} chatId - Chat identifier
     */
    setActiveChat(chatId) {
      this.activeChatId = chatId ? this._normalizeChatId(chatId) : null;

      if (this.activeChatId) {
        console.log('✅ Active chat:', this.activeChatId.slice(0, 16) + '...');
      }

      this.stopBlink();
    },

    /**
     * Play notification sound
     * @param {string} type - Sound type: 'received' | 'sent' | 'default'
     */
    playSound(type = 'default') {
      if (!this.config.soundEnabled) return;

      try {
        if (!this.audioCtx) return;
        if (this.audioCtx.state === 'suspended') {
          this.audioCtx.resume().catch(() => {});
        }

        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();

        osc.connect(gain);
        gain.connect(this.audioCtx.destination);

        // Sound profiles
        const profiles = {
          received: { freq: 1000, duration: 0.15, gain: 0.08 },
          sent: { freq: 600, duration: 0.1, gain: 0.05 },
          default: { freq: 800, duration: 0.2, gain: 0.1 }
        };

        const { freq, duration, gain: gainVal } = profiles[type] || profiles.default;

        osc.frequency.value = freq;
        osc.type = 'sine';
        gain.gain.setValueAtTime(gainVal, this.audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, this.audioCtx.currentTime + duration);

        osc.start();
        osc.stop(this.audioCtx.currentTime + duration);
      } catch (e) {
        console.debug('ℹ️ Sound play failed:', e);
      }
    },

    /**
     * Normalize chat ID for comparison
     * @private
     */
    _normalizeChatId(chatId) {
      if (!chatId) return '';
      return chatId.startsWith('group:') ? chatId.slice(6) : chatId;
    },

    /**
     * Check if user is in the target chat
     * @private
     */
    _isInActiveChat(chatId) {
      if (document.visibilityState !== 'visible') return false;

      const current = this.activeChatId;
      const target = this._normalizeChatId(chatId);

      return !!(current && target && current === target);
    },

    /**
     * Check if notification should be shown (throttling)
     * @private
     */
    _shouldNotify(chatId, sender, timestamp) {
      const key = `${this._normalizeChatId(chatId)}:${sender}`;
      const now = Date.now();
      const lastTime = this.lastNotificationTime.get(key) || 0;

      // Throttle duplicate notifications
      if (now - lastTime < this.config.throttleMs) {
        return false;
      }

      this.lastNotificationTime.set(key, now);

      // Cleanup old entries
      if (this.lastNotificationTime.size > this.config.maxTracked) {
        for (const [k, t] of this.lastNotificationTime) {
          if (now - t > 60000) {
            this.lastNotificationTime.delete(k);
          }
        }
      }

      return true;
    },

    /**
     * Show desktop notification
     * @param {Object} options - Notification options
     */
    show({ sender, chatId, isGroup = false, preview, timestamp = Date.now() }) {
      if (!sender || !chatId) {
        console.warn('⚠️ NotificationManager.show: missing params');
        return;
      }

      if (!this.config.notificationEnabled) return;

      // Play sound if tab is hidden
      if (document.visibilityState !== 'visible') {
        this.playSound('received');
      }

      // Suppress if user is in active chat
      if (this._isInActiveChat(chatId)) {
        return;
      }

      // Throttle check
      if (!this._shouldNotify(chatId, sender, timestamp)) {
        return;
      }

      const senderName = sender.slice(0, 12) + (sender.length > 12 ? '…' : '');
      const title = isGroup ? `👥 ${senderName}` : `💬 ${senderName}`;
      const normalizedChatId = this._normalizeChatId(chatId);

      // Desktop notification
      if ('Notification' in window && Notification.permission === 'granted') {
        try {
          const notification = new Notification(title, {
            body: preview,
            icon: '/static/favicon.ico',
            tag: `msg-${normalizedChatId}`,
            requireInteraction: true,
            silent: true
          });

          notification.onclick = () => {
            window.focus();

            // Try to switch chat via global function
            if (typeof window.selectConversation === 'function') {
              window.selectConversation(chatId, senderName, isGroup);
            } else {
              const params = new URLSearchParams({
                start_with: chatId,
                name: senderName
              });
              window.location.href = `/chat?${params}`;
            }

            notification.close();
          };

          notification.onerror = (e) => console.debug('ℹ️ Notification error:', e);

          // Auto-close after timeout
          setTimeout(() => notification.close(), this.config.notificationTimeout);
        } catch (e) {
          console.debug('ℹ️ Notification failed:', e);
        }
      }

      // Start title blinking if tab is hidden
      if (this.config.blinkEnabled && document.visibilityState !== 'visible') {
        this.startBlink(title);
      }
    },

    /**
     * Start title blinking animation
     * @param {string} text - Text to display
     */
    startBlink(text) {
      if (this.blinkInterval) {
        clearInterval(this.blinkInterval);
      }

      let toggle = true;
      const original = this.originalTitle;

      this.blinkInterval = setInterval(() => {
        if (document.visibilityState === 'visible') {
          this.stopBlink();
          return;
        }

        document.title = toggle ? `🔔 ${text}` : original;
        toggle = !toggle;
      }, 1000);

      console.log('✨ Title blink started');
    },

    /**
     * Stop title blinking
     */
    stopBlink() {
      if (this.blinkInterval) {
        clearInterval(this.blinkInterval);
        this.blinkInterval = null;
      }
      document.title = this.originalTitle;
      console.log('✨ Title blink stopped');
    },

    /**
     * Handle incoming message for notifications
     * @param {Object} msg - Message object
     */
    handleIncomingMessage(msg) {
      if (!msg?.sender || !msg?.chatId) {
        console.warn('⚠️ handleIncomingMessage: invalid message');
        return;
      }

      const isGroup = msg.chatId.startsWith('group:');

      // Generate preview
      let preview = '🔐 Новое сообщение';
      if (msg.image) {
        preview = '📷 Изображение';
      } else if (msg.content) {
        preview = msg.content.slice(0, 50) + (msg.content.length > 50 ? '…' : '');
      }

      this.show({
        sender: msg.sender,
        chatId: msg.chatId,
        isGroup,
        preview,
        timestamp: msg.timestamp || Date.now()
      });
    },

    /**
     * Show in-app toast notification
     * @param {string} message - Message text
     * @param {string} type - Type: 'success' | 'error' | 'warning' | 'info'
     * @param {number} duration - Duration in ms
     */
    showToast(message, type = 'info', duration = 4000) {
      // Remove existing toasts
      document.querySelectorAll('.notification').forEach(n => n.remove());

      const toast = document.createElement('div');
      toast.className = `notification ${type} animate-slide`;
      toast.setAttribute('role', 'alert');
      toast.innerHTML = `
        <span class="icon">${this._getToastIcon(type)}</span>
        <div class="content">
          <div class="message">${this._escapeHtml(message)}</div>
        </div>
        <button class="close" aria-label="Close">&times;</button>
      `;

      // Close handler
      const close = () => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(16px)';
        setTimeout(() => toast.remove(), 200);
      };

      toast.querySelector('.close').onclick = close;

      // Auto-dismiss
      const timeout = setTimeout(close, duration);
      toast.dataset.timeout = timeout;

      document.body.appendChild(toast);
    },

    /**
     * Get icon for toast type
     * @private
     */
    _getToastIcon(type) {
      const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ'
      };
      return icons[type] || icons.info;
    },

    /**
     * Escape HTML to prevent XSS
     * @private
     */
    _escapeHtml(str) {
      if (!str) return '';
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    },

    /**
     * Update configuration
     * @param {Object} newConfig - Config overrides
     */
    configure(newConfig) {
      this.config = { ...this.config, ...newConfig };
      console.log('🔧 NotificationManager config updated');
    },

    /**
     * Cleanup resources
     */
    destroy() {
      this.stopBlink();

      if (this.audioCtx?.state !== 'closed') {
        this.audioCtx?.close().catch(() => {});
      }

      // Clear all timeouts
      document.querySelectorAll('.notification[data-timeout]').forEach(el => {
        clearTimeout(parseInt(el.dataset.timeout));
        el.remove();
      });

      this.initialized = false;
      this.activeChatId = null;
      this.lastNotificationTime.clear();

      console.log('🧹 NotificationManager destroyed');
    }
  };

  // Export to global scope
  window.NotificationManager = NotificationManager;

  // Auto-init on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => NotificationManager.init());
  } else {
    NotificationManager.init();
  }

  // Handle visibility changes
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      NotificationManager.stopBlink();
      document.title = NotificationManager.originalTitle;
    }
  });

  // Cleanup on page unload
  window.addEventListener('beforeunload', () => {
    NotificationManager.destroy();
  });

})();