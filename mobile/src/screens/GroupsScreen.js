// src/screens/GroupsScreen.js
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  Alert,
  TextInput,
  StyleSheet,
  ActivityIndicator,
  ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { colors, glassStyle } from '../theme';
import { GlassCard } from '../components/GlassCard';
import { OvalButton } from '../components/OvalButton';
import { GlassModal } from '../components/GlassModal';
import { getGroups, createGroup, deleteGroup, addGroupMember, removeGroupMember } from '../api';
import useUserStore from '../store/userStore';
import QRScannerModal from '../components/QRScannerModal';
import { isValidAddress } from '../utils/QRManager';

export default function GroupsScreen() {
  const { address: myAddress } = useUserStore();
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [groupName, setGroupName] = useState('');
  const [selectedMembers, setSelectedMembers] = useState([]);
  const [scannerVisible, setScannerVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [currentGroup, setCurrentGroup] = useState(null);
  const [newMemberAddress, setNewMemberAddress] = useState('');

  useEffect(() => { loadGroups(); }, []);

  const loadGroups = async () => {
    setLoading(true);
    try {
      const data = await getGroups();
      setGroups(data.groups || []);
    } catch (e) {
      Alert.alert('Error', 'Failed to load groups');
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!groupName.trim()) {
      Alert.alert('Error', 'Enter group name');
      return;
    }
    if (selectedMembers.length === 0) {
      Alert.alert('Error', 'Select at least one member');
      return;
    }
    try {
      await createGroup(groupName.trim(), selectedMembers);
      setGroupName('');
      setSelectedMembers([]);
      setModalVisible(false);
      await loadGroups();
    } catch (e) {
      Alert.alert('Error', e.message);
    }
  };

  const handleDelete = (groupId, groupName) => {
    Alert.alert('Delete Group', `Are you sure you want to delete "${groupName}"?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await deleteGroup(groupId);
            await loadGroups();
          } catch (e) {
            Alert.alert('Error', e.message);
          }
        },
      },
    ]);
  };

  const openDetail = (group) => {
    setCurrentGroup(group);
    setDetailModalVisible(true);
  };

  const handleAddMember = async () => {
    if (!newMemberAddress.trim() || !isValidAddress(newMemberAddress.trim())) {
      Alert.alert('Error', 'Enter a valid 64-hex address');
      return;
    }
    try {
      await addGroupMember(currentGroup.id, newMemberAddress.trim());
      setNewMemberAddress('');
      const updated = await getGroups();
      const refreshed = updated.groups.find(g => g.id === currentGroup.id);
      if (refreshed) setCurrentGroup(refreshed);
      await loadGroups();
    } catch (e) {
      Alert.alert('Error', e.message);
    }
  };

  const handleRemoveMember = async (address) => {
    Alert.alert('Remove Member', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Remove',
        style: 'destructive',
        onPress: async () => {
          try {
            await removeGroupMember(currentGroup.id, address);
            const updated = await getGroups();
            const refreshed = updated.groups.find(g => g.id === currentGroup.id);
            if (refreshed) setCurrentGroup(refreshed);
            await loadGroups();
          } catch (e) {
            Alert.alert('Error', e.message);
          }
        },
      },
    ]);
  };

  const renderItem = ({ item }) => {
    const isCreator = item.creator === myAddress;
    return (
      <GlassCard style={styles.groupCard}>
        <View style={styles.groupInfo}>
          <Text style={styles.groupName}>{item.name}</Text>
          <Text style={styles.groupMeta}>{item.members.length} members</Text>
        </View>
        <View style={styles.groupActions}>
          <TouchableOpacity onPress={() => openDetail(item)} style={styles.iconButton}>
            <Ionicons name="information-circle-outline" size={24} color={colors.textMain} />
          </TouchableOpacity>
          {isCreator && (
            <TouchableOpacity onPress={() => handleDelete(item.id, item.name)} style={styles.iconButton}>
              <Ionicons name="trash-outline" size={24} color={colors.danger} />
            </TouchableOpacity>
          )}
        </View>
      </GlassCard>
    );
  };

  if (loading) {
    return (
      <View style={styles.loader}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Groups</Text>
        <OvalButton title="+ New Group" primary onPress={() => setModalVisible(true)} />
      </View>

      <FlatList
        data={groups}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        ListEmptyComponent={<Text style={styles.empty}>No groups</Text>}
        contentContainerStyle={styles.listContent}
      />

      {/* Modal создания группы */}
      <GlassModal
        visible={modalVisible}
        onClose={() => setModalVisible(false)}
        title="Create Group"
        footer={
          <>
            <OvalButton title="Cancel" onPress={() => setModalVisible(false)} />
            <OvalButton title="Create" primary onPress={handleCreate} />
          </>
        }
      >
        <TextInput
          style={styles.input}
          placeholder="Group name"
          placeholderTextColor={colors.textMuted}
          value={groupName}
          onChangeText={setGroupName}
        />
        <Text style={styles.label}>Members (addresses)</Text>
        <View style={styles.membersInputRow}>
          <TextInput
            style={[styles.input, { flex: 1, marginRight: 8 }]}
            placeholder="Add address"
            placeholderTextColor={colors.textMuted}
            value={selectedMembers.join(', ')}
            editable={false}
          />
          <TouchableOpacity onPress={() => setScannerVisible(true)}>
            <Ionicons name="qr-code-outline" size={28} color={colors.accent} />
          </TouchableOpacity>
        </View>
        {/* Здесь можно добавить список выбранных членов */}
      </GlassModal>

      {/* Modal деталей группы */}
      <GlassModal
        visible={detailModalVisible}
        onClose={() => setDetailModalVisible(false)}
        title={currentGroup?.name || 'Group Details'}
        footer={
          <OvalButton title="Close" onPress={() => setDetailModalVisible(false)} />
        }
      >
        <Text style={styles.label}>Members</Text>
        {currentGroup?.members.map((addr) => (
          <View key={addr} style={styles.memberRow}>
            <Text style={styles.memberAddress}>{addr.slice(0, 16)}…</Text>
            {addr !== myAddress && addr !== currentGroup?.creator && (
              <TouchableOpacity onPress={() => handleRemoveMember(addr)}>
                <Ionicons name="close-circle" size={20} color={colors.danger} />
              </TouchableOpacity>
            )}
            {addr === currentGroup?.creator && <Text style={styles.creatorBadge}>Owner</Text>}
          </View>
        ))}
        <View style={styles.addMemberRow}>
          <TextInput
            style={[styles.input, { flex: 1, marginRight: 8 }]}
            placeholder="Add member address"
            placeholderTextColor={colors.textMuted}
            value={newMemberAddress}
            onChangeText={setNewMemberAddress}
            autoCapitalize="none"
          />
          <OvalButton title="Add" primary onPress={handleAddMember} />
        </View>
      </GlassModal>

      <QRScannerModal
        visible={scannerVisible}
        onClose={() => setScannerVisible(false)}
        onScan={(addr) => {
          if (!selectedMembers.includes(addr)) {
            setSelectedMembers([...selectedMembers, addr]);
          }
          setScannerVisible(false);
        }}
        title="Scan member QR"
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
  loader: {
    flex: 1,
    justifyContent: 'center',
    backgroundColor: colors.bgPrimary,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  headerTitle: {
    color: colors.textMain,
    fontSize: 24,
    fontWeight: 'bold',
  },
  listContent: {
    paddingBottom: 20,
  },
  groupCard: {
    marginBottom: 12,
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  groupInfo: {
    flex: 1,
  },
  groupName: {
    color: colors.textMain,
    fontSize: 16,
    fontWeight: '600',
  },
  groupMeta: {
    color: colors.textMuted,
    fontSize: 12,
  },
  groupActions: {
    flexDirection: 'row',
    gap: 12,
  },
  iconButton: {
    padding: 4,
  },
  empty: {
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: 40,
  },
  input: {
    backgroundColor: 'rgba(0,0,0,0.3)',
    borderWidth: 1,
    borderColor: colors.glassBorder,
    borderRadius: 50,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: colors.textMain,
    marginBottom: 12,
  },
  label: {
    color: colors.textMuted,
    marginBottom: 8,
  },
  membersInputRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  memberRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: colors.glassBorder,
  },
  memberAddress: {
    color: colors.textMain,
    fontSize: 14,
  },
  creatorBadge: {
    color: colors.accent,
    fontSize: 12,
    fontWeight: 'bold',
  },
  addMemberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 12,
  },
});