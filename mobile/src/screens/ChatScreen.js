import React, { useEffect, useState } from 'react';
import { View, Text, FlatList, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import useChatStore from '../store/chatStore';
import useUserStore from '../store/userStore';
import { useNavigation } from '@react-navigation/native';

export default function ChatScreen() {
  const { conversations, loadConversations } = useChatStore();
  const { address } = useUserStore();
  const navigation = useNavigation();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadConversations().finally(() => setLoading(false));
  }, []);

  const openChat = (item) => {
    navigation.navigate('ChatDetail', {
      address: item.address,
      name: item.name,
      isGroup: item.is_group,
    });
  };

  const renderItem = ({ item }) => (
    <TouchableOpacity style={styles.item} onPress={() => openChat(item)}>
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>{item.name ? item.name[0].toUpperCase() : '?'}</Text>
      </View>
      <View style={styles.info}>
        <Text style={styles.name} numberOfLines={1}>{item.name || item.address.slice(0, 10)}</Text>
        <Text style={styles.preview} numberOfLines={1}>{item.last_preview || 'No messages'}</Text>
      </View>
      <Text style={styles.time}>
        {item.last_time ? new Date(item.last_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
      </Text>
    </TouchableOpacity>
  );

  if (loading) return <ActivityIndicator size="large" color="#6c5ce7" style={styles.loader} />;

  return (
    <View style={styles.container}>
      <FlatList
        data={conversations}
        keyExtractor={(item) => item.address}
        renderItem={renderItem}
        ListEmptyComponent={<Text style={styles.empty}>No conversations</Text>}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
    paddingHorizontal: 16,
  },
  item: {
    flexDirection: 'row',
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#2a2a2a',
    alignItems: 'center',
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#6c5ce7',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  avatarText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 18,
  },
  info: {
    flex: 1,
    marginRight: 8,
  },
  name: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '500',
  },
  preview: {
    color: '#a4b0be',
    fontSize: 13,
    marginTop: 2,
  },
  time: {
    color: '#666',
    fontSize: 11,
  },
  empty: {
    color: '#a4b0be',
    textAlign: 'center',
    marginTop: 50,
  },
  loader: {
    flex: 1,
    justifyContent: 'center',
    backgroundColor: '#0a0a0a',
  },
});