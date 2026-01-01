import { FC, useEffect, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { fetchProposals } from '../services/api';

interface Proposal {
  id: string;
  title: string;
  description: string;
  status: string;
  yesVotes: number;
  noVotes: number;
  startTime: string;
  endTime: string;
}

const Governance: FC = () => {
  const { connected } = useWallet();
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadProposals = async () => {
      try {
        const data = await fetchProposals();
        setProposals(data);
      } catch (error) {
        console.error('Failed to load proposals:', error);
      } finally {
        setLoading(false);
      }
    };

    loadProposals();
  }, []);

  if (!connected) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
            Connect Your Wallet
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            Please connect your wallet to participate in governance
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
          Governance
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          Vote on proposals to shape the future of FACTRADE
        </p>
      </div>

      <div className="space-y-6">
        {loading ? (
          <div className="card animate-pulse">
            <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-3/4 mb-4"></div>
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-full mb-2"></div>
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-2/3"></div>
          </div>
        ) : proposals.length === 0 ? (
          <div className="card">
            <p className="text-gray-600 dark:text-gray-400">
              No active proposals at this time
            </p>
          </div>
        ) : (
          proposals.map(proposal => {
            const totalVotes = proposal.yesVotes + proposal.noVotes;
            const yesPercentage = totalVotes > 0 ? (proposal.yesVotes / totalVotes) * 100 : 0;
            const noPercentage = totalVotes > 0 ? (proposal.noVotes / totalVotes) * 100 : 0;

            return (
              <div key={proposal.id} className="card">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-2">
                      {proposal.title}
                    </h3>
                    <p className="text-gray-600 dark:text-gray-400">
                      {proposal.description}
                    </p>
                  </div>
                  <span className={`px-3 py-1 rounded-full text-sm font-semibold ${
                    proposal.status === 'active'
                      ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                      : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
                  }`}>
                    {proposal.status}
                  </span>
                </div>

                <div className="space-y-3 mb-6">
                  <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-gray-600 dark:text-gray-400">Yes</span>
                      <span className="font-semibold text-green-600 dark:text-green-400">
                        {yesPercentage.toFixed(1)}% ({proposal.yesVotes.toLocaleString()})
                      </span>
                    </div>
                    <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-green-500 rounded-full"
                        style={{ width: `${yesPercentage}%` }}
                      ></div>
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-gray-600 dark:text-gray-400">No</span>
                      <span className="font-semibold text-red-600 dark:text-red-400">
                        {noPercentage.toFixed(1)}% ({proposal.noVotes.toLocaleString()})
                      </span>
                    </div>
                    <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-red-500 rounded-full"
                        style={{ width: `${noPercentage}%` }}
                      ></div>
                    </div>
                  </div>
                </div>

                <div className="flex space-x-3">
                  <button className="btn-primary flex-1">
                    Vote Yes
                  </button>
                  <button className="btn-secondary flex-1">
                    Vote No
                  </button>
                </div>

                <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400">
                  <div className="flex justify-between">
                    <span>Ends: {new Date(proposal.endTime).toLocaleString()}</span>
                    <span>Total Votes: {totalVotes.toLocaleString()}</span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default Governance;
