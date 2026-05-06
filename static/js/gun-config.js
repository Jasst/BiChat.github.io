/**
 * gun-config.js — GunDB Configuration for Dark Messenger
 * 🎯 Smart mode: auto-detect + manual override
 */

(function() {
  'use strict';

  // 🔥 Global flags
  const P2P_OVERRIDE = new URLSearchParams(window.location.search).get('p2p') === 'force';
   // ✅ СТАЛО
  const DEBUG = window.location.hostname === 'localhost' ||
              window.location.hostname === '127.0.0.1' ||
              window.location.port === '5000';

  const GunConfig = {
    peers: [],
    roomPrefix: 'dm_v1:',
    gun: null,
    userId: null,
    mode: 'unknown', // 'p2p' | 'localStorage' | 'disabled'

    /**
     * Detect if WebSocket is blocked by environment
     * @returns {Promise<boolean>} true = blocked
     */
    async _detectWebSocketBlocked() {
      return new Promise((resolve) => {
        if (P2P_OVERRIDE) {
          if (DEBUG) console.log('🔓 P2P forced via URL parameter');
          return resolve(false);
        }

        const testRelay = 'wss://gun.robins.one/gun';
        let ws;

        try {
          ws = new WebSocket(testRelay);
        } catch (e) {
          if (DEBUG) console.debug('ℹ️ WebSocket creation blocked:', e.name);
          return resolve(true);
        }

        const timeout = setTimeout(() => {
          ws?.close();
          resolve(true);
        }, 2000);

        ws.onopen = () => {
          clearTimeout(timeout);
          ws.close();
          resolve(false);
        };

        ws.onerror = () => {
          clearTimeout(timeout);
          resolve(true);
        };
      });
    },

    /**
     * Initialize GunDB with smart mode detection
     * @param {string} userId - User's public address
     * @returns {Promise<boolean>} Success status
     */
    async init(userId) {
      if (!userId || userId.length !== 64) {
        console.warn('⚠️ Invalid user address');
        return false;
      }

      this.userId = userId;

      // 1️⃣ Load peer config from server
      try {
        const res = await fetch('/gun-config', { cache: 'no-store' });
        if (res.ok) {
          const config = await res.json();
          this.peers = config.peers || this.peers;
          this.roomPrefix = config.roomPrefix || this.roomPrefix;
        }
      } catch (e) {
        if (DEBUG) console.debug('ℹ️ Using default peers config');
        this.peers = [
          'https://gun.robins.one/gun',
          'https://relic.eastus.cloudapp.azure.com/gun'
        ];
      }

      // 2️⃣ Check if Gun library is loaded
      if (typeof Gun === 'undefined') {
        console.warn('⚠️ Gun library not loaded');
        this.mode = 'disabled';
        return false;
      }

      // 3️⃣ Detect WebSocket availability
      const isBlocked = await this._detectWebSocketBlocked();

      // 4️⃣ Select operating mode
      if (isBlocked && !P2P_OVERRIDE) {
        // 🔹 localStorage-only mode
        this.mode = 'localStorage';
        this.gun = Gun({
          peers: [],
          localStorage: true,
          radisk: false,
          silent: true
        });
        console.log('✅ GunDB: localStorage mode (WebSocket blocked)');
      } else {
        // 🔹 Full P2P mode
        this.mode = 'p2p';
        this.gun = Gun({
          peers: this.peers,
          localStorage: true,
          radisk: false,
          retry: 3,
          timeout: 5000,
          silent: !DEBUG
        });

        // Connection logging
        this.gun.on('connect', (ctx) => {
          if (DEBUG) console.log('✅ P2P connected:', ctx?.peer?.url);
        });
        this.gun.on('disconnect', (ctx) => {
          if (DEBUG) console.debug('ℹ️ P2P disconnected:', ctx?.peer?.url);
        });
        console.log(`✅ GunDB: P2P mode with ${this.peers.length} peers`);
      }

      return true;
    },

    /**
     * Get Gun room reference for chat
     * @param {string} chatId - Chat identifier
     * @returns {Object} Gun chain reference
     */
    getRoom(chatId) {
      if (!this.gun) throw new Error('Gun not initialized');
      return this.gun.get(this.roomPrefix + chatId);
    },

    /**
     * Check if P2P mode is active
     * @returns {boolean}
     */
    isP2PEnabled() {
      return this.mode === 'p2p';
    },

    /**
     * Encrypt message for P2P transmission
     * @param {string} content - Message content
     * @param {string} recipient - Recipient address
     * @param {string|null} image - Optional image data
     * @returns {Promise<Object>} Encrypted payload
     */
    async encryptMessage(content, recipient, image = null) {
      if (!this.gun?.user) {
        throw new Error('User not authenticated');
      }

      const payload = {
        content: content || '',
        image: image,
        ts: Date.now(),
        version: '1.0'
      };

      // SEA encryption (Gun's encryption module)
      try {
        const encrypted = await SEA.encrypt(
          JSON.stringify(payload),
          recipient,
          null,
          { raw: true }
        );
        return { encrypted, ts: payload.ts };
      } catch (e) {
        console.error('❌ Encryption failed:', e);
        throw e;
      }
    },

    /**
     * Clear sensitive data from memory
     */
    clearSensitive() {
      if (this.gun?.user) {
        // SEA cleanup if needed
      }
      this.userId = null;
    }
  };

  // Export to global scope
  window.GunConfig = GunConfig;

})();