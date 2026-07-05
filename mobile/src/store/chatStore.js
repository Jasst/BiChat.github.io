import { create } from 'zustand';
import { getConversations, getConversation } from '../api';

const useChatStore = create((set, get) => ({
  conversations: [],
  currentChat: null,
  messages: [],
  loading: false,

  setConversations: (conv) => set({ conversations: conv }),
  setCurrentChat: (chat) => set({ currentChat: chat, messages: [] }),

  // Теперь поддерживает callback: setMessages(prev => [...prev, msg])
  setMessages: (msgs) => set((state) => ({
    messages: typeof msgs === 'function' ? msgs(state.messages) : msgs
  })),

  // Добавление с защитой от дубликатов
  addMessage: (msg) => set((state) => {
    if (!msg?.id || state.messages.find(m => m.id === msg.id)) return state;
    return { messages: [...state.messages, msg] };
  }),

  // Обновить сообщение по id (ищем старый id, заменяем объект)
  updateMessage: (id, updater) => set((state) => ({
    messages: state.messages.map(m => {
      if (m.id !== id) return m;
      return typeof updater === 'function' ? updater(m) : { ...m, ...updater };
    })
  })),

  // Удалить сообщение по id
  removeMessage: (id) => set((state) => ({
    messages: state.messages.filter(m => m.id !== id)
  })),

  addLocalMessage: (chatId, msg) => {
    const state = get();
    const isCurrent = state.currentChat?.address === chatId;
    const alreadyHas = state.messages.find(m => m.id === msg.id);
    const newMessages = isCurrent && !alreadyHas
      ? [...state.messages, msg]
      : state.messages;
    const convs = state.conversations.map((c) => {
      if (c.address === chatId) {
        return { ...c, last_preview: msg.content?.slice(0, 40) || '📎 File' };
      }
      return c;
    });
    set({ messages: newMessages, conversations: convs });
  },

  updateConversationPreview: (chatId, preview) => {
    const state = get();
    const convs = state.conversations.map((c) => {
      if (c.address === chatId) {
        return { ...c, last_preview: preview };
      }
      return c;
    });
    set({ conversations: convs });
  },

  loadConversations: async () => {
    try {
      const data = await getConversations();
      set({ conversations: data.conversations || [] });
    } catch (e) {
      console.error(e);
    }
  },

  loadMessages: async (address) => {
    try {
      set({ loading: true });
      const data = await getConversation(address);
      set({ messages: data.messages || [], loading: false });
    } catch (e) {
      set({ loading: false });
      console.error(e);
    }
  },

  addIncomingMessage: (msg) => {
    const state = get();
    const chatId = msg.chatId || msg.sender;
    const isCurrent = state.currentChat?.address === chatId || state.currentChat?.address === msg.sender;
    const alreadyHas = state.messages.find(m => m.id === msg.id);
    const newMessages = isCurrent && !alreadyHas
      ? [...state.messages, msg]
      : state.messages;
    const convs = state.conversations.map((c) => {
      if (c.address === chatId || c.address === msg.sender) {
        return { ...c, last_preview: msg.content?.slice(0, 40) || 'New message' };
      }
      return c;
    });
    set({ messages: newMessages, conversations: convs });
  },

  getGroupMembers: (groupId) => {
    return [];
  },

  updateUserStatus: (address, status) => {
    // заглушка
  },

  updateMessageStatus: (messageId, status) => {
    const state = get();
    const updatedMessages = state.messages.map((msg) => {
      if (msg.id === messageId) {
        return { ...msg, status };
      }
      return msg;
    });
    set({ messages: updatedMessages });
  },

  getMyPendingMessages: () => {
    const state = get();
    return state.messages.filter((msg) => msg.is_mine && msg.status !== 'read');
  },
}));

export default useChatStore;