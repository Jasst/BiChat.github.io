// App.js
import 'react-native-get-random-values';
import 'react-native-gesture-handler';
import React, { useEffect, useState } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { ActivityIndicator, View } from 'react-native';
import { createStackNavigator } from '@react-navigation/stack';

import BottomTabs from './src/navigation/BottomTabs';
import AuthStack from './src/navigation/AuthStack';
import UnlockScreen from './src/screens/UnlockScreen';
import useUserStore from './src/store/userStore';
import { storage } from './src/utils/storage';
import { getEncryptedMnemonic } from './src/utils/secureStorage';
import { initWebSocket, startHeartbeat, startStatusPolling, startUserStatusPolling } from './src/shared/core';
import DarkCrypto from './src/shared/crypto-client';
import { Buffer } from 'buffer';
import { API_BASE_URL } from './src/config/constants';

global.Buffer = Buffer;

const Stack = createStackNavigator();

export default function App() {
  const { isAuthenticated, needsUnlock, setAuthenticated, setAddress, setNeedsUnlock } = useUserStore();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const restoreSession = async () => {
      try {
        const mnemonic = await storage.getItem('mnemonic');
        if (mnemonic) {
          const keys = await DarkCrypto.deriveKeyPair(mnemonic);
          setAddress(keys.address);
          setAuthenticated(true);

          // ✅ Проверяем nonce
          let nonce = await storage.getItem('nonce');
          if (!nonce) {
            const nonceRes = await fetch(`${API_BASE_URL}/nonce`);
            if (nonceRes.ok) {
              const nonceData = await nonceRes.json();
              nonce = nonceData.nonce;
              await storage.setItem('nonce', nonce);
            } else {
              console.warn('Could not fetch nonce during session restore');
            }
          }

          await initWebSocket();
          startHeartbeat();
          startStatusPolling();
          startUserStatusPolling();

          setLoading(false);
          return;
        }

        const encrypted = await getEncryptedMnemonic();
        if (encrypted) {
          setNeedsUnlock(true, encrypted);
          setAuthenticated(false);
          setLoading(false);
          return;
        }

        setAuthenticated(false);
        setLoading(false);
      } catch (error) {
        console.warn('Failed to restore session:', error);
        setAuthenticated(false);
        setLoading(false);
      }
    };

    restoreSession();
  }, []);

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#0a0a0a' }}>
        <ActivityIndicator size="large" color="#6c5ce7" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {needsUnlock ? (
          <Stack.Screen name="Unlock" component={UnlockScreen} />
        ) : isAuthenticated ? (
          <Stack.Screen name="Main" component={BottomTabs} />
        ) : (
          <Stack.Screen name="Auth" component={AuthStack} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}