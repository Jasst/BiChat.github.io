import React, { useState, useEffect } from 'react';
import { View, Text, FlatList, TouchableOpacity, Alert, TextInput, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { getContacts, addContact, deleteContact, editContact } from '../api';

export default function ContactsScreen() {
  // ... логика (без изменений)

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
        renderItem={({ item }) => (
          <View style={styles.item}>
            <View>
              <Text style={styles.name}>{item.name}</Text>
              <Text style={styles.address}>{item.address.slice(0, 16)}…</Text>
            </View>
            <TouchableOpacity onPress={() => handleDelete(item.address)}>
              <Ionicons name="trash-outline" size={20} color="#d63031" />
            </TouchableOpacity>
          </View>
        )}
        ListEmptyComponent={<Text style={styles.empty}>No contacts</Text>}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0a', padding: 16 },
  form: { marginBottom: 20 },
  input: {
    backgroundColor: '#1e1e1e',
    borderRadius: 12,
    padding: 12,
    color: '#fff',
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#2a2a2a',
  },
  addButton: {
    backgroundColor: '#6c5ce7',
    padding: 12,
    borderRadius: 50,
    alignItems: 'center',
  },
  addText: { color: '#fff', fontWeight: 'bold' },
  item: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#2a2a2a',
    alignItems: 'center',
  },
  name: { color: '#fff', fontSize: 16 },
  address: { color: '#a4b0be', fontSize: 12 },
  empty: { color: '#a4b0be', textAlign: 'center', marginTop: 40 },
});