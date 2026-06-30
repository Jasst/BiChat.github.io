import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import useUserStore from '../store/userStore';
import { storage } from '../utils/storage';

export default function ProfileScreen() {
  const { address, logout } = useUserStore();

  const handleLogout = () => {
    Alert.alert('Logout', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Logout', style: 'destructive', onPress: logout },
    ]);
  };

  return (
    <View style={styles.container}>
      <Text style={styles.label}>Your Address</Text>
      <Text style={styles.address}>{address || 'Not set'}</Text>
      <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
        <Text style={styles.logoutText}>Logout</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0a', padding: 24, justifyContent: 'center' },
  label: { color: '#a4b0be', fontSize: 14, marginBottom: 8 },
  address: { color: '#fff', fontSize: 16, fontFamily: 'monospace', marginBottom: 40 },
  logoutBtn: { backgroundColor: '#d63031', padding: 16, borderRadius: 50, alignItems: 'center' },
  logoutText: { color: '#fff', fontWeight: 'bold' },
});