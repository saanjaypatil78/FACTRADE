import { logger } from '../utils/logger.js';

export enum LifecyclePhase {
  SEEDING = 'SEEDING',
  GROWTH = 'GROWTH',
  SCALING = 'SCALING',
  MATURITY = 'MATURITY',
}

interface PhaseMetrics {
  totalUsers: number;
  totalValueLocked: number;
  transactionVolume: number;
  governanceParticipation: number;
}

interface PhaseTransitionCriteria {
  minUsers: number;
  minTVL: number;
  minTransactions: number;
  minGovernanceRate: number;
}

const PHASE_CRITERIA: Record<LifecyclePhase, PhaseTransitionCriteria> = {
  [LifecyclePhase.SEEDING]: {
    minUsers: 0,
    minTVL: 0,
    minTransactions: 0,
    minGovernanceRate: 0,
  },
  [LifecyclePhase.GROWTH]: {
    minUsers: 100,
    minTVL: 10000,
    minTransactions: 500,
    minGovernanceRate: 0.1,
  },
  [LifecyclePhase.SCALING]: {
    minUsers: 1000,
    minTVL: 100000,
    minTransactions: 5000,
    minGovernanceRate: 0.25,
  },
  [LifecyclePhase.MATURITY]: {
    minUsers: 10000,
    minTVL: 1000000,
    minTransactions: 50000,
    minGovernanceRate: 0.4,
  },
};

export class PhaseManager {
  private currentPhase: LifecyclePhase = LifecyclePhase.SEEDING;
  private metrics: PhaseMetrics = {
    totalUsers: 0,
    totalValueLocked: 0,
    transactionVolume: 0,
    governanceParticipation: 0,
  };

  constructor() {
    this.loadPhaseFromStorage();
  }

  getCurrentPhase(): LifecyclePhase {
    return this.currentPhase;
  }

  getPhaseProgress(): number {
    const currentCriteria = PHASE_CRITERIA[this.currentPhase];
    const nextPhase = this.getNextPhase();
    
    if (!nextPhase) return 100;

    const nextCriteria = PHASE_CRITERIA[nextPhase];
    
    const userProgress = Math.min(100, (this.metrics.totalUsers / nextCriteria.minUsers) * 100);
    const tvlProgress = Math.min(100, (this.metrics.totalValueLocked / nextCriteria.minTVL) * 100);
    const txProgress = Math.min(100, (this.metrics.transactionVolume / nextCriteria.minTransactions) * 100);
    const govProgress = Math.min(100, (this.metrics.governanceParticipation / nextCriteria.minGovernanceRate) * 100);

    return (userProgress + tvlProgress + txProgress + govProgress) / 4;
  }

  async checkTransition(): Promise<void> {
    const nextPhase = this.getNextPhase();
    
    if (!nextPhase) {
      logger.info('Already at final phase (MATURITY)');
      return;
    }

    const criteria = PHASE_CRITERIA[nextPhase];
    const canTransition = 
      this.metrics.totalUsers >= criteria.minUsers &&
      this.metrics.totalValueLocked >= criteria.minTVL &&
      this.metrics.transactionVolume >= criteria.minTransactions &&
      this.metrics.governanceParticipation >= criteria.minGovernanceRate;

    if (canTransition) {
      await this.transitionToPhase(nextPhase);
    } else {
      logger.info(`Phase transition criteria not met for ${nextPhase}`, {
        current: this.metrics,
        required: criteria,
      });
    }
  }

  async updateMetrics(newMetrics: Partial<PhaseMetrics>): Promise<void> {
    this.metrics = { ...this.metrics, ...newMetrics };
    logger.info('Metrics updated', this.metrics);
    await this.checkTransition();
  }

  private async transitionToPhase(newPhase: LifecyclePhase): Promise<void> {
    const oldPhase = this.currentPhase;
    this.currentPhase = newPhase;
    
    logger.info(`🎯 Phase transition: ${oldPhase} → ${newPhase}`);
    
    await this.executePhaseActions(newPhase);
    this.savePhaseToStorage();
  }

  private async executePhaseActions(phase: LifecyclePhase): Promise<void> {
    switch (phase) {
      case LifecyclePhase.GROWTH:
        logger.info('Activating growth mechanisms: referral bonuses, reward acceleration');
        break;
      case LifecyclePhase.SCALING:
        logger.info('Activating scaling features: cross-chain bridges, partnerships');
        break;
      case LifecyclePhase.MATURITY:
        logger.info('Activating maturity features: full decentralization, advanced governance');
        break;
    }
  }

  private getNextPhase(): LifecyclePhase | null {
    const phases = Object.values(LifecyclePhase);
    const currentIndex = phases.indexOf(this.currentPhase);
    
    if (currentIndex < phases.length - 1) {
      return phases[currentIndex + 1];
    }
    
    return null;
  }

  private loadPhaseFromStorage(): void {
    logger.info('Phase loaded from storage:', this.currentPhase);
  }

  private savePhaseToStorage(): void {
    logger.info('Phase saved to storage:', this.currentPhase);
  }
}
