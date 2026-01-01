import { config as dotenvConfig } from 'dotenv';

dotenvConfig();

export const config = {
  nodeEnv: process.env.NODE_ENV || 'development',
  port: parseInt(process.env.PORT || '4000', 10),
  
  solana: {
    network: process.env.SOLANA_NETWORK || 'devnet',
    rpcUrl: process.env.SOLANA_RPC_URL || 'https://api.devnet.solana.com',
    rewardsProgramId: process.env.REWARDS_PROGRAM_ID || '',
    stakingProgramId: process.env.STAKING_PROGRAM_ID || '',
    governanceProgramId: process.env.GOVERNANCE_PROGRAM_ID || '',
  },

  database: {
    url: process.env.DATABASE_URL || 'postgresql://localhost:5432/factrade',
  },

  redis: {
    url: process.env.REDIS_URL || 'redis://localhost:6379',
  },

  rateLimit: {
    windowMs: 15 * 60 * 1000,
    max: 100,
  },
};
