/**
 * gun-config.js — GunDB конфигурация для Dark Messenger
 * Минимальная версия, работает с локальным запуском
 */
window.GunConfig = {
  peers: [],
  roomPrefix: 'dm_v1:',
  gun: null,
  userId: null,

  async init(userId) {
    this.userId = userId;
    
    // Загружаем конфиг с сервера
    try {
      const res = await fetch('/gun-config');
      const config = await res.json();
      this.peers = config.peers || [];
      this.roomPrefix = config.roomPrefix || 'dm_v1:';
    } catch (e) {
      console.warn('⚠️ Gun config fetch failed, using defaults', e);
      this.peers = [
        'https://gun.robins.one/gun',
        'https://relic.eastus.cloudapp.azure.com/gun'
      ];
    }

    // Инициализируем Gun, если библиотека загружена
    if (typeof Gun !== 'undefined') {
      this.gun = Gun({ 
        peers: this.peers, 
        localStorage: true,
        radisk: false,
        retry: 3,
        timeout: 5000
      });
      
      // Логирование подключения
      this.gun.on('connect', ctx => {
        console.log('✅ Gun connected:', ctx?.peer?.url);
      });
      
      console.log('✅ GunDB initialized with', this.peers.length, 'peers');
      return true;
    }
    
    console.warn('⚠️ Gun library not loaded yet');
    return false;
  },

  getRoom(chatId) {
    if (!this.gun) throw new Error('Gun not initialized');
    return this.gun.get(this.roomPrefix + chatId);
  },

  clearSensitive() {
    // Очистка чувствительных данных (если нужно)
  }
};