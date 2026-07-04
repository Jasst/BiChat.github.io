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

  // ===== Новый чат: модалка =====
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

  // ===== ИСПРАВЛЕНО: Дедупликация + сортировка =====
  const uniqueConversations = React.useMemo(() => {
    const seen = new Set();
    return conversations
      .filter(item => {
        if (seen.has(item.address)) return false;
        seen.add(item.address);
        return true;
      })
      .sort((a, b) => {
        // Сначала по unread_count (сверху непрочитанные), потом по времени
        const unreadDiff = (b.unread_count || 0) - (a.unread_count || 0);
        if (unreadDiff !== 0) return unreadDiff;
        return (b.last_time || 0) - (a.last_time || 0);
      });
  }, [conversations]);

  const renderItem = ({ item }) => {
    const isGroup = !!item.is_group;
    const displayName = item.name || (isGroup ? 'Group' : item.address.slice(0, 10));
    const initials = displayName.slice(0, 2).toUpperCase();
    const unreadCount = item.unread_count || 0;
    const hasUnread = unreadCount > 0;

    return (
      <TouchableOpacity
        style={[styles.item, hasUnread && styles.itemUnread]}
        onPress={() => openChat(item)}
        activeOpacity={0.7}
      >
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{initials}</Text>
          {isGroup && (
            <View style={styles.groupBadge}>
              <Text style={styles.groupBadgeText}>G</Text>
            </View>
          )}
          {/* ИНДИКАТОР ОНЛАЙН (если есть статус) */}
          {item.status === 'online' && !isGroup && (
            <View style={styles.onlineIndicator} />
          )}
        </View>
        <View style={styles.info}>
          <View style={styles.nameRow}>
            <Text style={[styles.name, hasUnread && styles.nameUnread]} numberOfLines={1}>
              {displayName}
            </Text>
            {item.last_time && (
              <Text style={[styles.time, hasUnread && styles.timeUnread]}>
                {new Date(item.last_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </Text>
            )}
          </View>
          <Text style={[styles.preview, hasUnread && styles.previewUnread]} numberOfLines={1}>
            {item.last_preview || 'No messages'}
          </Text>
        </View>
        <View style={styles.rightContainer}>
          {unreadCount > 0 && (
            <View style={styles.unreadBadge}>
              <Text style={styles.unreadText}>{unreadCount > 99 ? '99+' : unreadCount}</Text>
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
      activeOpacity={0.7}
    >
      <View style={styles.contactAvatar}>
        <Text style={styles.avatarText}>
          {(item.name || item.address).slice(0, 2).toUpperCase()}
        </Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.name}>{item.name || item.address.slice(0, 10)}</Text>
        <Text style={styles.preview}>{item.address.slice(0, 16)}…</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
    </TouchableOpacity>
  );

  if (loading && !refreshing) {
    return (
      <View style={styles.loader}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
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
        data={uniqueConversations}
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
        contentContainerStyle={uniqueConversations.length === 0 ? styles.emptyContent : styles.listContent}
        showsVerticalScrollIndicator={false}
      />

      {/* ===== Модалка "Новый чат" ===== */}
      <Modal
        visible={newChatVisible}
        animationType="slide"
        transparent
        onRequestClose={() => setNewChatVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <BlurView intensity={30} tint="dark" style={[styles.modalCard, glassStyle]}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Start New Chat</Text>
              <TouchableOpacity onPress={() => setNewChatVisible(false)} hitSlop={8}>
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
                ListEmptyComponent={
                  <View style={styles.emptyContacts}>
                    <Ionicons name="people-outline" size={32} color="#555" />
                    <Text style={styles.emptySub}>No contacts yet</Text>
                  </View>
                }
                showsVerticalScrollIndicator={false}
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
                autoCorrect={false}
              />
              <TouchableOpacity
                style={[styles.startBtn, !manualAddress.trim() && styles.startBtnDisabled]}
                onPress={() => startChatWith(manualAddress.trim(), null)}
                disabled={!manualAddress.trim()}
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
    alignItems: 'center',
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
    fontSize: 28,
    fontWeight: 'bold',
  },
  newChatBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  listContent: {
    paddingBottom: 20,
  },
  item: {
    flexDirection: 'row',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.glassBorder,
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.02)',
  },
  itemUnread: {
    backgroundColor: 'rgba(108, 92, 231, 0.08)',
  },
  avatar: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 14,
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
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderWidth: 2,
    borderColor: colors.bgPrimary,
    minWidth: 20,
    alignItems: 'center',
  },
  groupBadgeText: {
    color: '#fff',
    fontSize: 9,
    fontWeight: 'bold',
  },
  onlineIndicator: {
    position: 'absolute',
    bottom: 2,
    right: 2,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.success,
    borderWidth: 2,
    borderColor: colors.bgPrimary,
  },
  info: {
    flex: 1,
    justifyContent: 'center',
  },
  nameRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  name: {
    color: colors.textMain,
    fontSize: 16,
    fontWeight: '500',
    flex: 1,
    marginRight: 8,
  },
  nameUnread: {
    fontWeight: '700',
    color: '#fff',
  },
  time: {
    color: colors.textMuted,
    fontSize: 11,
  },
  timeUnread: {
    color: colors.accent,
    fontWeight: '600',
  },
  preview: {
    color: colors.textMuted,
    fontSize: 13,
  },
  previewUnread: {
    color: 'rgba(255,255,255,0.7)',
    fontWeight: '500',
  },
  rightContainer: {
    alignItems: 'flex-end',
    marginLeft: 8,
    minWidth: 24,
  },
  unreadBadge: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingHorizontal: 7,
    paddingVertical: 3,
    minWidth: 22,
    alignItems: 'center',
    justifyContent: 'center',
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
    maxHeight: '85%',
    padding: 20,
    paddingBottom: 30,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderBottomLeftRadius: 0,
    borderBottomRightRadius: 0,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 20,
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
    gap: 10,
    backgroundColor: colors.accent,
    borderRadius: 50,
    paddingVertical: 14,
    marginBottom: 20,
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  scanBtnText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 15,
  },
  sectionLabel: {
    color: colors.textMuted,
    fontSize: 13,
    marginBottom: 10,
    marginTop: 8,
    fontWeight: '500',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  contactsList: {
    maxHeight: 200,
    marginBottom: 16,
  },
  contactOption: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 4,
    borderBottomWidth: 1,
    borderBottomColor: colors.glassBorder,
  },
  contactAvatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  emptyContacts: {
    alignItems: 'center',
    paddingVertical: 20,
  },
  manualRow: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'center',
  },
  manualInput: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.3)',
    borderWidth: 1,
    borderColor: colors.glassBorder,
    borderRadius: 50,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: colors.textMain,
    fontFamily: 'monospace',
    fontSize: 13,
  },
  startBtn: {
    backgroundColor: colors.accent,
    borderRadius: 50,
    paddingHorizontal: 20,
    paddingVertical: 12,
    justifyContent: 'center',
    alignItems: 'center',
    minWidth: 70,
  },
  startBtnDisabled: {
    backgroundColor: 'rgba(108, 92, 231, 0.3)',
  },
  startBtnText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 14,
  },
});