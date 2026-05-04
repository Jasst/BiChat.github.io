/**
 * p2p-init.js — Инициализация P2P синхронизации
 * Подключается в base.html вместо inline-скрипта
 */

async function initP2P() {
  // Получаем адрес из разных возможных источников
  const userAddress =
    document.getElementById('userAddress')?.dataset?.fullAddress ||
    document.getElementById('address')?.value ||
    '';

  if (!userAddress || !Security.isValidAddress(userAddress)) {
    console.log('⚠️ P2P init skipped: address not ready');
    return false;
  }

  // Ждём загрузки GunDB
  if (!window.GunConfig?.init) {
    console.warn('⚠️ GunConfig not loaded');
    return false;
  }

  const gunReady = await window.GunConfig.init(userAddress);
  if (!gunReady) {
    console.warn('⚠️ P2P sync disabled: Gun not available');
    return false;
  }

  // Инициализируем P2P синхронизацию
  if (typeof P2PSync === 'function') {
    window.p2p = new P2PSync();
    console.log('✅ P2P sync ready');
  }

  // Глобальный хелпер для подписок
  window.subscribeToAllChats = function() {
    console.log('ℹ️ subscribeToAllChats: notifications handled by NotificationManager');
  };

  return true;
}

// Авто-инициализация после загрузки DOM
document.addEventListener('DOMContentLoaded', initP2P);

// Очистка при выгрузке страницы
window.addEventListener('beforeunload', () => {
  window.p2p?.unsubscribeAll?.();
  window.GunConfig?.clearSensitive?.();
  window.NotificationManager?.destroy?.();
});