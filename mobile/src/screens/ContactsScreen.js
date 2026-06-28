import React, { useState, useEffect } from 'react';
import { View, Text, FlatList, TouchableOpacity, Alert, TextInput, StyleSheet, ActivityIndicator } from 'react-native';
import { getContacts, addContact, deleteContact, editContact } from '../api';

export default function ContactsScreen() {
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');

  useEffect(() => {
    loadContacts();
  }, []);

  const loadContacts = async () => {
    setLoading(true);
    try {
      const data = await getContacts();
      setContacts(data.contacts || []);
    } catch (e) {
      Alert.alert('Error', e.message);
    }
    setLoading(false);
  };

  const handleAdd = async () => {
    if (!name || !address) return Alert.alert('Error', 'Fill both fields');
    try {
      await addContact(name, address);
      setName('');
      setAddress('');
      loadContacts();
    } catch (e) {
      Alert.alert('Error', e.message);
    }
  };

  const handleDelete = async (addr) => {
    Alert.alert('Delete', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: async () => {
          await deleteContact(addr);
          loadContacts();
        }
      }
    ]);
  };

  const renderItem = ({ item }) => (
    <View style={styles.item}>
      <View>
        <Text style={styles.name}>{item.name}</Text>
        <Text style={styles.address}>{item.address.slice(0, 16)}…</Text>
      </View>
      <TouchableOpacity onPress={() => handleDelete(item.address)}>
        <Text style={styles.delete}>✕</Text>
      </TouchableOpacity>
    </View>
  );

  if (loading) return <ActivityIndicator size="large" color="#fff" style={styles.loader} />;

  return (
    <View style={styles.container}>
      <View style={styles.form}>
        <TextInput style={styles.input} placeholder="Name" placeholderTextColor="#666" value={name} onChangeText={setName} />
        <TextInput style={styles.input} placeholder="Address (64 hex)" placeholderTextColor="#666" value={address} onChangeText={setAddress} />
        <TouchableOpacity style={styles.addButton} onPress={handleAdd}>
          <Text style={styles.addText}>Add Contact</Text>
        </TouchableOpacity>
      </View>
      <FlatList
        data={contacts}
        keyExtractor={(item) => item.address}
        renderItem={renderItem}
        ListEmptyComponent={<Text style={styles.empty}>No contacts</Text>}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0a', padding: 16 },
  form: { marginBottom: 20 },
  input: { backgroundColor: '#1e1e1e', borderRadius: 8, padding: 12, color: '#fff', marginBottom: 10 },
  addButton: { backgroundColor: '#6c5ce7', padding: 12, borderRadius: 8, alignItems: 'center' },
  addText: { color: '#fff', fontWeight: 'bold' },
  item: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: '#2a2a2a' },
  name: { color: '#fff', fontSize: 16 },
  address: { color: '#a4b0be', fontSize: 12 },
  delete: { color: '#d63031', fontSize: 18 },
  empty: { color: '#a4b0be', textAlign: 'center', marginTop: 40 },
  loader: { flex: 1, justifyContent: 'center' },
});