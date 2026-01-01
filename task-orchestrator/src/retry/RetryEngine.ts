import { logger } from '../utils/logger.js';

export enum RetryStrategy {
  EXPONENTIAL_BACKOFF = 'EXPONENTIAL_BACKOFF',
  LINEAR_BACKOFF = 'LINEAR_BACKOFF',
  IMMEDIATE_RETRY = 'IMMEDIATE_RETRY',
  CIRCUIT_BREAKER = 'CIRCUIT_BREAKER',
  ALTERNATIVE_APPROACH = 'ALTERNATIVE_APPROACH',
}

interface RetryConfig {
  maxAttempts: number;
  baseDelay: number;
  maxDelay: number;
  jitterFactor: number;
}

interface RetryResult {
  success: boolean;
  attempts: number;
  strategy: RetryStrategy;
  error?: Error;
}

export class RetryEngine {
  private readonly defaultConfig: RetryConfig = {
    maxAttempts: 3,
    baseDelay: 1000,
    maxDelay: 30000,
    jitterFactor: 0.2,
  };

  private circuitBreakers: Map<string, { failures: number; lastFailure: number }> = new Map();
  private readonly circuitBreakerThreshold = 5;
  private readonly circuitBreakerTimeout = 60000;

  async executeWithRetry<T>(
    taskId: string,
    operation: () => Promise<T>,
    strategies: RetryStrategy[] = [RetryStrategy.EXPONENTIAL_BACKOFF],
    config: Partial<RetryConfig> = {}
  ): Promise<RetryResult> {
    const finalConfig = { ...this.defaultConfig, ...config };
    let lastError: Error | undefined;

    for (const strategy of strategies) {
      logger.info(`Attempting task ${taskId} with strategy ${strategy}`);

      try {
        const result = await this.executeStrategy(
          taskId,
          operation,
          strategy,
          finalConfig
        );

        if (result.success) {
          this.resetCircuitBreaker(taskId);
          return result;
        }

        lastError = result.error;
      } catch (error) {
        lastError = error as Error;
        logger.error(`Strategy ${strategy} failed for task ${taskId}:`, error);
      }
    }

    this.recordFailure(taskId);

    return {
      success: false,
      attempts: finalConfig.maxAttempts * strategies.length,
      strategy: strategies[strategies.length - 1],
      error: lastError,
    };
  }

  private async executeStrategy<T>(
    taskId: string,
    operation: () => Promise<T>,
    strategy: RetryStrategy,
    config: RetryConfig
  ): Promise<RetryResult> {
    let attempts = 0;
    let lastError: Error | undefined;

    for (let i = 0; i < config.maxAttempts; i++) {
      attempts++;

      if (this.isCircuitBreakerOpen(taskId)) {
        logger.warn(`Circuit breaker open for task ${taskId}`);
        return {
          success: false,
          attempts,
          strategy,
          error: new Error('Circuit breaker open'),
        };
      }

      try {
        await operation();
        
        return {
          success: true,
          attempts,
          strategy,
        };
      } catch (error) {
        lastError = error as Error;
        logger.warn(`Attempt ${attempts} failed for task ${taskId}:`, error);

        if (i < config.maxAttempts - 1) {
          const delay = this.calculateDelay(strategy, i, config);
          logger.info(`Waiting ${delay}ms before retry...`);
          await this.sleep(delay);
        }
      }
    }

    return {
      success: false,
      attempts,
      strategy,
      error: lastError,
    };
  }

  private calculateDelay(
    strategy: RetryStrategy,
    attempt: number,
    config: RetryConfig
  ): number {
    let delay: number;

    switch (strategy) {
      case RetryStrategy.EXPONENTIAL_BACKOFF:
        delay = Math.min(
          config.baseDelay * Math.pow(2, attempt),
          config.maxDelay
        );
        break;

      case RetryStrategy.LINEAR_BACKOFF:
        delay = Math.min(
          config.baseDelay * (attempt + 1),
          config.maxDelay
        );
        break;

      case RetryStrategy.IMMEDIATE_RETRY:
        delay = 0;
        break;

      default:
        delay = config.baseDelay;
    }

    const jitter = delay * config.jitterFactor * (Math.random() - 0.5);
    return Math.max(0, delay + jitter);
  }

  private isCircuitBreakerOpen(taskId: string): boolean {
    const breaker = this.circuitBreakers.get(taskId);
    
    if (!breaker) return false;

    if (breaker.failures >= this.circuitBreakerThreshold) {
      const timeSinceLastFailure = Date.now() - breaker.lastFailure;
      
      if (timeSinceLastFailure < this.circuitBreakerTimeout) {
        return true;
      } else {
        this.resetCircuitBreaker(taskId);
        return false;
      }
    }

    return false;
  }

  private recordFailure(taskId: string): void {
    const breaker = this.circuitBreakers.get(taskId) || { failures: 0, lastFailure: 0 };
    breaker.failures++;
    breaker.lastFailure = Date.now();
    this.circuitBreakers.set(taskId, breaker);

    if (breaker.failures >= this.circuitBreakerThreshold) {
      logger.warn(`Circuit breaker triggered for task ${taskId}`);
    }
  }

  private resetCircuitBreaker(taskId: string): void {
    this.circuitBreakers.delete(taskId);
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  getMultiApproachStrategies(errorType: string): RetryStrategy[] {
    switch (errorType) {
      case 'NETWORK_ERROR':
        return [
          RetryStrategy.EXPONENTIAL_BACKOFF,
          RetryStrategy.LINEAR_BACKOFF,
          RetryStrategy.CIRCUIT_BREAKER,
        ];

      case 'RATE_LIMIT':
        return [
          RetryStrategy.LINEAR_BACKOFF,
          RetryStrategy.EXPONENTIAL_BACKOFF,
        ];

      case 'TEMPORARY_FAILURE':
        return [
          RetryStrategy.IMMEDIATE_RETRY,
          RetryStrategy.EXPONENTIAL_BACKOFF,
        ];

      default:
        return [
          RetryStrategy.EXPONENTIAL_BACKOFF,
          RetryStrategy.ALTERNATIVE_APPROACH,
        ];
    }
  }
}
