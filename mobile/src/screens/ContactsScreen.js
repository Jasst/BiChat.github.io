// src/screens/ContactsScreen.js
import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  Alert,
  TextInput,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { colors, glassStyle } from '../theme';
import { GlassCard } from '../components/GlassCard';
import { OvalButton } from '../components/OvalButton';
import { getContacts, addContact, deleteContact } from '../api';
import QRScannerModal from '../components/QRScannerModal';
import { isValidAddress } from '../utils/QRManager';
import { useFocusEffect } from '@react-navigation/native';

export default function ContactsScreen() {
  const [contacts, setContacts] = useState([]);
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [loading, setLoading] = useState(true);
  const [scannerVisible, setScannerVisible] = useState(false);
  const [adding, setAdding] = useState(false);

  // Обновляем при фокусе (как в ChatScreen)
  useFocusEffect(
    useCallback(() => {
      loadContacts();
    }, [])
  );

  const loadContacts = async () => {
    setLoading(true);
    try {
      const data = await getContacts();
      // Сортируем по имени
      const sorted = (data.contacts || []).sort((a, b) =>
        (a.name || '').localeCompare(b.name || '')
      );
      setContacts(sorted);
    } catch (e) {
      Alert.alert('Error', 'Failed to load contacts');
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async () => {
    const trimmedName = name.trim();
    const trimmedAddress = address.trim();

    if (!trimmedName || !trimmedAddress) {
      Alert.alert('Error', 'Fill all fields');
      return;
    }
    if (!isValidAddress(trimmedAddress)) {
      Alert.alert('Error', 'Invalid address (must be 64 hex characters)');
      return;
    }
    // Проверка на дубликат
    if (contacts.some(c => c.address === trimmedAddress)) {
      Alert.alert('Error', 'Contact with this address already exists');
      return;
    }

    setAdding(true);
    try {
      await addContact(trimmedName, trimmedAddress);
      setName('');
      setAddress('');
      await loadContacts();
      Alert.alert('Success', 'Contact added');
    } catch (e) {
      Alert.alert('Error', e.message || 'Failed to add contact');
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = (contactAddress, contactName) => {
    Alert.alert(
      'Delete Contact',
      `Are you sure you want to delete "${contactName}"?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await deleteContact(contactAddress);
              await loadContacts();
            } catch (e) {
              Alert.alert('Error', e.message || 'Failed to delete contact');
            }
          },
        },
      ]
    );
  };

  const handleScan = (scannedAddress) => {
    setAddress(scannedAddress);
    if (!name.trim()) {
      setName('Contact_' + scannedAddress.slice(0, 8));
    }
    setScannerVisible(false);
  };

  const handleStartChat = (contact) => {
    // Навигация в чат с контактом
    const { navigation } = this.props; // если есть доступ
    // Лучше передать navigation через props или useNavigation
  };

  const renderItem = ({ item, index }) => {
    const initials = (item.name || item.address).slice(0, 2).toUpperCase();

    return (
      <TouchableOpacity
        style={styles.item}
        activeOpacity={0.7}
        onLongPress={() => handleDelete(item.address, item.name)}
      >
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{initials}</Text>
        </View>
        <View style={styles.itemInfo}>
          <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
          <Text style={styles.address} numberOfLines={1}>
            {item.address.slice(0, 12)}…{item.address.slice(-4)}
          </Text>
        </View>
        <View style={styles.actions}>
          <TouchableOpacity
            onPress={() => handleDelete(item.address, item.name)}
            style={styles.actionBtn}
            hitSlop={8}
          >
            <Ionicons name="trash-outline" size={20} color={colors.danger} />
          </TouchableOpacity>
        </View>
      </TouchableOpacity>
    );
  };

  const renderEmpty = () => (
    <View style={styles.emptyContainer}>
      <Ionicons name="people-outline" size={64} color="#444" />
      <Text style={styles.empty}>No contacts yet</Text>
      <Text style={styles.emptySub}>Add a contact to start chatting</Text>
    </View>
  );

  if (loading) {
    return (
      <View style={styles.loader}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Contacts</Text>
        <OvalButton
          title="Scan QR"
          onPress={() => setScannerVisible(true)}
          icon={<Ionicons name="qr-code-outline" size={16} color="#fff" />}
        />
      </View>

      <GlassCard style={styles.formCard}>
        <TextInput
          style={styles.input}
          placeholder="Contact name"
          placeholderTextColor={colors.textMuted}
          value={name}
          onChangeText={setName}
          maxLength={50}
        />
        <View style={styles.addressRow}>
          <TextInput
            style={[styles.input, styles.addressInput]}
            placeholder="Address (64 hex chars)"
            placeholderTextColor={colors.textMuted}
            value={address}
            onChangeText={setAddress}
            autoCapitalize="none"
            autoCorrect={false}
            maxLength={64}
          />
          <TouchableOpacity
            style={styles.pasteBtn}
            onPress={async () => {
              // Можно добавить Clipboard API
            }}
          >
            <Ionicons name="clipboard-outline" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        </View>
        <OvalButton
          title={adding ? 'Adding...' : 'Add Contact'}
          primary
          loading={adding}
          onPress={handleAdd}
          style={styles.fullWidth}
          disabled={adding || !name.trim() || !address.trim()}
        />
      </GlassCard>

      <FlatList
        data={contacts}
        keyExtractor={(item) => item.address}
        renderItem={renderItem}
        ListEmptyComponent={renderEmpty}
        style={styles.list}
        contentContainerStyle={contacts.length === 0 ? styles.emptyContent : styles.listContent}
        showsVerticalScrollIndicator={false}
        refreshing={loading}
        onRefresh={loadContacts}
      />

      <QRScannerModal
        visible={scannerVisible}
        onClose={() => setScannerVisible(false)}
        onScan={handleScan}
        title="Scan Contact QR"
      />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
    padding: 16
  },
  loader: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.bgPrimary
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16
  },
  headerTitle: {
    color: colors.textMain,
    fontSize: 28,
    fontWeight: 'bold'
  },
  formCard: {
    marginBottom: 16,
    padding: 16
  },
  input: {
    backgroundColor: 'rgba(0,0,0,0.3)',
    borderWidth: 1,
    borderColor: colors.glassBorder,
    borderRadius: 50,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: colors.textMain,
    marginBottom: 12,
    fontSize: 14,
  },
  addressRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
  },
  addressInput: {
    flex: 1,
    marginBottom: 0,
    marginRight: 8,
  },
  pasteBtn: {
    padding: 10,
    borderRadius: 50,
    backgroundColor: 'rgba(255,255,255,0.05)',
  },
  fullWidth: {
    width: '100%',
    marginTop: 4,
  },
  list: {
    flex: 1
  },
  listContent: {
    paddingBottom: 20,
  },
  emptyContent: {
    flex: 1,
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 4,
    borderBottomWidth: 1,
    borderBottomColor: colors.glassBorder,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  avatarText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 16,
  },
  itemInfo: {
    flex: 1
  },
  name: {
    color: colors.textMain,
    fontSize: 16,
    fontWeight: '500',
    marginBottom: 2,
  },
  address: {
    color: colors.textMuted,
    fontSize: 12,
    fontFamily: 'monospace',
  },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  actionBtn: {
    padding: 8,
    borderRadius: 20,
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
});