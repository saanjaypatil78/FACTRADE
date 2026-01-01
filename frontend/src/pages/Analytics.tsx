import { FC } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';

const Analytics: FC = () => {
  const { connected } = useWallet();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
          Analytics
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          Protocol metrics and performance analytics
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div className="card">
          <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">
            Total Value Locked
          </h3>
          <p className="text-3xl font-bold text-gray-900 dark:text-white">
            $12.5M
          </p>
          <p className="text-sm text-green-600 dark:text-green-400 mt-1">
            +15.3% this month
          </p>
        </div>

        <div className="card">
          <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">
            Total Users
          </h3>
          <p className="text-3xl font-bold text-gray-900 dark:text-white">
            4,523
          </p>
          <p className="text-sm text-green-600 dark:text-green-400 mt-1">
            +234 this week
          </p>
        </div>

        <div className="card">
          <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">
            Total Transactions
          </h3>
          <p className="text-3xl font-bold text-gray-900 dark:text-white">
            89,456
          </p>
          <p className="text-sm text-green-600 dark:text-green-400 mt-1">
            +1,234 today
          </p>
        </div>
      </div>

      <div className="card">
        <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
          Protocol Performance
        </h3>
        <div className="h-64 flex items-center justify-center text-gray-500 dark:text-gray-400">
          Chart Placeholder - Historical TVL
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
            Top Stakers
          </h3>
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map(i => (
              <div key={i} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                <div className="flex items-center space-x-3">
                  <span className="text-lg font-semibold text-gray-500 dark:text-gray-400">
                    #{i}
                  </span>
                  <span className="text-sm font-mono text-gray-900 dark:text-white">
                    {`${i}abc...xyz`}
                  </span>
                </div>
                <span className="text-sm font-semibold text-primary-600 dark:text-primary-400">
                  {(Math.random() * 100000).toFixed(0)} FGDA
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
            Recent Transactions
          </h3>
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map(i => (
              <div key={i} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                <div>
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">
                    {i % 2 === 0 ? 'Stake' : 'Claim Rewards'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {new Date(Date.now() - i * 5 * 60 * 1000).toLocaleTimeString()}
                  </p>
                </div>
                <span className="text-sm font-semibold text-gray-900 dark:text-white">
                  {(Math.random() * 1000).toFixed(2)} FGDA
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Analytics;
