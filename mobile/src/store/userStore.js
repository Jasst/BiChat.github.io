// src/store/userStore.js
import { create } from 'zustand';

const useUserStore = create((set) => ({
  address: null,
  isAuthenticated: false,
  needsUnlock: false,          // true, если есть зашифрованная мнемоника и нужно ввести пароль
  encryptedMnemonic: null,     // зашифрованные данные (строка JSON)
  setAddress: (address) => set({ address }),
  setAuthenticated: (status) => set({ isAuthenticated: status }),
  setNeedsUnlock: (needs, encrypted) => set({ needsUnlock: needs, encryptedMnemonic: encrypted }),
  logout: async () => {
    const { storage } = await import('../utils/storage');
    const { clearEncryptedMnemonic } = await import('../utils/secureStorage');
    await storage.removeItem('mnemonic');
    await storage.removeItem('userAddress');
    await clearEncryptedMnemonic();  // удаляем зашифрованную копию
    set({ address: null, isAuthenticated: false, needsUnlock: false, encryptedMnemonic: null });
  },
}));

export default useUserStore;