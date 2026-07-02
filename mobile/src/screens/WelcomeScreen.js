// src/screens/WelcomeScreen.js
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { BlurView } from 'expo-blur';
import { colors, glassStyle } from '../theme';
import { OvalButton } from '../components/OvalButton';

export default function WelcomeScreen() {
  const navigation = useNavigation();

  return (
    <View style={styles.container}>
      <BlurView intensity={20} tint="dark" style={[styles.card, glassStyle]}>
        <Text style={styles.title}>Dark Messenger</Text>
        <Text style={styles.subtitle}>Decentralized • Encrypted</Text>
        <OvalButton
          title="🔑 Login"
          primary
          onPress={() => navigation.navigate('Login')}
          style={styles.fullWidth}
        />
        <OvalButton
          title="✨ Create New Wallet"
          onPress={() => navigation.navigate('CreateWallet')}
          style={[styles.fullWidth, styles.outlineBtn]}
        />
      </BlurView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 30,
  },
  card: {
    width: '100%',
    maxWidth: 480,
    padding: 32,
    alignItems: 'center',
    ...glassStyle,
  },
  title: {
    fontSize: 36,
    fontWeight: 'bold',
    color: colors.textMain,
    marginBottom: 8,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 16,
    color: colors.textMuted,
    marginBottom: 40,
    textAlign: 'center',
  },
  fullWidth: {
    width: '100%',
    marginBottom: 16,
  },
  outlineBtn: {
    borderColor: colors.accent,
    borderWidth: 1,
    backgroundColor: 'transparent',
  },
});