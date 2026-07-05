// utils/QRManager.js
export function parseQRData(data) {
  if (!data) return null;
  // Проверка на 64-символьный hex адрес
  if (/^[a-fA-F0-9]{64}$/.test(data)) return data.toLowerCase();
  // Поддержка darkmsg:...
  if (data.toLowerCase().startsWith('darkmsg:')) {
    const match = data.match(/darkmsg:([a-fA-F0-9]{64})/i);
    if (match?.[1]) return match[1].toLowerCase();
  }
  // Поддержка bitcoin:...
  if (data.toLowerCase().startsWith('bitcoin:')) {
    const match = data.match(/bitcoin:([a-fA-F0-9]{64})/i);
    if (match?.[1]) return match[1].toLowerCase();
  }
  return null;
}

export function isValidAddress(address) {
  return typeof address === 'string' && address.length === 64 && /^[a-fA-F0-9]{64}$/.test(address);
}