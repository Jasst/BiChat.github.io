// hooks/useMessages.js
import { useState, useEffect, useCallback } from 'react';
import { getCachedMessages, addMessageToCache } from '../shared/core';
import { getConversation } from '../api'; // наш API-клиент

export function useMessages(chatId) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);

  const loadMessages = useCallback(async (force = false) => {
    if (!chatId) return;
    setLoading(true);
    try {
      // Сначала из кеша
      const cached = getCachedMessages(chatId);
      if (cached.length && !force) {
        setMessages(cached);
        setLoading(false);
        return;
      }
      // Загрузка с сервера
      const data = await getConversation(chatId);
      const msgs = data.messages || [];
      // Сохраняем в кеш
      msgs.forEach(msg => addMessageToCache(chatId, msg));
      setMessages(msgs);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [chatId]);

  const addMessage = useCallback((msg) => {
    setMessages(prev => [...prev, msg]);
  }, []);

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  return { messages, loading, loadMessages, addMessage };
}