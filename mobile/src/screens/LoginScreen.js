import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert, ActivityIndicator } from 'react-native';
import DarkCrypto from '../shared/crypto-client';
import useUserStore from '../store/userStore';
import { storage } from '../utils/storage';
import { API_BASE_URL } from '../config/constants';
import { initWebSocket, startHeartbeat, startStatusPolling, startUserStatusPolling } from '../shared/core';

export default function LoginScreen({ navigation }) {
  const [mnemonic, setMnemonic] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const { setAddress, setAuthenticated } = useUserStore();

  const handleLogin = async () => {
    if (!mnemonic.trim()) {
      Alert.alert('Error', 'Enter your mnemonic phrase');
      return;
    }

    setLoading(true);
    try {
      const keys = await DarkCrypto.deriveKeyPair(mnemonic.trim());
      const { address, compressedPubKey, signPrivateKey } = keys;

      // Получаем nonce с сервера
      const nonceRes = await fetch(`${API_BASE_URL}/nonce`);
      if (!nonceRes.ok) throw new Error('Failed to get nonce');
      const nonceData = await nonceRes.json();
      const nonce = nonceData.nonce;

      // Подписываем nonce
      const signatureArray = await DarkCrypto.signData(signPrivateKey, nonce);
      const signatureHex = Array.from(new Uint8Array(signatureArray))
        .map(b => b.toString(16).padStart(2, '0')).join('');
      const pubkeyB64 = DarkCrypto._toBase64(compressedPubKey);

      // Отправляем логин
      const loginRes = await fetch(`${API_BASE_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address, public_key: pubkeyB64, signature: signatureHex })
      });
      const loginData = await loginRes.json();

      if (loginRes.ok) {
        // Сохраняем мнемонику и адрес
        await storage.setItem('mnemonic', mnemonic.trim());
        await storage.setItem('userAddress', address);
        setAddress(address);
        setAuthenticated(true);

        // Инициализируем WebSocket
        await initWebSocket();
        startHeartbeat();
        startStatusPolling();
        startUserStatusPolling();

        navigation.replace('Main');
      } else {
        Alert.alert('Login failed', loginData.error || 'Invalid credentials');
      }
    } catch (error) {
      console.error(error);
      Alert.alert('Error', error.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Login</Text>
      <TextInput
        style={styles.input}
        placeholder="Enter your 24-word mnemonic"
        placeholderTextColor="#666"
        multiline
        numberOfLines={4}
        value={mnemonic}
        onChangeText={setMnemonic}
      />
      <TextInput
        style={styles.input}
        placeholder="Encryption password (optional)"
        placeholderTextColor="#666"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
      />
      <TouchableOpacity style={styles.button} onPress={handleLogin} disabled={loading}>
        {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Login</Text>}
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
    padding: 20,
    justifyContent: 'center',
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 30,
    textAlign: 'center',
  },
  input: {
    backgroundColor: '#1e1e1e',
    borderRadius: 12,
    padding: 12,
    color: '#fff',
    fontSize: 16,
    marginBottom: 16,
    minHeight: 80,
    textAlignVertical: 'top',
  },
  button: {
    backgroundColor: '#6c5ce7',
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  buttonText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 16,
  },
});