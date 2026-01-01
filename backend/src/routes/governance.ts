import { Router } from 'express';
import { logger } from '../utils/logger.js';

const router = Router();

router.get('/proposals', async (req, res) => {
  try {
    const proposals = [
      {
        id: 'prop_1',
        title: 'Increase Staking Rewards',
        description: 'Proposal to increase staking rewards by 5%',
        status: 'active',
        yesVotes: 75000,
        noVotes: 25000,
        startTime: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
        endTime: new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString(),
      },
    ];
    res.json(proposals);
  } catch (error) {
    logger.error('Failed to fetch proposals:', error);
    res.status(500).json({ error: 'Failed to fetch proposals' });
  }
});

router.post('/vote', async (req, res) => {
  try {
    const { wallet, proposalId, vote, signature } = req.body;
    
    logger.info(`Vote cast: ${vote} on ${proposalId} by ${wallet}`);
    
    const result = {
      success: true,
      txSignature: signature || 'mock_signature',
    };
    
    res.json(result);
  } catch (error) {
    logger.error('Failed to cast vote:', error);
    res.status(500).json({ error: 'Failed to cast vote' });
  }
});

export default router;
