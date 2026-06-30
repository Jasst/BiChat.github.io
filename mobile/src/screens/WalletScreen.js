import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, TextInput } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { getBalance, getGlobalStats, getTransactions, stake, unstake, sendCoins, getStakingInfo } from '../api';

export default function WalletScreen() {
  const [balance, setBalance] = useState(0);
  const [stats, setStats] = useState({});
  const [txs, setTxs] = useState([]);
  const [stakingInfo, setStakingInfo] = useState({});
  const [loading, setLoading] = useState(true);
  const [amount, setAmount] = useState('');
  const [sendTo, setSendTo] = useState('');
  const [sendAmount, setSendAmount] = useState('');

  const loadData = async () => {
    setLoading(true);
    try {
      const bal = await getBalance();
      setBalance(bal.balance / 1e6);
      const st = await getGlobalStats();
      setStats(st);
      const tx = await getTransactions();
      setTxs(tx.transactions || []);
      const staking = await getStakingInfo();
      setStakingInfo(staking);
    } catch (e) {
      Alert.alert('Error', e.message);
    }
    setLoading(false);
  };

  useEffect(() => { loadData(); }, []);

  const handleStake = async () => {
    if (!amount) return Alert.alert('Enter amount');
    const amt = Math.floor(parseFloat(amount) * 1e6);
    await stake(amt);
    loadData();
  };

  const handleSend = async () => {
    if (!sendTo || !sendAmount) return Alert.alert('Fill all fields');
    const amt = Math.floor(parseFloat(sendAmount) * 1e6);
    await sendCoins(sendTo, amt);
    loadData();
  };

  if (loading) return <ActivityIndicator size="large" color="#6c5ce7" style={styles.loader} />;

  return (
    <View style={styles.container}>
      <Text style={styles.balance}>{balance.toFixed(6)} BlockCoin</Text>
      <View style={styles.row}>
        <TextInput style={styles.input} placeholder="Stake amount" placeholderTextColor="#666" value={amount} onChangeText={setAmount} keyboardType="numeric" />
        <TouchableOpacity style={styles.btn} onPress={handleStake}><Text style={styles.btnText}>Stake</Text></TouchableOpacity>
        <TouchableOpacity style={[styles.btn, { backgroundColor: '#d63031' }]} onPress={unstake}><Text style={styles.btnText}>Unstake</Text></TouchableOpacity>
      </View>
      <View style={styles.row}>
        <TextInput style={styles.input} placeholder="Recipient address" placeholderTextColor="#666" value={sendTo} onChangeText={setSendTo} />
        <TextInput style={styles.input} placeholder="Amount" placeholderTextColor="#666" value={sendAmount} onChangeText={setSendAmount} keyboardType="numeric" />
        <TouchableOpacity style={styles.btn} onPress={handleSend}><Text style={styles.btnText}>Send</Text></TouchableOpacity>
      </View>
      <Text style={styles.stats}>Supply: {stats.total_supply ? (stats.total_supply / 1e6).toFixed(6) : 0}</Text>
      <Text style={styles.stats}>Staking pool: {stats.staking_pool_balance ? (stats.staking_pool_balance / 1e6).toFixed(6) : 0}</Text>
      <Text style={styles.txsTitle}>Transactions</Text>
      {txs.slice(0, 5).map((tx, i) => (
        <Text key={i} style={styles.tx}>{tx.type} {tx.amount / 1e6}</Text>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0a', padding: 16 },
  balance: { fontSize: 32, color: '#fff', fontWeight: 'bold', marginBottom: 20 },
  row: { flexDirection: 'row', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' },
  input: {
    backgroundColor: '#1e1e1e',
    borderRadius: 12,
    padding: 10,
    color: '#fff',
    flex: 1,
    marginRight: 8,
    minWidth: 100,
    borderWidth: 1,
    borderColor: '#2a2a2a',
  },
  btn: { backgroundColor: '#6c5ce7', padding: 10, borderRadius: 50 },
  btnText: { color: '#fff', fontWeight: 'bold' },
  stats: { color: '#a4b0be', fontSize: 14, marginVertical: 4 },
  txsTitle: { color: '#fff', fontSize: 18, marginTop: 16, marginBottom: 8 },
  tx: { color: '#fff', fontSize: 14, paddingVertical: 4 },
  loader: { flex: 1, justifyContent: 'center', backgroundColor: '#0a0a0a' },
});