import { Router } from 'express';
import { logger } from '../utils/logger.js';

const router = Router();

router.get('/stats', async (req, res) => {
  try {
    const stats = {
      totalRewardsDistributed: 1234567.89,
      currentAPY: 12.5,
      totalStaked: 9876543.21,
      activeUsers: 4523,
    };
    res.json(stats);
  } catch (error) {
    logger.error('Failed to fetch rewards stats:', error);
    res.status(500).json({ error: 'Failed to fetch stats' });
  }
});

router.get('/user/:wallet', async (req, res) => {
  try {
    const { wallet } = req.params;
    const userRewards = {
      wallet,
      totalRewards: 1234.56,
      pendingRewards: 12.34,
      claimedRewards: 1222.22,
      lastClaimTime: new Date().toISOString(),
    };
    res.json(userRewards);
  } catch (error) {
    logger.error('Failed to fetch user rewards:', error);
    res.status(500).json({ error: 'Failed to fetch user rewards' });
  }
});

router.post('/claim', async (req, res) => {
  try {
    const { wallet, signature } = req.body;
    
    logger.info(`Processing rewards claim for ${wallet}`);
    
    const result = {
      success: true,
      amount: 12.34,
      txSignature: signature || 'mock_signature',
    };
    
    res.json(result);
  } catch (error) {
    logger.error('Failed to claim rewards:', error);
    res.status(500).json({ error: 'Failed to claim rewards' });
  }
});

export default router;
