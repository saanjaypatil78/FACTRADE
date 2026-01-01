import { Router } from 'express';
import { logger } from '../utils/logger.js';

const router = Router();

router.get('/pools', async (req, res) => {
  try {
    const pools = [
      {
        id: 'pool_7day',
        name: '7-Day Staking',
        apy: 10.0,
        lockPeriod: 7,
        totalStaked: 1000000,
        rewardMultiplier: 1.0,
      },
      {
        id: 'pool_14day',
        name: '14-Day Staking',
        apy: 15.0,
        lockPeriod: 14,
        totalStaked: 2500000,
        rewardMultiplier: 1.5,
      },
      {
        id: 'pool_30day',
        name: '30-Day Staking',
        apy: 25.0,
        lockPeriod: 30,
        totalStaked: 5000000,
        rewardMultiplier: 2.5,
      },
    ];
    res.json(pools);
  } catch (error) {
    logger.error('Failed to fetch staking pools:', error);
    res.status(500).json({ error: 'Failed to fetch pools' });
  }
});

router.get('/positions/:wallet', async (req, res) => {
  try {
    const { wallet } = req.params;
    const positions = [
      {
        id: 'pos_1',
        pool: 'pool_30day',
        amount: 10000,
        startDate: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
        endDate: new Date(Date.now() + 20 * 24 * 60 * 60 * 1000).toISOString(),
        rewards: 123.45,
        isUnbonding: false,
      },
    ];
    res.json(positions);
  } catch (error) {
    logger.error('Failed to fetch positions:', error);
    res.status(500).json({ error: 'Failed to fetch positions' });
  }
});

router.post('/stake', async (req, res) => {
  try {
    const { wallet, poolId, amount, signature } = req.body;
    
    logger.info(`Processing stake: ${amount} tokens to ${poolId} for ${wallet}`);
    
    const result = {
      success: true,
      positionId: `pos_${Date.now()}`,
      txSignature: signature || 'mock_signature',
    };
    
    res.json(result);
  } catch (error) {
    logger.error('Failed to stake:', error);
    res.status(500).json({ error: 'Failed to stake' });
  }
});

router.post('/unstake', async (req, res) => {
  try {
    const { wallet, positionId, signature } = req.body;
    
    logger.info(`Processing unstake for position ${positionId}`);
    
    const result = {
      success: true,
      txSignature: signature || 'mock_signature',
    };
    
    res.json(result);
  } catch (error) {
    logger.error('Failed to unstake:', error);
    res.status(500).json({ error: 'Failed to unstake' });
  }
});

export default router;
