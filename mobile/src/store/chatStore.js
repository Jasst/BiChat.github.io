import { create } from 'zustand';
import { getConversations, getConversation } from '../api';

const useChatStore = create((set, get) => ({
  conversations: [],
  currentChat: null,
  messages: [],
  loading: false,

  setConversations: (conv) => set({ conversations: conv }),
  setCurrentChat: (chat) => set({ currentChat: chat, messages: [] }),
  setMessages: (msgs) => set({ messages: msgs }),
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),

  // Новый метод для локального добавления сообщения (из actions.js)
  addLocalMessage: (chatId, msg) => {
    const state = get();
    // Если это текущий чат – добавляем в сообщения
    if (state.currentChat?.address === chatId) {
      set({ messages: [...state.messages, msg] });
    }
    // Обновляем превью в списке диалогов
    const convs = state.conversations.map((c) => {
      if (c.address === chatId) {
        return { ...c, last_preview: msg.content?.slice(0, 40) || '📎 File' };
      }
      return c;
    });
    set({ conversations: convs });
  },

  // Новый метод для обновления превью (из actions.js)
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

  // Загрузка списка диалогов
  loadConversations: async () => {
    try {
      const data = await getConversations();
      set({ conversations: data.conversations || [] });
    } catch (e) {
      console.error(e);
    }
  },

  // Загрузка сообщений конкретного чата
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

  // Обработка входящего сообщения через WebSocket
  addIncomingMessage: (msg) => {
    const state = get();
    // Если это текущий чат – добавляем в сообщения
    if (state.currentChat?.address === msg.chatId || state.currentChat?.address === msg.sender) {
      set({ messages: [...state.messages, msg] });
    }
    // Обновляем превью в списке диалогов
    const convs = state.conversations.map((c) => {
      if (c.address === msg.chatId || c.address === msg.sender) {
        return { ...c, last_preview: msg.content?.slice(0, 40) || 'New message' };
      }
      return c;
    });
    set({ conversations: convs });
  },

  // Метод для получения членов группы (заглушка, пока не реализовано)
  getGroupMembers: (groupId) => {
    // В будущем загружать с сервера или из кеша
    return [];
  },

  // Обновление статуса пользователя
  updateUserStatus: (address, status) => {
    // Можно обновить статус в списке диалогов или в отдельном хранилище
    // Пока заглушка
  },

  // Обновление статуса сообщения
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

  // Получить свои сообщения с пометкой is_mine
  getMyPendingMessages: () => {
    const state = get();
    return state.messages.filter((msg) => msg.is_mine && msg.status !== 'read');
  },
}));

export default useChatStore;