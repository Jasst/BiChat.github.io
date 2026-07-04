// src/screens/WalletScreen.js
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
  Alert,
  TextInput,
  Clipboard,
  Animated,
  Easing,
  ScrollView,
  TouchableOpacity,
  Share,
  Dimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { GlassCard } from '../components/GlassCard';
import { OvalButton } from '../components/OvalButton';
import QRCodeDisplay from '../components/QRCodeDisplay';
import { colors } from '../theme';
import {
  getBalance,
  getGlobalStats,
  getTransactions,
  stake,
  unstake,
  sendCoins,
  getStakingInfo,
} from '../api';
import QRScannerModal from '../components/QRScannerModal';
import { API_BASE_URL } from '../config/constants';
import miningService from '../services/miningService';

const { width: SCREEN_W } = Dimensions.get('window');
const BLOCKCOIN_SATS = 1_000_000;
const AUTO_MINING_KEY = 'autoMining';

const C = {
  bg: '#0a0a0f',
  cardBg: 'rgba(20,20,30,0.7)',
  border: 'rgba(255,255,255,0.08)',
  borderLight: 'rgba(255,255,255,0.14)',
  accent: '#6c5ce7',
  accentGlow: 'rgba(108,92,231,0.35)',
  accentLight: '#a29bfe',
  success: '#00b894',
  successBg: 'rgba(0,184,148,0.12)',
  danger: '#d63031',
  dangerBg: 'rgba(214,48,49,0.12)',
  warning: '#fdcb6e',
  text: '#f5f6fa',
  muted: '#a4b0be',
  darkBg: 'rgba(0,0,0,0.25)',
};

// ========== Хелперы для стейкинга ==========
function estimateTimeFromBlock(unlockBlock, currentBlock) {
  const blocksLeft = unlockBlock - currentBlock;
  const avgBlockTimeSeconds = 60;
  const totalMinutes = Math.max(0, Math.floor((blocksLeft * avgBlockTimeSeconds) / 60));
  if (totalMinutes < 60) return `${totalMinutes} min`;
  const hours = Math.floor(totalMinutes / 60);
  const mins = totalMinutes % 60;
  return `${hours}h ${mins}m`;
}

function calculateStakingData(stakingInfo) {
  const stakes = stakingInfo?.stakes || [];
  const currentBlock = stakingInfo?.current_block || 0;
  const expectedIncome = stakingInfo?.expected_income || 0;

  let totalStaked = 0;
  let weightedTime = 0;
  const nowSec = Date.now() / 1000;

  stakes.forEach(s => {
    totalStaked += s.amount;
    const elapsed = nowSec - (s.start_time || nowSec);
    weightedTime += s.amount * elapsed;
  });

  const avgElapsed = totalStaked > 0 ? weightedTime / totalStaked : 0;
  const years = avgElapsed / (365 * 24 * 3600);
  const apr = years > 0 ? (expectedIncome / totalStaked) / years * 100 : 0;

  return {
    totalStaked,
    expectedIncome,
    apr,
    stakes,
    currentBlock,
  };
}

// ========== Вкладки ==========
const StakingRoute = ({ stakingInfo, onStake, onUnstake, amount, setAmount }) => {
  const data = calculateStakingData(stakingInfo);

  return (
    <ScrollView showsVerticalScrollIndicator={false} style={{ flex: 1 }}>
      <GlassCard style={styles.tabCard}>
        <Text style={styles.tabTitle}>Stake Management</Text>

        {data.stakes.length === 0 ? (
          <View style={styles.emptyState}>
            <Ionicons name="lock-closed-outline" size={40} color={C.muted} style={{ opacity: 0.3 }} />
            <Text style={styles.emptyText}>No active stakes</Text>
          </View>
        ) : (
          <>
            {/* Общая информация */}
            <View style={styles.infoRow}>
              <View style={[styles.iconCircle, { backgroundColor: 'rgba(108,92,231,0.12)' }]}>
                <Ionicons name="stats-chart-outline" size={18} color={C.accent} />
              </View>
              <View style={styles.infoBody}>
                <Text style={styles.infoLabel}>Total Staked</Text>
                <Text style={styles.infoValue}>
                  {(data.totalStaked / BLOCKCOIN_SATS).toFixed(6)}{' '}
                  <Text style={styles.infoUnit}>BlockCoin</Text>
                </Text>
              </View>
            </View>

            {data.expectedIncome > 0 && (
              <View style={styles.infoRow}>
                <View style={[styles.iconCircle, { backgroundColor: C.successBg }]}>
                  <Ionicons name="gift-outline" size={18} color={C.success} />
                </View>
                <View style={styles.infoBody}>
                  <Text style={styles.infoLabel}>Pending Income</Text>
                  <Text style={[styles.infoValue, { color: C.success }]}>
                    {(data.expectedIncome / BLOCKCOIN_SATS).toFixed(6)}{' '}
                    <Text style={styles.infoUnit}>BlockCoin</Text>
                  </Text>
                </View>
              </View>
            )}

            {data.apr > 0 && (
              <View style={styles.infoRow}>
                <View style={[styles.iconCircle, { backgroundColor: 'rgba(253,203,110,0.12)' }]}>
                  <Ionicons name="trending-up-outline" size={18} color={C.warning} />
                </View>
                <View style={styles.infoBody}>
                  <Text style={styles.infoLabel}>APR</Text>
                  <Text style={[styles.infoValue, { color: C.warning }]}>
                    {data.apr.toFixed(2)}%
                  </Text>
                </View>
              </View>
            )}

            <View style={styles.divider} />

            {/* Список стейков */}
            <Text style={[styles.infoLabel, { marginBottom: 10 }]}>Active Stakes</Text>
            {data.stakes.map((s, i) => {
              const timeEst = estimateTimeFromBlock(s.unlock_block, data.currentBlock);
              return (
                <View key={i} style={styles.stakeItem}>
                  <View style={styles.stakeItemLeft}>
                    <Ionicons name="time-outline" size={14} color={C.muted} />
                    <Text style={styles.stakeItemTime}>~{timeEst}</Text>
                  </View>
                  <Text style={styles.stakeItemAmount}>
                    {(s.amount / BLOCKCOIN_SATS).toFixed(6)} BC
                  </Text>
                </View>
              );
            })}

            <View style={styles.divider} />
          </>
        )}

        {/* Форма */}
        <View style={styles.row}>
          <TextInput
            style={[styles.input, { flex: 1 }]}
            placeholder="Amount"
            placeholderTextColor={C.muted}
            value={amount}
            onChangeText={setAmount}
            keyboardType="numeric"
          />
          <OvalButton title="Stake" primary onPress={onStake} />
          <OvalButton
            title="Unstake"
            onPress={onUnstake}
            style={{ borderColor: C.danger, backgroundColor: C.dangerBg }}
            textStyle={{ color: C.danger }}
          />
        </View>
      </GlassCard>
    </ScrollView>
  );
};

const TransferRoute = ({
  sendTo,
  setSendTo,
  sendAmount,
  setSendAmount,
  onSend,
  onScan,
  fee,
  myAddress,
  showQR,
  setShowQR,
  onCopyAddress,
  onShareAddress,
}) => (
  <ScrollView showsVerticalScrollIndicator={false} style={{ flex: 1 }}>
    {/* SEND */}
    <GlassCard style={styles.tabCard}>
      <Text style={styles.tabTitle}>Send BlockCoin</Text>

      <View style={styles.row}>
        <TextInput
          style={[styles.input, { flex: 1 }]}
          placeholder="Recipient address (64 hex)"
          placeholderTextColor={C.muted}
          value={sendTo}
          onChangeText={setSendTo}
          autoCapitalize="none"
          autoCorrect={false}
        />
        <TouchableOpacity style={styles.iconBtn} onPress={onScan}>
          <Ionicons name="scan-outline" size={22} color={C.accent} />
        </TouchableOpacity>
      </View>

      <View style={styles.row}>
        <TextInput
          style={[styles.input, { flex: 1 }]}
          placeholder="Amount"
          placeholderTextColor={C.muted}
          value={sendAmount}
          onChangeText={setSendAmount}
          keyboardType="numeric"
        />
        <OvalButton title="Send" primary onPress={onSend} />
      </View>

      {fee !== null && (
        <View style={styles.feeRow}>
          <Ionicons name="information-circle-outline" size={14} color={C.muted} />
          <Text style={styles.feeText}>
            Fee: {(fee / BLOCKCOIN_SATS).toFixed(6)} BlockCoin
          </Text>
        </View>
      )}
    </GlassCard>

    {/* RECEIVE */}
    <GlassCard style={[styles.tabCard, { marginTop: 14 }]}>
      <Text style={styles.tabTitle}>Receive BlockCoin</Text>

      <View style={styles.receiveHeader}>
        <Text style={styles.receiveLabel}>Your address</Text>
        <TouchableOpacity style={styles.copyBtn} onPress={onCopyAddress}>
          <Ionicons name="copy-outline" size={16} color={C.accent} />
          <Text style={styles.copyBtnText}>Copy</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.addressBox}>
        <Text style={styles.addressText} selectable>
          {myAddress || 'Loading address...'}
        </Text>
      </View>

      <TouchableOpacity
        style={styles.toggleQRBtn}
        onPress={() => setShowQR(!showQR)}
      >
        <Ionicons
          name={showQR ? 'qr-code-outline' : 'expand-outline'}
          size={16}
          color={C.accent}
        />
        <Text style={styles.toggleQRText}>
          {showQR ? 'Hide QR Code' : 'Show QR Code'}
        </Text>
      </TouchableOpacity>

      {showQR && myAddress ? (
        <View style={styles.qrBlock}>
          <QRCodeDisplay value={myAddress} size={200} color="#000" backgroundColor="#fff" />
          <View style={styles.qrActions}>
            <TouchableOpacity style={styles.qrActionBtn} onPress={onShareAddress}>
              <Ionicons name="share-outline" size={18} color={C.accent} />
              <Text style={styles.qrActionText}>Share</Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : null}
    </GlassCard>
  </ScrollView>
);

const HistoryRoute = ({ txs, myAddress }) => (
  <ScrollView showsVerticalScrollIndicator={false} style={{ flex: 1 }}>
    <GlassCard style={styles.tabCard}>
      <Text style={styles.tabTitle}>Transaction History</Text>

      {txs.length === 0 ? (
        <View style={styles.emptyState}>
          <Ionicons name="receipt-outline" size={48} color={C.muted} style={{ opacity: 0.35 }} />
          <Text style={styles.emptyText}>No transactions yet</Text>
        </View>
      ) : (
        txs.map((tx, i) => {
          const config = {
            reward: { label: 'Lottery Reward', sign: '+', icon: 'trophy-outline', color: C.warning, bg: 'rgba(253,203,110,0.12)' },
            fee: { label: 'Fee', sign: '-', icon: 'cash-outline', color: C.danger, bg: C.dangerBg },
            transfer: { label: '', sign: '', icon: 'swap-horizontal', color: C.accent, bg: 'rgba(108,92,231,0.1)' },
            block_reward: { label: 'Block Reward', sign: '+', icon: 'cube-outline', color: C.accent, bg: 'rgba(108,92,231,0.1)' },
            stake: { label: 'Stake', sign: '-', icon: 'lock-closed-outline', color: C.accent, bg: 'rgba(108,92,231,0.1)' },
            unstake: { label: 'Unstake', sign: '+', icon: 'lock-open-outline', color: C.success, bg: C.successBg },
            airdrop: { label: 'Airdrop', sign: '+', icon: 'gift-outline', color: C.warning, bg: 'rgba(253,203,110,0.12)' },
            message_fee: { label: 'Message Fee', sign: '-', icon: 'chatbubble-outline', color: C.danger, bg: C.dangerBg },
            staking_reward: { label: 'Staking Reward', sign: '+', icon: 'pulse-outline', color: C.success, bg: C.successBg },
          };

          let cfg = config[tx.type] || config.transfer;
          let addressInfo = '';

          if (tx.type === 'transfer') {
            if (tx.sender === myAddress) {
              cfg = { ...cfg, label: 'Sent', sign: '-', icon: 'arrow-up-circle-outline', color: C.danger, bg: C.dangerBg };
              addressInfo = '→ ' + (tx.recipient?.slice(0, 10) + '...' + tx.recipient?.slice(-4) || '');
            } else {
              cfg = { ...cfg, label: 'Received', sign: '+', icon: 'arrow-down-circle-outline', color: C.success, bg: C.successBg };
              addressInfo = '← ' + (tx.sender?.slice(0, 10) + '...' + tx.sender?.slice(-4) || '');
            }
          }

          const amount = (tx.amount / BLOCKCOIN_SATS).toFixed(6);
          const time = tx.timestamp ? new Date(tx.timestamp * 1000).toLocaleString() : '';

          return (
            <View key={i} style={styles.txRow}>
              <View style={[styles.txIcon, { backgroundColor: cfg.bg }]}>
                <Ionicons name={cfg.icon} size={20} color={cfg.color} />
              </View>
              <View style={styles.txBody}>
                <Text style={styles.txType}>{cfg.label}</Text>
                {addressInfo ? <Text style={styles.txAddr} numberOfLines={1}>{addressInfo}</Text> : null}
                <Text style={styles.txTime}>{time}</Text>
              </View>
              <Text style={[styles.txAmount, { color: cfg.sign === '+' ? C.success : C.danger }]}>
                {cfg.sign}{amount}
              </Text>
            </View>
          );
        })
      )}
    </GlassCard>
  </ScrollView>
);

const NetworkRoute = ({ stats }) => {
  const items = [
    { icon: 'layers-outline', label: 'Total Supply', value: ((stats.total_supply || 0) / BLOCKCOIN_SATS).toFixed(6) + ' BC' },
    { icon: 'infinite-outline', label: 'Remaining to mine', value: stats.remaining_supply !== null ? (stats.remaining_supply / BLOCKCOIN_SATS).toFixed(6) + ' BC' : '∞' },
    { icon: 'people-outline', label: 'Staking Pool', value: ((stats.staking_pool_balance || 0) / BLOCKCOIN_SATS).toFixed(6) + ' BC' },
    { icon: 'chatbox-outline', label: 'Message Fee', value: ((stats.message_fee || 0) / BLOCKCOIN_SATS).toFixed(6) + ' BC' },
    { icon: 'cube-outline', label: 'Block Reward', value: ((stats.block_reward || 0) / BLOCKCOIN_SATS).toFixed(6) + ' BC' },
    { icon: 'options-outline', label: 'Difficulty', value: stats.difficulty || 0 },
    { icon: 'albums-outline', label: 'Total Blocks', value: stats.total_blocks || 0 },
    { icon: 'pie-chart-outline', label: 'Total Staked', value: ((stats.total_staked || 0) / BLOCKCOIN_SATS).toFixed(6) + ' BC' },
    { icon: 'trending-up-outline', label: 'Staking Fee Ratio', value: ((stats.staking_fee_ratio || 0) * 100).toFixed(1) + '%' },
  ];

  return (
    <ScrollView showsVerticalScrollIndicator={false} style={{ flex: 1 }}>
      <GlassCard style={styles.tabCard}>
        <Text style={styles.tabTitle}>Network Statistics</Text>
        {items.map((item, i) => (
          <View key={i} style={styles.netRow}>
            <View style={styles.netIconBox}>
              <Ionicons name={item.icon} size={16} color={C.accent} />
            </View>
            <Text style={styles.netLabel}>{item.label}</Text>
            <Text style={styles.netValue}>{item.value}</Text>
          </View>
        ))}
      </GlassCard>
    </ScrollView>
  );
};

// ========== Основной компонент ==========
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
  const [activeTab, setActiveTab] = useState('staking');
  const [myAddress, setMyAddress] = useState('');
  const [fee, setFee] = useState(null);
  const [showQR, setShowQR] = useState(false);

  const [isMining, setIsMining] = useState(false);
  const [miningProgress, setMiningProgress] = useState(0);
  const [miningStatus, setMiningStatus] = useState('Click to start mining');
  const [miningHashRate, setMiningHashRate] = useState(0);
  const [miningEta, setMiningEta] = useState(null);

  const pulseAnim = useRef(new Animated.Value(1)).current;
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 1.2, duration: 900, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 1, duration: 900, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      ])
    ).start();
    Animated.timing(fadeAnim, { toValue: 1, duration: 500, useNativeDriver: true }).start();
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const bal = await getBalance();
      setBalance(bal.balance / BLOCKCOIN_SATS);
      const st = await getGlobalStats();
      setStats(st);
      const tx = await getTransactions();
      setTxs(tx.transactions || []);
      const staking = await getStakingInfo();
      setStakingInfo(staking);
      const addr = await AsyncStorage.getItem('userAddress');
      if (addr) setMyAddress(addr);
      await refreshFeeDisplay();
    } catch (e) {
      Alert.alert('Error', e.message);
    }
    setLoading(false);
  }, []);

  const refreshFeeDisplay = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/wallet/config`);
      if (res.ok) {
        const cfg = await res.json();
        setFee(cfg.transfer_fee || 0);
      }
    } catch (e) {
      console.warn('Failed to fetch fee', e);
    }
  };

  const handleStake = async () => {
    if (!amount) return Alert.alert('Enter amount');
    const amt = Math.floor(parseFloat(amount) * BLOCKCOIN_SATS);
    await stake(amt);
    loadData();
    loadStakingInfo();
  };

  const handleUnstake = async () => {
    await unstake();
    loadData();
    loadStakingInfo();
  };

  const loadStakingInfo = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/wallet/staking/info`);
      if (res.ok) {
        const data = await res.json();
        setStakingInfo(data);
      }
    } catch (e) {
      console.warn('Failed to load staking info', e);
    }
  };

  const handleSend = async () => {
    if (!sendTo || !sendAmount) return Alert.alert('Fill all fields');
    const addr = sendTo.trim().toLowerCase();
    if (addr.length !== 64 || !/^[a-f0-9]{64}$/.test(addr)) {
      return Alert.alert('Invalid address', 'Enter a valid 64-character hex address');
    }
    const amt = Math.floor(parseFloat(sendAmount) * BLOCKCOIN_SATS);
    if (isNaN(amt) || amt <= 0) return Alert.alert('Invalid amount');
    await sendCoins(addr, amt);
    loadData();
    setSendTo('');
    setSendAmount('');
  };

  const handleCopyAddress = async () => {
    const addr = await AsyncStorage.getItem('userAddress');
    if (addr) {
      Clipboard.setString(addr);
      Alert.alert('Copied', 'Address copied to clipboard');
    }
  };

  const handleShareAddress = async () => {
    const addr = await AsyncStorage.getItem('userAddress');
    if (!addr) return;
    try {
      await Share.share({ message: addr, title: 'My BlockCoin Address' });
    } catch (e) {
      if (e.name !== 'AbortError') console.error(e);
    }
  };

  useEffect(() => {
    miningService.setCallbacks({
      onProgress: ({ progress, maxIter, hashrate, eta, percent }) => {
        setMiningProgress(percent);
        setMiningHashRate(hashrate);
        setMiningEta(eta);
        setMiningStatus(`Hashing… ${Math.floor(progress / 1000)}k / ${Math.floor(maxIter / 1000)}k`);
      },
      onBlockFound: (result) => {
        Alert.alert('🎉 Block mined!', `+${(result.reward || 0) / BLOCKCOIN_SATS} BlockCoin`);
        loadData();
        loadStakingInfo();
        setIsMining(false);
        setMiningStatus('Block found!');
        setMiningProgress(0);
        setMiningHashRate(0);
        setMiningEta(null);
        AsyncStorage.setItem(AUTO_MINING_KEY, 'false');
      },
      onError: (error) => {
        Alert.alert('Mining Error', error.message);
        setMiningStatus('Error: ' + error.message);
      },
      onStopped: () => {
        setMiningStatus('Stopped');
        setMiningProgress(0);
        setMiningHashRate(0);
        setMiningEta(null);
        setIsMining(false);
        AsyncStorage.setItem(AUTO_MINING_KEY, 'false');
      },
    });

    const checkAuto = async () => {
      const auto = await AsyncStorage.getItem(AUTO_MINING_KEY);
      if (auto === 'true') {
        setIsMining(true);
        miningService.startMining();
      }
    };
    checkAuto();

    return () => miningService.stopMining();
  }, [loadData]);

  const startMining = () => {
    if (isMining) return;
    setIsMining(true);
    AsyncStorage.setItem(AUTO_MINING_KEY, 'true');
    setMiningStatus('Starting…');
    setMiningProgress(0);
    miningService.startMining();
  };

  const stopMining = () => {
    setIsMining(false);
    AsyncStorage.setItem(AUTO_MINING_KEY, 'false');
    miningService.stopMining();
  };

  useEffect(() => {
    loadData();
    loadStakingInfo();
  }, [loadData]);

  const tabs = [
    { key: 'staking', title: 'Staking' },
    { key: 'transfer', title: 'Transfer' },
    { key: 'history', title: 'History' },
    { key: 'network', title: 'Network' },
  ];

  const renderContent = () => {
    switch (activeTab) {
      case 'staking':
        return <StakingRoute stakingInfo={stakingInfo} onStake={handleStake} onUnstake={handleUnstake} amount={amount} setAmount={setAmount} />;
      case 'transfer':
        return (
          <TransferRoute
            sendTo={sendTo}
            setSendTo={setSendTo}
            sendAmount={sendAmount}
            setSendAmount={setSendAmount}
            onSend={handleSend}
            onScan={() => setScannerVisible(true)}
            fee={fee}
            myAddress={myAddress}
            showQR={showQR}
            setShowQR={setShowQR}
            onCopyAddress={handleCopyAddress}
            onShareAddress={handleShareAddress}
          />
        );
      case 'history':
        return <HistoryRoute txs={txs} myAddress={myAddress} />;
      case 'network':
        return <NetworkRoute stats={stats} />;
      default:
        return null;
    }
  };

  if (loading) {
    return (
      <View style={styles.loader}>
        <ActivityIndicator size="large" color={C.accent} />
        <Text style={styles.loaderText}>Loading wallet…</Text>
      </View>
    );
  }

  return (
    <Animated.View style={[styles.root, { opacity: fadeAnim }]}>
      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.scroll}>
        {/* ===== HERO: Баланс ===== */}
        <GlassCard style={styles.balanceCard}>
          <Text style={styles.balanceTitle}>Total Balance</Text>
          <Text style={styles.balanceAmount}>{balance.toFixed(6)}</Text>
          <Text style={styles.balanceCoin}>BlockCoin</Text>

          <View style={styles.balanceDivider} />

          <View style={styles.balanceRow}>
            <View style={styles.balanceLeft}>
              <Ionicons name="lock-closed-outline" size={14} color={C.muted} />
              <Text style={styles.balanceLabel}>Staked:</Text>
            </View>
            <Text style={styles.balanceValue}>
              {((stakingInfo.stakes?.reduce((sum, s) => sum + (s.amount || 0), 0) || 0) / BLOCKCOIN_SATS).toFixed(6)} BC
            </Text>
          </View>

          <View style={styles.balanceRow}>
            <View style={styles.balanceLeft}>
              <Ionicons name="wifi-outline" size={14} color={C.muted} />
              <Text style={styles.balanceLabel}>Network:</Text>
            </View>
            <Text style={[styles.balanceValue, { color: C.success }]}>● Connected</Text>
          </View>
        </GlassCard>

        {/* ===== HERO: Майнинг ===== */}
        <GlassCard style={styles.miningCard}>
          <View style={styles.miningHeader}>
            <Text style={styles.miningTitle}>Mining</Text>
            <Animated.View
              style={[
                styles.miningBadge,
                {
                  backgroundColor: isMining ? C.successBg : 'rgba(255,255,255,0.05)',
                  borderColor: isMining ? C.success : C.border,
                  transform: [{ scale: isMining ? pulseAnim : 1 }],
                },
              ]}
            >
              <View style={[styles.pulseDot, { backgroundColor: isMining ? C.success : C.muted }]} />
              <Text style={{ color: isMining ? C.success : C.muted, fontSize: 12, fontWeight: '600' }}>
                {isMining ? 'Active' : 'Waiting'}
              </Text>
            </Animated.View>
          </View>

          <Text style={styles.miningStatus}>{miningStatus}</Text>

          <View style={styles.miningStats}>
            <View style={styles.statBox}>
              <Text style={styles.statLabel}>HASH RATE</Text>
              <Text style={styles.statValue}>
                {isMining && miningHashRate > 0 ? miningHashRate.toLocaleString() : '—'} h/s
              </Text>
            </View>
            <View style={styles.statBox}>
              <Text style={styles.statLabel}>ETA</Text>
              <Text style={styles.statValue}>
                {isMining && miningEta !== null && miningEta !== Infinity
                  ? (miningEta / 60).toFixed(1) + ' min'
                  : '—'}
              </Text>
            </View>
          </View>

          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${miningProgress}%` }]} />
          </View>

          <View style={styles.miningActions}>
            <TouchableOpacity
              style={[styles.mineBtn, styles.mineStart, isMining && styles.mineDisabled]}
              onPress={startMining}
              disabled={isMining}
            >
              <Text style={styles.mineStartText}>Start Mining</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.mineBtn, styles.mineStop, !isMining && styles.mineDisabled]}
              onPress={stopMining}
              disabled={!isMining}
            >
              <Text style={styles.mineStopText}>Stop</Text>
            </TouchableOpacity>
          </View>
        </GlassCard>

        {/* ===== ТАБЫ (только текст) ===== */}
        <View style={styles.tabsNav}>
          {tabs.map((tab) => (
            <TouchableOpacity
              key={tab.key}
              style={[styles.tabBtn, activeTab === tab.key && styles.tabBtnActive]}
              onPress={() => setActiveTab(tab.key)}
            >
              <Text style={[styles.tabBtnText, activeTab === tab.key && styles.tabBtnTextActive]}>
                {tab.title}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* ===== Контент ===== */}
        {renderContent()}
      </ScrollView>

      <QRScannerModal
        visible={scannerVisible}
        onClose={() => setScannerVisible(false)}
        onScan={(addr) => {
          setSendTo(addr);
          setScannerVisible(false);
        }}
        title="Scan recipient QR"
      />
    </Animated.View>
  );
}

// ========== Стили ==========
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  scroll: { padding: 16, paddingBottom: 40 },
  loader: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: C.bg },
  loaderText: { color: C.muted, marginTop: 12, fontSize: 14 },

  // BALANCE
  balanceCard: {
    padding: 24,
    borderRadius: 24,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: C.border,
  },
  balanceTitle: {
    fontSize: 13,
    textTransform: 'uppercase',
    color: C.muted,
    letterSpacing: 1.5,
    fontWeight: '700',
    marginBottom: 10,
  },
  balanceAmount: {
    fontSize: 42,
    fontWeight: '800',
    color: C.text,
    lineHeight: 48,
  },
  balanceCoin: {
    color: C.accent,
    fontSize: 16,
    fontWeight: '700',
    marginTop: 4,
  },
  balanceDivider: {
    height: 1,
    backgroundColor: C.border,
    marginVertical: 16,
  },
  balanceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  balanceLeft: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  balanceLabel: { color: C.muted, fontSize: 13 },
  balanceValue: { color: C.text, fontWeight: '700', fontSize: 13 },

  // MINING
  miningCard: {
    padding: 20,
    borderRadius: 24,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: C.border,
  },
  miningHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  miningTitle: { fontSize: 18, fontWeight: '700', color: C.text },
  miningBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 50,
    borderWidth: 1,
    gap: 6,
  },
  pulseDot: { width: 8, height: 8, borderRadius: 4 },
  miningStatus: { color: C.muted, fontSize: 13, marginBottom: 14, fontWeight: '500' },
  miningStats: { flexDirection: 'row', gap: 10, marginBottom: 16 },
  statBox: {
    flex: 1,
    backgroundColor: C.darkBg,
    padding: 12,
    borderRadius: 16,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: C.border,
  },
  statLabel: { fontSize: 10, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 },
  statValue: { fontSize: 15, fontWeight: '700', color: C.text },
  progressTrack: {
    height: 6,
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: 50,
    overflow: 'hidden',
    marginBottom: 16,
  },
  progressFill: {
    height: '100%',
    backgroundColor: C.accent,
    borderRadius: 50,
    shadowColor: C.accent,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.6,
    shadowRadius: 8,
  },
  miningActions: { flexDirection: 'row', gap: 10 },
  mineBtn: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 50,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mineStart: {
    backgroundColor: C.accent,
    shadowColor: C.accentGlow,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 12,
    elevation: 6,
  },
  mineStartText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  mineStop: { backgroundColor: C.dangerBg, borderWidth: 1, borderColor: C.danger },
  mineStopText: { color: C.danger, fontWeight: '700', fontSize: 15 },
  mineDisabled: { opacity: 0.35 },

  // TABS
  tabsNav: {
    flexDirection: 'row',
    marginBottom: 16,
    backgroundColor: C.cardBg,
    padding: 5,
    borderRadius: 50,
    borderWidth: 1,
    borderColor: C.border,
    gap: 4,
  },
  tabBtn: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 50,
    backgroundColor: 'transparent',
  },
  tabBtnActive: {
    backgroundColor: C.accent,
    shadowColor: C.accentGlow,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 10,
    elevation: 4,
  },
  tabBtnText: { color: C.muted, fontWeight: '600', fontSize: 13 },
  tabBtnTextActive: { color: '#fff' },

  // TAB CONTENT
  tabCard: { padding: 20, borderRadius: 24, borderWidth: 1, borderColor: C.border },
  tabTitle: { color: C.text, fontSize: 16, fontWeight: '700', marginBottom: 16 },

  // FORMS
  row: { flexDirection: 'row', alignItems: 'center', marginBottom: 12, gap: 8 },
  input: {
    flex: 1,
    backgroundColor: C.darkBg,
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 50,
    paddingHorizontal: 18,
    paddingVertical: 12,
    color: C.text,
    fontSize: 14,
    minWidth: 80,
  },
  iconBtn: {
    width: 48,
    height: 48,
    borderRadius: 50,
    backgroundColor: 'rgba(108,92,231,0.08)',
    borderWidth: 1,
    borderColor: C.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  feeRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 2 },
  feeText: { color: C.muted, fontSize: 12 },

  // STAKING
  infoRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 14, gap: 12 },
  iconCircle: { width: 42, height: 42, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  infoBody: { flex: 1 },
  infoLabel: { color: C.muted, fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 },
  infoValue: { color: C.text, fontSize: 18, fontWeight: '700' },
  infoUnit: { color: C.muted, fontSize: 12, fontWeight: '400' },
  divider: { height: 1, backgroundColor: C.border, marginVertical: 14 },
  stakeItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 12,
    backgroundColor: C.darkBg,
    borderRadius: 12,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: C.border,
  },
  stakeItemLeft: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  stakeItemTime: { color: C.muted, fontSize: 13 },
  stakeItemAmount: { color: C.text, fontWeight: '700', fontSize: 13 },

  // RECEIVE
  receiveHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
  receiveLabel: { color: C.muted, fontSize: 13 },
  copyBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: 'rgba(108,92,231,0.08)',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 50,
    borderWidth: 1,
    borderColor: C.border,
  },
  copyBtnText: { color: C.accent, fontWeight: '600', fontSize: 13 },
  addressBox: {
    backgroundColor: C.darkBg,
    padding: 14,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: C.border,
    marginBottom: 12,
  },
  addressText: { color: C.text, fontFamily: 'monospace', fontSize: 12, lineHeight: 18 },
  toggleQRBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 12,
    borderRadius: 50,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: 'rgba(108,92,231,0.06)',
  },
  toggleQRText: { color: C.accent, fontWeight: '600', fontSize: 14 },
  qrBlock: { alignItems: 'center', marginTop: 16, padding: 16, backgroundColor: '#fff', borderRadius: 20 },
  qrActions: { marginTop: 14, flexDirection: 'row', gap: 10 },
  qrActionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 50,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: 'rgba(108,92,231,0.06)',
  },
  qrActionText: { color: C.accent, fontWeight: '600', fontSize: 13 },

  // TRANSACTIONS
  emptyState: { alignItems: 'center', paddingVertical: 40 },
  emptyText: { color: C.muted, marginTop: 12, fontSize: 14 },
  txRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
  },
  txIcon: { width: 42, height: 42, borderRadius: 12, alignItems: 'center', justifyContent: 'center', marginRight: 12 },
  txBody: { flex: 1, marginRight: 8 },
  txType: { color: C.text, fontSize: 14, fontWeight: '600' },
  txAddr: { color: C.muted, fontSize: 11, marginTop: 2, fontFamily: 'monospace' },
  txTime: { color: C.muted, fontSize: 10, marginTop: 2 },
  txAmount: { fontWeight: '700', fontSize: 14 },

  // NETWORK
  netRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
  },
  netIconBox: { width: 32, alignItems: 'center', marginRight: 8 },
  netLabel: { color: C.muted, fontSize: 14, flex: 1 },
  netValue: { color: C.text, fontWeight: '700', fontSize: 14, fontFamily: 'monospace' },
});