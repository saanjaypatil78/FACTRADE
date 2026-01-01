import express from 'express';
import cron from 'node-cron';
import { logger } from './utils/logger.js';
import { PhaseManager } from './phases/PhaseManager.js';
import { RetryEngine } from './retry/RetryEngine.js';
import { EscalationManager } from './escalation/EscalationManager.js';
import { TaskQueue } from './core/TaskQueue.js';

const app = express();
const PORT = process.env.ORCHESTRATOR_PORT || 5000;

app.use(express.json());

const phaseManager = new PhaseManager();
const retryEngine = new RetryEngine();
const escalationManager = new EscalationManager();
const taskQueue = new TaskQueue(retryEngine, escalationManager);

app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    phase: phaseManager.getCurrentPhase(),
    queueSize: taskQueue.size(),
    timestamp: new Date().toISOString(),
  });
});

app.get('/status', (req, res) => {
  res.json({
    currentPhase: phaseManager.getCurrentPhase(),
    phaseProgress: phaseManager.getPhaseProgress(),
    activeTasks: taskQueue.getActiveTasks(),
    failedTasks: taskQueue.getFailedTasks(),
    statistics: taskQueue.getStatistics(),
  });
});

app.post('/tasks', async (req, res) => {
  try {
    const task = await taskQueue.addTask(req.body);
    res.status(201).json(task);
  } catch (error) {
    logger.error('Failed to add task:', error);
    res.status(500).json({ error: 'Failed to add task' });
  }
});

app.get('/tasks/:id', (req, res) => {
  const task = taskQueue.getTask(req.params.id);
  if (task) {
    res.json(task);
  } else {
    res.status(404).json({ error: 'Task not found' });
  }
});

cron.schedule('*/5 * * * *', async () => {
  logger.info('Running phase transition check...');
  await phaseManager.checkTransition();
});

cron.schedule('* * * * *', async () => {
  logger.info('Processing task queue...');
  await taskQueue.processQueue();
});

cron.schedule('*/15 * * * *', () => {
  logger.info('Running health checks...');
  escalationManager.performHealthChecks();
});

app.listen(PORT, () => {
  logger.info(`🤖 FACTRADE Task Orchestrator running on port ${PORT}`);
  logger.info(`Initial Phase: ${phaseManager.getCurrentPhase()}`);
  
  taskQueue.start();
  logger.info('Task queue processing started');
});

export default app;
