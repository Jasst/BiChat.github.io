// src/screens/ContactsScreen.js
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  Alert,
  TextInput,
  StyleSheet,
  ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { colors } from '../theme';
import { GlassCard } from '../components/GlassCard';
import { OvalButton } from '../components/OvalButton';
import { getContacts, addContact, deleteContact } from '../api';
import QRScannerModal from '../components/QRScannerModal';
import { isValidAddress } from '../utils/QRManager';

export default function ContactsScreen() {
  const [contacts, setContacts] = useState([]);
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [loading, setLoading] = useState(true);
  const [scannerVisible, setScannerVisible] = useState(false);

  useEffect(() => { loadContacts(); }, []);

  const loadContacts = async () => {
    setLoading(true);
    try {
      const data = await getContacts();
      setContacts(data.contacts || []);
    } catch (e) {
      Alert.alert('Error', 'Failed to load contacts');
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async () => {
    if (!name.trim() || !address.trim()) {
      Alert.alert('Error', 'Fill all fields');
      return;
    }
    if (!isValidAddress(address.trim())) {
      Alert.alert('Error', 'Invalid address (must be 64 hex characters)');
      return;
    }
    try {
      await addContact(name.trim(), address.trim());
      setName('');
      setAddress('');
      await loadContacts();
    } catch (e) {
      Alert.alert('Error', e.message);
    }
  };

  const handleDelete = (address) => {
    Alert.alert('Delete', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await deleteContact(address);
            await loadContacts();
          } catch (e) {
            Alert.alert('Error', e.message);
          }
        },
      },
    ]);
  };

  const handleScan = (scannedAddress) => {
    setAddress(scannedAddress);
    if (!name.trim()) {
      setName('Contact_' + scannedAddress.slice(0, 8));
    }
  };

  const renderItem = ({ item }) => (
    <View style={styles.item}>
      <View style={styles.itemInfo}>
        <Text style={styles.name}>{item.name}</Text>
        <Text style={styles.address}>{item.address.slice(0, 16)}…</Text>
      </View>
      <TouchableOpacity onPress={() => handleDelete(item.address)} style={styles.deleteBtn}>
        <Ionicons name="trash-outline" size={20} color={colors.danger} />
      </TouchableOpacity>
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
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Contacts</Text>
        <OvalButton title="Scan QR" onPress={() => setScannerVisible(true)} icon="📷" />
      </View>

      <GlassCard style={styles.formCard}>
        <TextInput
          style={styles.input}
          placeholder="Name"
          placeholderTextColor={colors.textMuted}
          value={name}
          onChangeText={setName}
        />
        <TextInput
          style={styles.input}
          placeholder="Address (64 hex)"
          placeholderTextColor={colors.textMuted}
          value={address}
          onChangeText={setAddress}
          autoCapitalize="none"
        />
        <OvalButton title="Add Contact" primary onPress={handleAdd} style={styles.fullWidth} />
      </GlassCard>

      <FlatList
        data={contacts}
        keyExtractor={(item) => item.address}
        renderItem={renderItem}
        ListEmptyComponent={<Text style={styles.empty}>No contacts</Text>}
        style={styles.list}
      />

      <QRScannerModal
        visible={scannerVisible}
        onClose={() => setScannerVisible(false)}
        onScan={handleScan}
        title="Scan Contact QR"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bgPrimary, padding: 16 },
  loader: { flex: 1, justifyContent: 'center', backgroundColor: colors.bgPrimary },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 },
  headerTitle: { color: colors.textMain, fontSize: 24, fontWeight: 'bold' },
  formCard: { marginBottom: 16, padding: 16 },
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
  fullWidth: { width: '100%' },
  list: { flex: 1 },
  item: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.glassBorder,
    alignItems: 'center',
  },
  itemInfo: { flex: 1 },
  name: { color: colors.textMain, fontSize: 16 },
  address: { color: colors.textMuted, fontSize: 12 },
  deleteBtn: { padding: 8 },
  empty: { color: colors.textMuted, textAlign: 'center', marginTop: 40 },
});