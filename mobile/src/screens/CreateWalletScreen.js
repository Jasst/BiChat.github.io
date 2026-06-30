import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Alert, ActivityIndicator } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import DarkCrypto from '../shared/crypto-client';
import useUserStore from '../store/userStore';
import { storage } from '../utils/storage';
import { API_BASE_URL } from '../config/constants';
import { initWebSocket, startHeartbeat, startStatusPolling, startUserStatusPolling } from '../shared/core';

export default function CreateWalletScreen({ navigation }) {
  const [mnemonic, setMnemonic] = useState(null);
  const [loading, setLoading] = useState(false);
  const { setAddress, setAuthenticated } = useUserStore();

  const generateWallet = async () => {
    setLoading(true);
    try {
      const newMnemonic = await DarkCrypto.generateMnemonic();
      const keys = await DarkCrypto.deriveKeyPair(newMnemonic);
      const { address, compressedPubKey } = keys;

      const pubkeyB64 = DarkCrypto._toBase64(compressedPubKey);
      const registerRes = await fetch(`${API_BASE_URL}/create_wallet`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address, public_key: pubkeyB64 })
      });
      const registerData = await registerRes.json();

      if (registerRes.ok) {
        await storage.setItem('mnemonic', newMnemonic);
        await storage.setItem('userAddress', address);
        setAddress(address);
        setAuthenticated(true);
        setMnemonic(newMnemonic);
        Alert.alert('Wallet created', `Your address: ${address}\n\nSave your mnemonic safely!`);

        await initWebSocket();
        startHeartbeat();
        startStatusPolling();
        startUserStatusPolling();

        navigation.replace('Main');
      } else {
        Alert.alert('Error', registerData.error || 'Registration failed');
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
      <Text style={styles.title}>Create New Wallet</Text>
      <Text style={styles.subtitle}>Generate a new 24-word recovery phrase</Text>
      {mnemonic && (
        <View style={styles.mnemonicBox}>
          <Text style={styles.mnemonicText}>{mnemonic}</Text>
        </View>
      )}
      <TouchableOpacity
        style={styles.button}
        onPress={generateWallet}
        disabled={loading}
      >
        <LinearGradient
          colors={['#6c5ce7', '#4a3db8']}
          style={styles.gradient}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 0 }}
        >
          {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Generate Wallet</Text>}
        </LinearGradient>
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
    marginBottom: 8,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 16,
    color: '#a4b0be',
    marginBottom: 30,
    textAlign: 'center',
  },
  mnemonicBox: {
    backgroundColor: '#1e1e1e',
    padding: 16,
    borderRadius: 12,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: '#2a2a2a',
  },
  mnemonicText: {
    color: '#fff',
    fontSize: 16,
    textAlign: 'center',
  },
  button: {
    borderRadius: 50,
    overflow: 'hidden',
  },
  gradient: {
    paddingVertical: 16,
    alignItems: 'center',
  },
  buttonText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 16,
  },
});