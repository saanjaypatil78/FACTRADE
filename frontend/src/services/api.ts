import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:4000/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const fetchRewardsStats = async (wallet: string) => {
  const response = await api.get(`/rewards/user/${wallet}`);
  return {
    totalRewards: response.data.totalRewards || 0,
    currentAPY: 12.5,
    totalStaked: 0,
    userBalance: 0,
    pendingRewards: response.data.pendingRewards || 0,
  };
};

export const fetchStakingPools = async () => {
  const response = await api.get('/staking/pools');
  return response.data;
};

export const stakeTokens = async (wallet: string, poolId: string, amount: number, signature: string) => {
  const response = await api.post('/staking/stake', { wallet, poolId, amount, signature });
  return response.data;
};

export const claimRewards = async (wallet: string, signature: string) => {
  const response = await api.post('/rewards/claim', { wallet, signature });
  return response.data;
};

export const fetchProposals = async () => {
  const response = await api.get('/governance/proposals');
  return response.data;
};

export const castVote = async (wallet: string, proposalId: string, vote: 'yes' | 'no', signature: string) => {
  const response = await api.post('/governance/vote', { wallet, proposalId, vote, signature });
  return response.data;
};

export default api;
