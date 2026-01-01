import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import compression from 'compression';
import { config } from './config/env.js';
import { logger } from './utils/logger.js';
import { errorHandler } from './middleware/errorHandler.js';
import { rateLimiter } from './middleware/rateLimiter.js';

import rewardsRouter from './routes/rewards.js';
import stakingRouter from './routes/staking.js';
import tasksRouter from './routes/tasks.js';
import governanceRouter from './routes/governance.js';
import analyticsRouter from './routes/analytics.js';

const app = express();

app.use(helmet());
app.use(cors());
app.use(compression());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(rateLimiter);

app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    uptime: process.uptime(),
  });
});

app.use('/api/v1/rewards', rewardsRouter);
app.use('/api/v1/staking', stakingRouter);
app.use('/api/v1/tasks', tasksRouter);
app.use('/api/v1/governance', governanceRouter);
app.use('/api/v1/analytics', analyticsRouter);

app.use(errorHandler);

const PORT = config.port || 4000;

app.listen(PORT, () => {
  logger.info(`🚀 FACTRADE Backend API running on port ${PORT}`);
  logger.info(`Environment: ${config.nodeEnv}`);
  logger.info(`Solana Network: ${config.solana.network}`);
});

export default app;
