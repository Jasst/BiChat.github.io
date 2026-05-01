/**
 * gun-config.js — GunDB конфигурация для Dark Messenger
 * 🎯 Умный режим: авто-детект + ручной оверрайд для будущего
 */

// 🔥 Глобальный флаг: можно переключить вручную для тестов
// Использование: ?p2p=force в URL — включить даже если хостинг блокирует
const P2P_OVERRIDE = new URLSearchParams(window.location.search).get('p2p') === 'force';

window.GunConfig = {
  peers: [],
  roomPrefix: 'dm_v1:',
  gun: null,
  userId: null,
  mode: 'unknown', // 'p2p' | 'localStorage' | 'disabled'

  /**
   * Детектирование, блокирует ли среда WebSocket
   * @returns {Promise<boolean>} true = блокировка (shared-хостинг)
   */
  async _detectWebSocketBlocked() {
    return new Promise((resolve) => {
      // Если принудительное включение — сразу считаем что всё ок
      if (P2P_OVERRIDE) {
        console.log('🔓 P2P forced via URL parameter');
        return resolve(false);
      }

      // Быстрый тест подключения к стабильному релею
      const testRelay = 'wss://gun.robins.one/gun';
      let ws;

      try {
        ws = new WebSocket(testRelay);
      } catch (e) {
        // 🔥 Ловим блокировку на уровне создания сокета
        console.debug('ℹ️ WebSocket creation blocked:', e.name);
        return resolve(true);
      }

      const timeout = setTimeout(() => {
        ws.close();
        resolve(true); // Не ответил за 2с → скорее всего блокировка
      }, 2000);

      ws.onopen = () => {
        clearTimeout(timeout);
        ws.close();
        resolve(false); // WebSocket работает ✅
      };

      ws.onerror = () => {
        clearTimeout(timeout);
        resolve(true); // Ошибка → блокировка ❌
      };
    });
  },

  async init(userId) {
    this.userId = userId;

    // 1️⃣ Загружаем конфиг пиров с сервера
    try {
      const res = await fetch('/gun-config');
      const config = await res.json();
      this.peers = config.peers || [];
      this.roomPrefix = config.roomPrefix || 'dm_v1:';
    } catch (e) {
      console.debug('ℹ️ Gun config fetch failed, using defaults', e);
      this.peers = [
        'https://gun.robins.one/gun',
        'https://relic.eastus.cloudapp.azure.com/gun',
        'https://gun-manhattan.herokuapp.com/gun'
      ];
    }

    // 2️⃣ Проверяем, загружена ли библиотека Gun
    if (typeof Gun === 'undefined') {
      console.warn('⚠️ Gun library not loaded');
      this.mode = 'disabled';
      return false;
    }

    // 3️⃣ Детектируем блокировку WebSocket (если не форсировано)
    const isBlocked = await this._detectWebSocketBlocked();

    // 4️⃣ Выбираем режим работы
    if (isBlocked && !P2P_OVERRIDE) {
      // 🔹 Режим 1: только localStorage (для shared-хостинга)
      this.mode = 'localStorage';
      this.gun = Gun({
        peers: [],           // ❌ Не пытаемся подключаться к релеям
        localStorage: true,  // ✅ Локальный кэш работает
        radisk: false,
        silent: true         // Меньше внутренних логов
      });
      console.log('✅ GunDB: localStorage mode (WebSocket blocked)');
      console.log('💡 To test P2P: add ?p2p=force to URL');
    } else {
      // 🔹 Режим 2: полный P2P (для VPS / локальной разработки)
      this.mode = 'p2p';
      this.gun = Gun({
        peers: this.peers,   // ✅ Подключаемся к релеям
        localStorage: true,  // ✅ + локальный кэш
        radisk: false,
        retry: 3,
        timeout: 5000,
        silent: false
      });

      // Логирование подключений (только в режиме P2P)
      this.gun.on('connect', (ctx) => {
        console.log('✅ P2P connected:', ctx?.peer?.url);
      });
      this.gun.on('disconnect', (ctx) => {
        console.debug('ℹ️ P2P disconnected:', ctx?.peer?.url);
      });

      console.log(`✅ GunDB: P2P mode with ${this.peers.length} peers`);
    }

    return true;
  },

  getRoom(chatId) {
    if (!this.gun) throw new Error('Gun not initialized');
    return this.gun.get(this.roomPrefix + chatId);
  },

  /**
   * Проверка, активен ли полноценный P2P-режим
   * @returns {boolean}
   */
  isP2PEnabled() {
    return this.mode === 'p2p';
  },

  /**
   * Очистка чувствительных данных
   */
  clearSensitive() {
    // Мнемоника не хранится здесь — только в session на сервере
    if (this.gun?.user) {
      // Дополнительная очистка если нужно
    }
  }
};