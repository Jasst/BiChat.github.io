// App.js
import 'react-native-gesture-handler';
import React, { useEffect, useState } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { ActivityIndicator, View } from 'react-native';
import { createStackNavigator } from '@react-navigation/stack';

import BottomTabs from './src/navigation/BottomTabs';
import AuthStack from './src/navigation/AuthStack';
import useUserStore from './src/store/userStore';
import { storage } from './src/utils/storage';
import { initWebSocket, startHeartbeat, startStatusPolling, startUserStatusPolling } from './src/shared/core';
import DarkCrypto from './src/shared/crypto-client';

const Stack = createStackNavigator();

export default function App() {
  const { isAuthenticated, setAuthenticated, setAddress } = useUserStore();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const restoreSession = async () => {
      try {
        const mnemonic = await storage.getItem('mnemonic');
        if (mnemonic) {
          // Восстанавливаем адрес из мнемоники
          const keys = await DarkCrypto.deriveKeyPair(mnemonic);
          setAddress(keys.address);
          setAuthenticated(true);

          // Инициализируем WebSocket и фоновые процессы
          await initWebSocket();
          startHeartbeat();
          startStatusPolling();
          startUserStatusPolling();
        } else {
          setAuthenticated(false);
        }
      } catch (error) {
        console.warn('Failed to restore session:', error);
        setAuthenticated(false);
      } finally {
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
        {isAuthenticated ? (
          <Stack.Screen name="Main" component={BottomTabs} />
        ) : (
          <Stack.Screen name="Auth" component={AuthStack} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}