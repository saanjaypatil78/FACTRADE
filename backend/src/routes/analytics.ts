import { Router } from 'express';
import { logger } from '../utils/logger.js';

const router = Router();

router.get('/overview', async (req, res) => {
  try {
    const overview = {
      totalValueLocked: 12500000,
      totalUsers: 4523,
      totalTransactions: 89456,
      averageAPY: 12.5,
      last24hVolume: 450000,
      last24hTransactions: 1234,
    };
    res.json(overview);
  } catch (error) {
    logger.error('Failed to fetch analytics:', error);
    res.status(500).json({ error: 'Failed to fetch analytics' });
  }
});

router.get('/chart/:metric', async (req, res) => {
  try {
    const { metric } = req.params;
    const { period = '7d' } = req.query;
    
    const dataPoints = Array.from({ length: 30 }, (_, i) => ({
      timestamp: new Date(Date.now() - (29 - i) * 24 * 60 * 60 * 1000).toISOString(),
      value: Math.random() * 10000 + 5000,
    }));
    
    res.json({
      metric,
      period,
      data: dataPoints,
    });
  } catch (error) {
    logger.error('Failed to fetch chart data:', error);
    res.status(500).json({ error: 'Failed to fetch chart data' });
  }
});

export default router;
