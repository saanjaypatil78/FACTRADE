import { Router } from 'express';
import { logger } from '../utils/logger.js';

const router = Router();

const mockTasks = new Map();

router.get('/', async (req, res) => {
  try {
    const tasks = Array.from(mockTasks.values());
    res.json(tasks);
  } catch (error) {
    logger.error('Failed to fetch tasks:', error);
    res.status(500).json({ error: 'Failed to fetch tasks' });
  }
});

router.post('/', async (req, res) => {
  try {
    const task = {
      id: `task_${Date.now()}`,
      ...req.body,
      status: 'pending',
      createdAt: new Date().toISOString(),
    };
    
    mockTasks.set(task.id, task);
    logger.info(`Task created: ${task.id}`);
    
    res.status(201).json(task);
  } catch (error) {
    logger.error('Failed to create task:', error);
    res.status(500).json({ error: 'Failed to create task' });
  }
});

router.get('/:id', async (req, res) => {
  try {
    const task = mockTasks.get(req.params.id);
    
    if (!task) {
      return res.status(404).json({ error: 'Task not found' });
    }
    
    res.json(task);
  } catch (error) {
    logger.error('Failed to fetch task:', error);
    res.status(500).json({ error: 'Failed to fetch task' });
  }
});

router.patch('/:id', async (req, res) => {
  try {
    const task = mockTasks.get(req.params.id);
    
    if (!task) {
      return res.status(404).json({ error: 'Task not found' });
    }
    
    const updatedTask = {
      ...task,
      ...req.body,
      updatedAt: new Date().toISOString(),
    };
    
    mockTasks.set(req.params.id, updatedTask);
    logger.info(`Task updated: ${req.params.id}`);
    
    res.json(updatedTask);
  } catch (error) {
    logger.error('Failed to update task:', error);
    res.status(500).json({ error: 'Failed to update task' });
  }
});

export default router;
