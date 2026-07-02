import { API_BASE_URL } from '../config/constants';

const api = async (endpoint, options = {}) => {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.error || `HTTP ${res.status}`);
  }
  return res.json();
};

export const getContacts = () => api('/get_contacts');
export const addContact = (name, address) => api('/add_contact', { method: 'POST', body: JSON.stringify({ name, address }) });
export const deleteContact = (address) => api('/delete_contact', { method: 'POST', body: JSON.stringify({ address }) });
export const editContact = (address, name) => api('/edit_contact', { method: 'POST', body: JSON.stringify({ address, name }) });

export const getConversations = () => api('/get_conversations');
export const getConversation = (withAddress, beforeId = null) => {
  let url = `/get_conversation?with=${withAddress}`;
  if (beforeId) url += `&before_id=${beforeId}`;
  return api(url);
};
export const sendMessage = (payload) => api('/send_message', { method: 'POST', body: JSON.stringify(payload) });

export const getGroups = () => api('/get_groups');
export const createGroup = (name, members) => api('/create_group', { method: 'POST', body: JSON.stringify({ name, members }) });
export const renameGroup = (groupId, name) => api('/rename_group', { method: 'POST', body: JSON.stringify({ group_id: groupId, name }) });
export const addGroupMember = (groupId, address) => api('/add_group_member', { method: 'POST', body: JSON.stringify({ group_id: groupId, address }) });
export const removeGroupMember = (groupId, address) => api('/remove_group_member', { method: 'POST', body: JSON.stringify({ group_id: groupId, address }) });
export const deleteGroup = (groupId) => api('/delete_group', { method: 'POST', body: JSON.stringify({ group_id: groupId }) });

export const getBalance = () => api('/wallet/balance');
export const getGlobalStats = () => api('/wallet/global-stats');
export const getTransactions = () => api('/wallet/transactions');
export const stake = (amount) => api('/wallet/stake', { method: 'POST', body: JSON.stringify({ amount }) });
export const unstake = () => api('/wallet/unstake', { method: 'POST' });
export const sendCoins = (recipient, amount) => api('/wallet/send', { method: 'POST', body: JSON.stringify({ recipient, amount }) });
export const getStakingInfo = () => api('/wallet/staking/info');
export const getConfig = () => api('/wallet/config');
export const getPublicKey = (address) => api(`/get_public_key/${address}`);