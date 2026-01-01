import { FC, useEffect, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { fetchStakingPools } from '../services/api';

interface StakingPool {
  id: string;
  name: string;
  apy: number;
  lockPeriod: number;
  totalStaked: number;
  rewardMultiplier: number;
}

const Staking: FC = () => {
  const { connected } = useWallet();
  const [pools, setPools] = useState<StakingPool[]>([]);
  const [loading, setLoading] = useState(true);
  const [stakeAmount, setStakeAmount] = useState('');

  useEffect(() => {
    const loadPools = async () => {
      try {
        const data = await fetchStakingPools();
        setPools(data);
      } catch (error) {
        console.error('Failed to load pools:', error);
      } finally {
        setLoading(false);
      }
    };

    loadPools();
  }, []);

  if (!connected) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
            Connect Your Wallet
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            Please connect your wallet to access staking
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
          Staking
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          Stake your tokens to earn rewards
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {loading ? (
          <>
            {[1, 2, 3].map(i => (
              <div key={i} className="card animate-pulse">
                <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-1/2 mb-4"></div>
                <div className="space-y-2">
                  <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded"></div>
                  <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded"></div>
                </div>
              </div>
            ))}
          </>
        ) : (
          pools.map(pool => (
            <div key={pool.id} className="card hover:shadow-xl transition-shadow duration-200">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xl font-bold text-gray-900 dark:text-white">
                  {pool.name}
                </h3>
                <span className="text-2xl">🔒</span>
              </div>
              
              <div className="space-y-3 mb-6">
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-400">APY</span>
                  <span className="font-bold text-primary-600 dark:text-primary-400">
                    {pool.apy}%
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-400">Lock Period</span>
                  <span className="font-semibold text-gray-900 dark:text-white">
                    {pool.lockPeriod} days
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-400">Total Staked</span>
                  <span className="font-semibold text-gray-900 dark:text-white">
                    {pool.totalStaked.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-400">Multiplier</span>
                  <span className="font-semibold text-gray-900 dark:text-white">
                    {pool.rewardMultiplier}x
                  </span>
                </div>
              </div>

              <input
                type="number"
                placeholder="Amount to stake"
                value={stakeAmount}
                onChange={(e) => setStakeAmount(e.target.value)}
                className="input mb-3"
              />
              
              <button className="btn-primary w-full">
                Stake
              </button>
            </div>
          ))
        )}
      </div>

      <div className="card">
        <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
          Your Staking Positions
        </h3>
        <p className="text-gray-600 dark:text-gray-400">
          No active positions
        </p>
      </div>
    </div>
  );
};

export default Staking;
