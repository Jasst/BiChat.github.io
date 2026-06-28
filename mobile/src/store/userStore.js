import { create } from 'zustand';

const useUserStore = create((set) => ({
  address: null,
  isAuthenticated: false,
  setAddress: (address) => set({ address }),
  setAuthenticated: (status) => set({ isAuthenticated: status }),
  logout: async () => {
    const { storage } = await import('../utils/storage');
    await storage.removeItem('mnemonic');
    await storage.removeItem('userAddress');
    set({ address: null, isAuthenticated: false });
  },
}));

export default useUserStore;