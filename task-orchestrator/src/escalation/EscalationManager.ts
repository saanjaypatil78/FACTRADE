import { logger } from '../utils/logger.js';

export enum EscalationLevel {
  INFO = 'INFO',
  WARNING = 'WARNING',
  ERROR = 'ERROR',
  CRITICAL = 'CRITICAL',
  HUMAN_INTERVENTION = 'HUMAN_INTERVENTION',
}

interface EscalationEvent {
  id: string;
  taskId: string;
  level: EscalationLevel;
  message: string;
  timestamp: Date;
  metadata: Record<string, unknown>;
}

export class EscalationManager {
  private escalationThreshold = 5;
  private escalationHistory: EscalationEvent[] = [];
  private taskFailureCounts: Map<string, number> = new Map();

  async escalate(
    taskId: string,
    level: EscalationLevel,
    message: string,
    metadata: Record<string, unknown> = {}
  ): Promise<void> {
    const event: EscalationEvent = {
      id: this.generateEventId(),
      taskId,
      level,
      message,
      timestamp: new Date(),
      metadata,
    };

    this.escalationHistory.push(event);
    
    logger.warn(`🚨 Escalation [${level}]: ${message}`, { taskId, metadata });

    switch (level) {
      case EscalationLevel.INFO:
        this.handleInfo(event);
        break;
      case EscalationLevel.WARNING:
        this.handleWarning(event);
        break;
      case EscalationLevel.ERROR:
        this.handleError(event);
        break;
      case EscalationLevel.CRITICAL:
        this.handleCritical(event);
        break;
      case EscalationLevel.HUMAN_INTERVENTION:
        this.handleHumanIntervention(event);
        break;
    }
  }

  checkEscalation(taskId: string, failures: number): EscalationLevel {
    this.taskFailureCounts.set(taskId, failures);

    if (failures >= this.escalationThreshold * 2) {
      return EscalationLevel.HUMAN_INTERVENTION;
    } else if (failures >= this.escalationThreshold) {
      return EscalationLevel.CRITICAL;
    } else if (failures >= this.escalationThreshold / 2) {
      return EscalationLevel.ERROR;
    } else if (failures > 0) {
      return EscalationLevel.WARNING;
    }

    return EscalationLevel.INFO;
  }

  async performHealthChecks(): Promise<void> {
    logger.info('Performing system health checks...');

    const recentFailures = this.getRecentFailures(15 * 60 * 1000);
    
    if (recentFailures.length > 10) {
      await this.escalate(
        'system',
        EscalationLevel.WARNING,
        `High number of recent failures: ${recentFailures.length}`,
        { count: recentFailures.length }
      );
    }

    const criticalEvents = this.escalationHistory.filter(
      e => e.level === EscalationLevel.CRITICAL || e.level === EscalationLevel.HUMAN_INTERVENTION
    );

    if (criticalEvents.length > 0) {
      logger.warn(`${criticalEvents.length} critical events requiring attention`);
    }
  }

  getEscalationHistory(limit = 100): EscalationEvent[] {
    return this.escalationHistory.slice(-limit);
  }

  private handleInfo(event: EscalationEvent): void {
    logger.info(`Info escalation: ${event.message}`);
  }

  private handleWarning(event: EscalationEvent): void {
    logger.warn(`Warning escalation: ${event.message}`);
  }

  private handleError(event: EscalationEvent): void {
    logger.error(`Error escalation: ${event.message}`);
    this.notifyOperations(event);
  }

  private handleCritical(event: EscalationEvent): void {
    logger.error(`CRITICAL escalation: ${event.message}`);
    this.notifyOperations(event);
    this.triggerAlerts(event);
  }

  private handleHumanIntervention(event: EscalationEvent): void {
    logger.error(`🆘 HUMAN INTERVENTION REQUIRED: ${event.message}`);
    this.notifyOperations(event);
    this.triggerAlerts(event);
    this.createTicket(event);
  }

  private notifyOperations(event: EscalationEvent): void {
    logger.info(`Notifying operations team about ${event.level} event`);
  }

  private triggerAlerts(event: EscalationEvent): void {
    logger.info(`Triggering alerts for ${event.level} event`);
  }

  private createTicket(event: EscalationEvent): void {
    logger.info(`Creating support ticket for event ${event.id}`);
  }

  private getRecentFailures(windowMs: number): EscalationEvent[] {
    const cutoff = Date.now() - windowMs;
    return this.escalationHistory.filter(
      e => e.timestamp.getTime() > cutoff &&
           (e.level === EscalationLevel.ERROR ||
            e.level === EscalationLevel.CRITICAL ||
            e.level === EscalationLevel.HUMAN_INTERVENTION)
    );
  }

  private generateEventId(): string {
    return `evt_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }
}
