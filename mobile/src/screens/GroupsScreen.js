import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function GroupsScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Groups</Text>
      <Text style={styles.subtitle}>Этот экран будет реализован позже</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0a0a0a',
    paddingHorizontal: 20,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#ffffff',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: '#666666',
  },
});