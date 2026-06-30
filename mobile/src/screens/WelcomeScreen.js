import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { LinearGradient } from 'expo-linear-gradient';

export default function WelcomeScreen() {
  const navigation = useNavigation();

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Dark Messenger</Text>
      <Text style={styles.subtitle}>Decentralized • Encrypted</Text>

      <TouchableOpacity
        style={styles.button}
        onPress={() => navigation.navigate('Login')}
      >
        <LinearGradient
          colors={['#6c5ce7', '#4a3db8']}
          style={styles.gradient}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 0 }}
        >
          <Text style={styles.buttonText}>🔑 Login</Text>
        </LinearGradient>
      </TouchableOpacity>

      <TouchableOpacity
        style={[styles.button, styles.outlineButton]}
        onPress={() => navigation.navigate('CreateWallet')}
      >
        <Text style={styles.outlineText}>✨ Create New Wallet</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
    padding: 30,
    justifyContent: 'center',
    alignItems: 'center',
  },
  title: {
    fontSize: 36,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: '#a4b0be',
    marginBottom: 50,
  },
  button: {
    width: '100%',
    marginBottom: 16,
    borderRadius: 50,
    overflow: 'hidden',
  },
  gradient: {
    paddingVertical: 16,
    alignItems: 'center',
  },
  buttonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  outlineButton: {
    borderWidth: 1,
    borderColor: '#6c5ce7',
    backgroundColor: 'transparent',
    paddingVertical: 16,
    alignItems: 'center',
  },
  outlineText: {
    color: '#6c5ce7',
    fontSize: 18,
    fontWeight: 'bold',
  },
});