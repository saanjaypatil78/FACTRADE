import { logger } from '../utils/logger.js';
import { RetryEngine, RetryStrategy } from '../retry/RetryEngine.js';
import { EscalationManager, EscalationLevel } from '../escalation/EscalationManager.js';

export enum TaskStatus {
  PENDING = 'PENDING',
  RUNNING = 'RUNNING',
  COMPLETED = 'COMPLETED',
  FAILED = 'FAILED',
  ESCALATED = 'ESCALATED',
}

export interface Task {
  id: string;
  type: string;
  status: TaskStatus;
  priority: number;
  attempts: number;
  maxAttempts: number;
  createdAt: Date;
  updatedAt: Date;
  error?: string;
  metadata: Record<string, unknown>;
}

export class TaskQueue {
  private tasks: Map<string, Task> = new Map();
  private queue: Task[] = [];
  private processing = false;

  constructor(
    private retryEngine: RetryEngine,
    private escalationManager: EscalationManager
  ) {}

  async addTask(taskData: Partial<Task>): Promise<Task> {
    const task: Task = {
      id: this.generateTaskId(),
      type: taskData.type || 'generic',
      status: TaskStatus.PENDING,
      priority: taskData.priority || 5,
      attempts: 0,
      maxAttempts: taskData.maxAttempts || 3,
      createdAt: new Date(),
      updatedAt: new Date(),
      metadata: taskData.metadata || {},
    };

    this.tasks.set(task.id, task);
    this.queue.push(task);
    this.sortQueue();

    logger.info(`Task ${task.id} added to queue`);
    return task;
  }

  async processQueue(): Promise<void> {
    if (this.processing || this.queue.length === 0) {
      return;
    }

    this.processing = true;

    try {
      const task = this.queue.shift();
      if (task) {
        await this.processTask(task);
      }
    } finally {
      this.processing = false;
    }
  }

  private async processTask(task: Task): Promise<void> {
    task.status = TaskStatus.RUNNING;
    task.attempts++;
    task.updatedAt = new Date();

    logger.info(`Processing task ${task.id} (attempt ${task.attempts}/${task.maxAttempts})`);

    const strategies = this.retryEngine.getMultiApproachStrategies(task.type);
    
    const result = await this.retryEngine.executeWithRetry(
      task.id,
      async () => this.executeTask(task),
      strategies
    );

    if (result.success) {
      task.status = TaskStatus.COMPLETED;
      logger.info(`Task ${task.id} completed successfully`);
    } else {
      if (task.attempts >= task.maxAttempts) {
        task.status = TaskStatus.FAILED;
        task.error = result.error?.message;

        const escalationLevel = this.escalationManager.checkEscalation(
          task.id,
          task.attempts
        );

        if (escalationLevel === EscalationLevel.HUMAN_INTERVENTION) {
          task.status = TaskStatus.ESCALATED;
          await this.escalationManager.escalate(
            task.id,
            escalationLevel,
            `Task failed after ${task.attempts} attempts`,
            { task, error: result.error }
          );
        }
      } else {
        task.status = TaskStatus.PENDING;
        this.queue.push(task);
        this.sortQueue();
      }
    }

    task.updatedAt = new Date();
  }

  private async executeTask(task: Task): Promise<void> {
    logger.info(`Executing task ${task.id} of type ${task.type}`);
    
    await new Promise(resolve => setTimeout(resolve, 100));
    
    logger.info(`Task ${task.id} execution completed`);
  }

  getTask(id: string): Task | undefined {
    return this.tasks.get(id);
  }

  getActiveTasks(): Task[] {
    return Array.from(this.tasks.values()).filter(
      t => t.status === TaskStatus.RUNNING || t.status === TaskStatus.PENDING
    );
  }

  getFailedTasks(): Task[] {
    return Array.from(this.tasks.values()).filter(
      t => t.status === TaskStatus.FAILED || t.status === TaskStatus.ESCALATED
    );
  }

  size(): number {
    return this.queue.length;
  }

  start(): void {
    logger.info('Task queue started');
  }

  getStatistics() {
    const allTasks = Array.from(this.tasks.values());
    return {
      total: allTasks.length,
      pending: allTasks.filter(t => t.status === TaskStatus.PENDING).length,
      running: allTasks.filter(t => t.status === TaskStatus.RUNNING).length,
      completed: allTasks.filter(t => t.status === TaskStatus.COMPLETED).length,
      failed: allTasks.filter(t => t.status === TaskStatus.FAILED).length,
      escalated: allTasks.filter(t => t.status === TaskStatus.ESCALATED).length,
    };
  }

  private sortQueue(): void {
    this.queue.sort((a, b) => b.priority - a.priority);
  }

  private generateTaskId(): string {
    return `task_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }
}
