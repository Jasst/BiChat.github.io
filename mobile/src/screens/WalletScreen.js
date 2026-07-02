// src/screens/WalletScreen.js
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
  Alert,
  TextInput,
  ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { SceneMap, TabView } from 'react-native-tab-view';
import { GlassCard } from '../components/GlassCard';
import { OvalButton } from '../components/OvalButton';
import { colors, glassStyle } from '../theme';
import { getBalance, getGlobalStats, getTransactions, stake, unstake, sendCoins, getStakingInfo } from '../api';
import QRScannerModal from '../components/QRScannerModal';

// Вкладки
const StakingRoute = ({ stakingInfo, onStake, onUnstake, amount, setAmount }) => (
  <View style={styles.tabContent}>
    <GlassCard>
      <Text style={styles.infoText}>Staked: {stakingInfo.staked ? (stakingInfo.staked / 1e6).toFixed(6) : 0} BlockCoin</Text>
      <Text style={styles.infoText}>Rewards: {stakingInfo.rewards ? (stakingInfo.rewards / 1e6).toFixed(6) : 0}</Text>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          placeholder="Amount"
          placeholderTextColor="#666"
          value={amount}
          onChangeText={setAmount}
          keyboardType="numeric"
        />
        <OvalButton title="Stake" primary onPress={onStake} />
        <OvalButton title="Unstake" onPress={onUnstake} style={{ borderColor: colors.danger }} />
      </View>
    </GlassCard>
  </View>
);

const TransferRoute = ({ sendTo, setSendTo, sendAmount, setSendAmount, onSend, onScan }) => (
  <View style={styles.tabContent}>
    <GlassCard>
      <Text style={styles.label}>Send BlockCoin</Text>
      <View style={styles.row}>
        <TextInput
          style={[styles.input, { flex: 2 }]}
          placeholder="Recipient address"
          placeholderTextColor="#666"
          value={sendTo}
          onChangeText={setSendTo}
        />
        <OvalButton title="Scan" onPress={onScan} style={{ paddingHorizontal: 16 }} />
      </View>
      <View style={styles.row}>
        <TextInput
          style={[styles.input, { flex: 2 }]}
          placeholder="Amount"
          placeholderTextColor="#666"
          value={sendAmount}
          onChangeText={setSendAmount}
          keyboardType="numeric"
        />
        <OvalButton title="Send" primary onPress={onSend} />
      </View>
    </GlassCard>
    <GlassCard>
      <Text style={styles.label}>Receive</Text>
      <View style={styles.addressRow}>
        <Text style={styles.address} numberOfLines={1}>Your address</Text>
        <OvalButton title="Copy" onPress={() => {}} style={{ paddingHorizontal: 16 }} />
      </View>
    </GlassCard>
  </View>
);

const HistoryRoute = ({ txs }) => (
  <View style={styles.tabContent}>
    <GlassCard>
      {txs.length === 0 ? (
        <Text style={styles.empty}>No transactions</Text>
      ) : (
        txs.map((tx, i) => (
          <View key={i} style={styles.txRow}>
            <Text style={styles.txType}>{tx.type}</Text>
            <Text style={styles.txAmount}>{(tx.amount / 1e6).toFixed(6)}</Text>
          </View>
        ))
      )}
    </GlassCard>
  </View>
);

const NetworkRoute = ({ stats }) => (
  <View style={styles.tabContent}>
    <GlassCard>
      <Text style={styles.infoText}>Total Supply: {(stats.total_supply || 0) / 1e6}</Text>
      <Text style={styles.infoText}>Staking Pool: {(stats.staking_pool_balance || 0) / 1e6}</Text>
      <Text style={styles.infoText}>Message Fee: {(stats.message_fee || 0) / 1e6}</Text>
      <Text style={styles.infoText}>Block Reward: {(stats.block_reward || 0) / 1e6}</Text>
      <Text style={styles.infoText}>Difficulty: {stats.difficulty || 0}</Text>
      <Text style={styles.infoText}>Total Blocks: {stats.total_blocks || 0}</Text>
    </GlassCard>
  </View>
);

export default function WalletScreen() {
  const [balance, setBalance] = useState(0);
  const [stats, setStats] = useState({});
  const [txs, setTxs] = useState([]);
  const [stakingInfo, setStakingInfo] = useState({});
  const [loading, setLoading] = useState(true);
  const [amount, setAmount] = useState('');
  const [sendTo, setSendTo] = useState('');
  const [sendAmount, setSendAmount] = useState('');
  const [scannerVisible, setScannerVisible] = useState(false);
  const [index, setIndex] = useState(0);
  const [routes] = useState([
    { key: 'staking', title: 'Staking' },
    { key: 'transfer', title: 'Transfer' },
    { key: 'history', title: 'History' },
    { key: 'network', title: 'Network' },
  ]);

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

  const handleUnstake = async () => {
    await unstake();
    loadData();
  };

  const handleSend = async () => {
    if (!sendTo || !sendAmount) return Alert.alert('Fill all fields');
    const amt = Math.floor(parseFloat(sendAmount) * 1e6);
    await sendCoins(sendTo, amt);
    loadData();
  };

  const renderScene = SceneMap({
    staking: () => <StakingRoute stakingInfo={stakingInfo} onStake={handleStake} onUnstake={handleUnstake} amount={amount} setAmount={setAmount} />,
    transfer: () => <TransferRoute sendTo={sendTo} setSendTo={setSendTo} sendAmount={sendAmount} setSendAmount={setSendAmount} onSend={handleSend} onScan={() => setScannerVisible(true)} />,
    history: () => <HistoryRoute txs={txs} />,
    network: () => <NetworkRoute stats={stats} />,
  });

  if (loading) return <ActivityIndicator size="large" color={colors.accent} style={styles.loader} />;

  return (
    <View style={styles.container}>
      <GlassCard style={styles.balanceCard}>
        <Text style={styles.balanceTitle}>Total Balance</Text>
        <Text style={styles.balanceAmount}>{balance.toFixed(6)}</Text>
        <Text style={styles.balanceCoin}>BlockCoin</Text>
      </GlassCard>

      {/* Блок майнинга (как в вебе) */}
      <GlassCard style={styles.miningCard}>
        <View style={styles.miningHeader}>
          <Text style={styles.miningTitle}>⛏️ Mining</Text>
          <View style={[styles.miningBadge, { backgroundColor: 'rgba(0,184,148,0.2)', borderColor: colors.success }]}>
            <View style={[styles.pulseDot, { backgroundColor: colors.success }]} />
            <Text style={{ color: colors.success }}>Active</Text>
          </View>
        </View>
        <Text style={styles.miningStatus}>Mining in progress...</Text>
        <View style={styles.progressBar}>
          <View style={[styles.progressFill, { width: '45%' }]} />
        </View>
        <View style={styles.miningActions}>
          <OvalButton title="⚡ Start Mining" primary style={{ flex: 1 }} />
          <OvalButton title="⏹ Stop" style={{ flex: 1, borderColor: colors.danger }} />
        </View>
      </GlassCard>

      <TabView
        navigationState={{ index, routes }}
        renderScene={renderScene}
        onIndexChange={setIndex}
        initialLayout={{ width: 400 }}
        renderTabBar={props => (
          <View style={styles.tabBar}>
            {props.navigationState.routes.map((route, i) => (
              <OvalButton
                key={i}
                title={route.title}
                primary={i === index}
                onPress={() => setIndex(i)}
                style={styles.tabButton}
              />
            ))}
          </View>
        )}
      />

      <QRScannerModal
        visible={scannerVisible}
        onClose={() => setScannerVisible(false)}
        onScan={(addr) => setSendTo(addr)}
        title="Scan recipient QR"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
    padding: 16,
  },
  loader: { flex: 1, justifyContent: 'center', backgroundColor: colors.bgPrimary },
  balanceCard: {
    marginBottom: 20,
    padding: 20,
  },
  balanceTitle: {
    fontSize: 14,
    textTransform: 'uppercase',
    color: colors.textMuted,
    letterSpacing: 1,
    marginBottom: 6,
  },
  balanceAmount: {
    fontSize: 42,
    fontWeight: '800',
    color: colors.textMain,
  },
  balanceCoin: {
    color: colors.accent,
    fontSize: 18,
    fontWeight: '600',
    marginTop: 4,
  },
  miningCard: {
    marginBottom: 20,
  },
  miningHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  miningTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.textMain,
  },
  miningBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 50,
    borderWidth: 1,
  },
  pulseDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  miningStatus: {
    color: colors.textMuted,
    fontSize: 13,
    marginBottom: 12,
  },
  progressBar: {
    height: 6,
    backgroundColor: 'rgba(255,255,255,0.1)',
    borderRadius: 50,
    overflow: 'hidden',
    marginBottom: 16,
  },
  progressFill: {
    height: '100%',
    backgroundColor: colors.accent,
    borderRadius: 50,
  },
  miningActions: {
    flexDirection: 'row',
    gap: 10,
  },
  tabBar: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginVertical: 12,
    gap: 6,
  },
  tabButton: {
    flex: 1,
    minWidth: 80,
  },
  tabContent: {
    flex: 1,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
    gap: 8,
  },
  input: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.3)',
    borderWidth: 1,
    borderColor: colors.glassBorder,
    borderRadius: 50,
    paddingHorizontal: 16,
    paddingVertical: 10,
    color: colors.textMain,
    minWidth: 80,
  },
  label: {
    color: colors.textMuted,
    fontSize: 14,
    marginBottom: 8,
  },
  addressRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  address: {
    color: colors.textMain,
    fontFamily: 'monospace',
    fontSize: 12,
    flex: 1,
    marginRight: 8,
  },
  infoText: {
    color: colors.textMain,
    fontSize: 14,
    marginBottom: 6,
  },
  txRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.glassBorder,
  },
  txType: { color: colors.textMuted, fontSize: 14 },
  txAmount: { color: colors.textMain, fontWeight: '600' },
  empty: { color: colors.textMuted, textAlign: 'center', padding: 20 },
});