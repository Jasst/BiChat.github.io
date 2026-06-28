import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  FlatList,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Alert,
} from 'react-native';
import useChatStore from '../store/chatStore';
import useUserStore from '../store/userStore';
import { getConversation } from '../api';
import { sendMessage as sendEncryptedMessage } from '../shared/actions';

export default function ChatDetailScreen({ route }) {
  const { address, name, isGroup } = route.params;
  const { messages, setMessages, addMessage } = useChatStore();
  const { address: myAddress } = useUserStore();
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const flatListRef = useRef();

  // Загрузка сообщений
  const loadMessages = async () => {
    setLoading(true);
    try {
      const data = await getConversation(address);
      setMessages(data.messages || []);
    } catch (e) {
      console.error(e);
      Alert.alert('Error', 'Failed to load messages');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMessages();
  }, [address]);

  const handleSend = async () => {
    if (!input.trim()) return;
    const content = input.trim();
    setInput('');

    // Локальное добавление сообщения (для мгновенного отображения)
    const tempMsg = {
      id: Date.now(),
      sender: myAddress,
      content: content,
      timestamp: Date.now() / 1000,
      is_mine: true,
      status: 'sent',
    };
    addMessage(tempMsg);
    flatListRef.current?.scrollToEnd();

    try {
      const result = await sendEncryptedMessage(
        address,
        content,
        null,
        isGroup,
        isGroup ? address.replace('group:', '') : null
      );
      // Можно обновить статус или ID сообщения, если нужно
      console.log('Message sent:', result);
    } catch (e) {
      console.error(e);
      Alert.alert('Error', 'Failed to send message');
      // Опционально: удалить временное сообщение или пометить ошибкой
    }
  };

  const renderItem = ({ item }) => (
    <View style={[styles.messageRow, item.is_mine ? styles.myMessage : styles.otherMessage]}>
      <Text style={styles.messageText}>{item.content}</Text>
      <Text style={styles.time}>
        {new Date(item.timestamp * 1000).toLocaleTimeString()}
      </Text>
    </View>
  );

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.header}>
        <Text style={styles.headerTitle}>{name || address.slice(0, 10)}</Text>
      </View>
      {loading ? (
        <Text style={styles.loading}>Loading...</Text>
      ) : (
        <FlatList
          ref={flatListRef}
          data={messages}
          keyExtractor={(item) => item.id.toString()}
          renderItem={renderItem}
          contentContainerStyle={{ paddingVertical: 16 }}
          onContentSizeChange={() => flatListRef.current?.scrollToEnd()}
        />
      )}
      <View style={styles.inputContainer}>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={setInput}
          placeholder="Type a message..."
          placeholderTextColor="#666"
          multiline
        />
        <TouchableOpacity style={styles.sendButton} onPress={handleSend}>
          <Text style={styles.sendText}>➤</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0a' },
  header: {
    padding: 16,
    backgroundColor: '#141414',
    borderBottomWidth: 1,
    borderBottomColor: '#2a2a2a',
  },
  headerTitle: { color: '#fff', fontSize: 18, fontWeight: '600' },
  messageRow: {
    marginVertical: 4,
    maxWidth: '80%',
    padding: 10,
    borderRadius: 16,
  },
  myMessage: {
    alignSelf: 'flex-end',
    backgroundColor: '#6c5ce7',
  },
  otherMessage: {
    alignSelf: 'flex-start',
    backgroundColor: '#2a2a2a',
  },
  messageText: { color: '#fff', fontSize: 15 },
  time: {
    color: '#aaa',
    fontSize: 10,
    marginTop: 4,
    alignSelf: 'flex-end',
  },
  loading: { color: '#fff', textAlign: 'center', marginTop: 40 },
  inputContainer: {
    flexDirection: 'row',
    padding: 10,
    borderTopWidth: 1,
    borderTopColor: '#2a2a2a',
    alignItems: 'center',
  },
  input: {
    flex: 1,
    backgroundColor: '#1e1e1e',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 8,
    color: '#fff',
    maxHeight: 100,
  },
  sendButton: {
    marginLeft: 8,
    backgroundColor: '#6c5ce7',
    borderRadius: 24,
    padding: 10,
  },
  sendText: { color: '#fff', fontSize: 18 },
});