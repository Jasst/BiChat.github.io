// src/screens/ChatScreen.js
import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  Modal,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { GlassCard } from '../components/GlassCard';
import { colors, glassStyle } from '../theme';
import useChatStore from '../store/chatStore';
import useUserStore from '../store/userStore';
import { getContacts } from '../api';
import QRScannerModal from '../components/QRScannerModal';
import { isValidAddress } from '../utils/QRManager';

export default function ChatScreen() {
  const { conversations, loadConversations, loading } = useChatStore();
  const { address: myAddress } = useUserStore();
  const navigation = useNavigation();
  const [refreshing, setRefreshing] = useState(false);

  // ===== Новый чат: модалка (паритет с #newChatModal в chat.html) =====
  const [newChatVisible, setNewChatVisible] = useState(false);
  const [scannerVisible, setScannerVisible] = useState(false);
  const [manualAddress, setManualAddress] = useState('');
  const [contacts, setContacts] = useState([]);
  const [contactsLoading, setContactsLoading] = useState(false);

  useFocusEffect(
    useCallback(() => {
      loadConversations();
    }, [])
  );

  const onRefresh = async () => {
    setRefreshing(true);
    await loadConversations();
    setRefreshing(false);
  };

  const openChat = (item) => {
    navigation.navigate('ChatDetail', {
      address: item.address,
      name: item.name,
      isGroup: item.is_group,
    });
  };

  const openNewChatModal = async () => {
    setNewChatVisible(true);
    setManualAddress('');
    setContactsLoading(true);
    try {
      const data = await getContacts();
      setContacts(data.contacts || []);
    } catch (e) {
      // Список контактов не критичен для ручного ввода/QR — просто оставляем пустым
      setContacts([]);
    } finally {
      setContactsLoading(false);
    }
  };

  const startChatWith = (address, name) => {
    if (!isValidAddress(address)) {
      Alert.alert('Error', 'Invalid address (must be 64 hex characters)');
      return;
    }
    if (address === myAddress) {
      Alert.alert('Error', 'You cannot start a chat with yourself');
      return;
    }
    setNewChatVisible(false);
    navigation.navigate('ChatDetail', {
      address,
      name: name || address.slice(0, 10) + '…',
      isGroup: false,
    });
  };

  const handleScanForNewChat = (scannedAddress) => {
    setScannerVisible(false);
    startChatWith(scannedAddress, null);
  };

  const renderItem = ({ item }) => {
    const isGroup = !!item.is_group;
    const displayName = item.name || (isGroup ? 'Group' : item.address.slice(0, 10));
    const initials = displayName.slice(0, 2).toUpperCase();
    const unreadCount = item.unread_count || 0;

    return (
      <TouchableOpacity style={styles.item} onPress={() => openChat(item)}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{initials}</Text>
          {isGroup && <View style={styles.groupBadge}><Text style={styles.groupBadgeText}>G</Text></View>}
        </View>
        <View style={styles.info}>
          <Text style={styles.name} numberOfLines={1}>{displayName}</Text>
          <Text style={styles.preview} numberOfLines={1}>
            {item.last_preview || 'No messages'}
          </Text>
        </View>
        <View style={styles.rightContainer}>
          <Text style={styles.time}>
            {item.last_time ? new Date(item.last_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
          </Text>
          {unreadCount > 0 && (
            <View style={styles.unreadBadge}>
              <Text style={styles.unreadText}>{unreadCount}</Text>
            </View>
          )}
        </View>
      </TouchableOpacity>
    );
  };

  const renderContactOption = ({ item }) => (
    <TouchableOpacity
      style={styles.contactOption}
      onPress={() => startChatWith(item.address, item.name)}
    >
      <View style={styles.contactAvatar}>
        <Text style={styles.avatarText}>{(item.name || item.address).slice(0, 2).toUpperCase()}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.name}>{item.name}</Text>
        <Text style={styles.preview}>{item.address.slice(0, 16)}…</Text>
      </View>
    </TouchableOpacity>
  );

  if (loading && !refreshing) {
    return <ActivityIndicator size="large" color={colors.accent} style={styles.loader} />;
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Chats</Text>
        <TouchableOpacity style={styles.newChatBtn} onPress={openNewChatModal}>
          <Ionicons name="add" size={26} color="#fff" />
        </TouchableOpacity>
      </View>

      <FlatList
        data={conversations}
        keyExtractor={(item) => item.address}
        renderItem={renderItem}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Ionicons name="chatbubbles-outline" size={64} color="#444" />
            <Text style={styles.empty}>No conversations</Text>
            <Text style={styles.emptySub}>Tap + to start a new chat</Text>
          </View>
        }
        contentContainerStyle={conversations.length === 0 ? styles.emptyContent : null}
      />

      {/* ===== Модалка "Новый чат" — паритет с newChatModal (chat.html) ===== */}
      <Modal visible={newChatVisible} animationType="slide" transparent onRequestClose={() => setNewChatVisible(false)}>
        <View style={styles.modalOverlay}>
          <BlurView intensity={30} tint="dark" style={[styles.modalCard, glassStyle]}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Start New Chat</Text>
              <TouchableOpacity onPress={() => setNewChatVisible(false)}>
                <Ionicons name="close" size={26} color={colors.textMain} />
              </TouchableOpacity>
            </View>

            <TouchableOpacity style={styles.scanBtn} onPress={() => setScannerVisible(true)}>
              <Ionicons name="qr-code-outline" size={20} color="#fff" />
              <Text style={styles.scanBtnText}>Scan QR Code</Text>
            </TouchableOpacity>

            <Text style={styles.sectionLabel}>Select from contacts</Text>
            {contactsLoading ? (
              <ActivityIndicator color={colors.accent} style={{ marginVertical: 12 }} />
            ) : (
              <FlatList
                data={contacts}
                keyExtractor={(item) => item.address}
                renderItem={renderContactOption}
                style={styles.contactsList}
                ListEmptyComponent={<Text style={styles.emptySub}>No contacts yet</Text>}
              />
            )}

            <Text style={styles.sectionLabel}>Or enter address</Text>
            <View style={styles.manualRow}>
              <TextInput
                style={styles.manualInput}
                placeholder="64-character hex address"
                placeholderTextColor={colors.textMuted}
                value={manualAddress}
                onChangeText={setManualAddress}
                autoCapitalize="none"
                maxLength={64}
              />
              <TouchableOpacity
                style={styles.startBtn}
                onPress={() => startChatWith(manualAddress.trim(), null)}
              >
                <Text style={styles.startBtnText}>Start</Text>
              </TouchableOpacity>
            </View>
          </BlurView>
        </View>
      </Modal>

      <QRScannerModal
        visible={scannerVisible}
        onClose={() => setScannerVisible(false)}
        onScan={handleScanForNewChat}
        title="Scan QR to start chat"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  loader: {
    flex: 1,
    justifyContent: 'center',
    backgroundColor: colors.bgPrimary,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
  },
  headerTitle: {
    color: colors.textMain,
    fontSize: 24,
    fontWeight: 'bold',
  },
  newChatBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  item: {
    flexDirection: 'row',
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.glassBorder,
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.02)',
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    position: 'relative',
  },
  avatarText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 18,
  },
  groupBadge: {
    position: 'absolute',
    bottom: -2,
    right: -2,
    backgroundColor: '#2a2a2a',
    borderRadius: 10,
    paddingHorizontal: 4,
    borderWidth: 1,
    borderColor: colors.bgPrimary,
  },
  groupBadgeText: {
    color: '#fff',
    fontSize: 8,
    fontWeight: 'bold',
  },
  info: {
    flex: 1,
    marginRight: 8,
  },
  name: {
    color: colors.textMain,
    fontSize: 16,
    fontWeight: '500',
  },
  preview: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: 2,
  },
  rightContainer: {
    alignItems: 'flex-end',
    gap: 4,
  },
  time: {
    color: colors.textMuted,
    fontSize: 11,
  },
  unreadBadge: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingHorizontal: 6,
    paddingVertical: 2,
    minWidth: 20,
    alignItems: 'center',
  },
  unreadText: {
    color: '#fff',
    fontSize: 11,
    fontWeight: 'bold',
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 60,
  },
  empty: {
    color: colors.textMuted,
    fontSize: 18,
    marginTop: 16,
  },
  emptySub: {
    color: '#666',
    fontSize: 14,
    marginTop: 8,
  },
  emptyContent: {
    flex: 1,
    justifyContent: 'center',
  },

  // ===== Модалка "Новый чат" =====
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  modalCard: {
    maxHeight: '80%',
    padding: 20,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    ...glassStyle,
    borderBottomLeftRadius: 0,
    borderBottomRightRadius: 0,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  modalTitle: {
    color: colors.textMain,
    fontSize: 20,
    fontWeight: '700',
  },
  scanBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: colors.accent,
    borderRadius: 50,
    paddingVertical: 12,
    marginBottom: 16,
  },
  scanBtnText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 15,
  },
  sectionLabel: {
    color: colors.textMuted,
    fontSize: 13,
    marginBottom: 8,
    marginTop: 4,
  },
  contactsList: {
    maxHeight: 180,
    marginBottom: 12,
  },
  contactOption: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.glassBorder,
  },
  contactAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 10,
  },
  manualRow: {
    flexDirection: 'row',
    gap: 8,
  },
  manualInput: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.3)',
    borderWidth: 1,
    borderColor: colors.glassBorder,
    borderRadius: 50,
    paddingHorizontal: 16,
    paddingVertical: 10,
    color: colors.textMain,
    fontFamily: 'monospace',
    fontSize: 13,
  },
  startBtn: {
    backgroundColor: colors.accent,
    borderRadius: 50,
    paddingHorizontal: 18,
    justifyContent: 'center',
  },
  startBtnText: {
    color: '#fff',
    fontWeight: '700',
  },
});