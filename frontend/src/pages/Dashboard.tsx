import { FC, useEffect, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import StatsCard from '../components/StatsCard';
import RewardsChart from '../components/RewardsChart';
import { fetchRewardsStats } from '../services/api';

interface RewardsStats {
  totalRewards: number;
  currentAPY: number;
  totalStaked: number;
  userBalance: number;
  pendingRewards: number;
}

const Dashboard: FC = () => {
  const { publicKey, connected } = useWallet();
  const [stats, setStats] = useState<RewardsStats>({
    totalRewards: 0,
    currentAPY: 12.5,
    totalStaked: 0,
    userBalance: 0,
    pendingRewards: 0,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadStats = async () => {
      if (connected && publicKey) {
        try {
          const data = await fetchRewardsStats(publicKey.toBase58());
          setStats(data);
        } catch (error) {
          console.error('Failed to load stats:', error);
        } finally {
          setLoading(false);
        }
      } else {
        setLoading(false);
      }
    };

    loadStats();
    const interval = setInterval(loadStats, 30000);
    return () => clearInterval(interval);
  }, [connected, publicKey]);

  if (!connected) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
            Connect Your Wallet
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            Please connect your wallet to view your dashboard
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
          Dashboard
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          Track your rewards, staking positions, and protocol performance
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard
          title="Total Rewards"
          value={`${stats.totalRewards.toFixed(2)} FGDA`}
          change="+12.5%"
          trend="up"
          icon="💰"
          loading={loading}
        />
        <StatsCard
          title="Current APY"
          value={`${stats.currentAPY}%`}
          change="+0.5%"
          trend="up"
          icon="📈"
          loading={loading}
        />
        <StatsCard
          title="Total Staked"
          value={`${stats.totalStaked.toLocaleString()} FGDA`}
          change="+8.2%"
          trend="up"
          icon="🔒"
          loading={loading}
        />
        <StatsCard
          title="Pending Rewards"
          value={`${stats.pendingRewards.toFixed(4)} FGDA`}
          change="Live"
          trend="neutral"
          icon="⏳"
          loading={loading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
            Rewards History
          </h3>
          <RewardsChart />
        </div>

        <div className="card">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
            Quick Actions
          </h3>
          <div className="space-y-3">
            <button className="btn-primary w-full">
              Claim Rewards
            </button>
            <button className="btn-secondary w-full">
              Compound Rewards
            </button>
            <button className="btn-secondary w-full">
              Stake Tokens
            </button>
          </div>

          <div className="mt-6 p-4 bg-primary-50 dark:bg-primary-900/20 rounded-lg">
            <h4 className="text-sm font-semibold text-primary-900 dark:text-primary-100 mb-2">
              💡 Tip
            </h4>
            <p className="text-sm text-primary-700 dark:text-primary-300">
              Compound your rewards regularly to maximize your returns through the power of compounding!
            </p>
          </div>
        </div>
      </div>

      <div className="card">
        <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
          Lifecycle Phase
        </h3>
        <div className="flex items-center space-x-4">
          <div className="flex-1">
            <div className="flex justify-between mb-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Current Phase: Growth
              </span>
              <span className="text-sm text-gray-500 dark:text-gray-400">
                60% Complete
              </span>
            </div>
            <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
              <div className="h-full bg-primary-600 rounded-full" style={{ width: '60%' }}></div>
            </div>
            <div className="flex justify-between mt-2 text-xs text-gray-500 dark:text-gray-400">
              <span>Seeding</span>
              <span className="font-semibold text-primary-600">Growth</span>
              <span>Scaling</span>
              <span>Maturity</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
