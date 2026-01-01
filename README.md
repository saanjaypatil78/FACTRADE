# FACTRADE FGDA

**Autonomous Solana Rewards Protocol with Staking and Lifecycle Management**

## 🚀 Overview

FACTRADE FGDA is a production-ready decentralized application (dApp) built on Solana that provides:

- **Autonomous Rewards Protocol**: Auto-yield tokenomics with dynamic APY
- **Token Staking**: Multi-period staking vaults (7, 14, 30 days) with unbonding
- **Lifecycle Management**: Phase-based progression (Seeding → Growth → Scaling → Maturity)
- **Task Orchestration**: Self-healing retry system with intelligent escalation
- **Real-time Dashboard**: Live metrics for rewards, TVL, and performance

## 📋 Architecture

### Smart Contracts (Solana Programs)
- **Rewards Protocol** (`rewards_program`): Autonomous yield calculation and compounding
- **Staking Vault** (`staking_program`): Lock-up periods with unbonding mechanics
- **Governance Token** (`governance_program`): On-chain voting and parameter control

### Frontend (React + TypeScript)
- Wallet integration (Phantom, Solflare, Ledger)
- Real-time dashboard with auto-updating metrics
- Staking interface with period selection
- Transaction history and analytics
- Responsive design with dark mode

### Backend (Node.js + Express)
- On-chain data indexing and aggregation
- Task tracking and workflow management
- Analytics and reporting endpoints
- Rate limiting and monitoring

### Task Orchestration
- Autonomous phase transitions
- Multi-approach retry strategies
- Automatic escalation system
- Detailed logging and debugging

## 🛠 Tech Stack

- **Blockchain**: Solana (Anchor Framework)
- **Frontend**: React, TypeScript, Vite, TailwindCSS
- **Backend**: Node.js, Express, TypeScript
- **Database**: PostgreSQL (indexing) + Redis (caching)
- **Testing**: Jest, Playwright, Anchor Tests
- **Monitoring**: Prometheus, Grafana
- **CI/CD**: GitHub Actions

## 📦 Installation

### Prerequisites
- Node.js 18+
- Rust 1.70+
- Solana CLI 1.16+
- Anchor 0.29+
- Docker & Docker Compose

### Quick Start

```bash
# Clone repository
git clone <repository-url>
cd factrade-fgda

# Install dependencies
npm install

# Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# Build Solana programs
npm run solana:build

# Run tests
npm run solana:test
npm run test

# Start development servers
npm run dev
```

## 🚢 Deployment

### Devnet Deployment
```bash
# Deploy to Solana Devnet
npm run deploy:devnet

# Verify deployment
solana program show <PROGRAM_ID> --url devnet
```

### Mainnet Deployment
```bash
# Deploy to Solana Mainnet (requires SOL for fees)
npm run deploy:mainnet

# Verify deployment
solana program show <PROGRAM_ID> --url mainnet-beta
```

## 📊 Monitoring & Operations

### Health Checks
- Frontend: `http://localhost:3000/health`
- Backend API: `http://localhost:4000/health`
- Orchestrator: `http://localhost:5000/health`

### Metrics & Dashboards
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001`

### Logs
```bash
# View application logs
docker-compose logs -f

# View specific service
docker-compose logs -f backend
```

## 🧪 Testing

```bash
# Run all tests
npm run test

# Run E2E tests
npm run test:e2e

# Run Solana program tests
npm run solana:test

# Coverage report
npm run test:coverage
```

## 📖 API Documentation

### Backend Endpoints

#### Rewards
- `GET /api/v1/rewards/stats` - Get global rewards statistics
- `GET /api/v1/rewards/user/:wallet` - Get user rewards
- `POST /api/v1/rewards/claim` - Claim pending rewards

#### Staking
- `GET /api/v1/staking/pools` - List staking pools
- `POST /api/v1/staking/stake` - Stake tokens
- `POST /api/v1/staking/unstake` - Initiate unstaking
- `GET /api/v1/staking/positions/:wallet` - Get user positions

#### Tasks
- `GET /api/v1/tasks` - List tasks
- `POST /api/v1/tasks` - Create task
- `GET /api/v1/tasks/:id` - Get task details
- `PATCH /api/v1/tasks/:id` - Update task status

## 🔧 Configuration

### Environment Variables

```env
# Solana
SOLANA_NETWORK=devnet
SOLANA_RPC_URL=https://api.devnet.solana.com
REWARDS_PROGRAM_ID=
STAKING_PROGRAM_ID=
GOVERNANCE_PROGRAM_ID=

# Backend
NODE_ENV=development
PORT=4000
DATABASE_URL=postgresql://user:pass@localhost:5432/factrade
REDIS_URL=redis://localhost:6379

# Frontend
VITE_API_URL=http://localhost:4000
VITE_SOLANA_NETWORK=devnet

# Orchestrator
ORCHESTRATOR_PORT=5000
RETRY_MAX_ATTEMPTS=3
ESCALATION_THRESHOLD=5
```

## 🏗 Project Structure

```
factrade-fgda/
├── solana-program/          # Rust Solana programs
│   ├── programs/
│   │   ├── rewards/         # Rewards protocol
│   │   ├── staking/         # Staking vault
│   │   └── governance/      # Governance
│   └── tests/
├── frontend/                # React TypeScript dApp
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── utils/
│   └── public/
├── backend/                 # Node.js Express API
│   ├── src/
│   │   ├── controllers/
│   │   ├── services/
│   │   ├── models/
│   │   └── middleware/
│   └── tests/
├── task-orchestrator/       # Workflow engine
│   ├── src/
│   │   ├── phases/
│   │   ├── retry/
│   │   └── escalation/
│   └── tests/
├── infrastructure/          # DevOps
│   ├── docker/
│   ├── k8s/
│   └── monitoring/
└── tests/                   # E2E tests
```

## 🔒 Security

- All smart contracts undergo security audits before mainnet
- Multi-signature wallet for program upgrades
- Rate limiting and DDoS protection on APIs
- Environment variable encryption
- Regular dependency updates

## 📈 Lifecycle Phases

### 1. Seeding Phase
- Initial user onboarding
- Basic reward distribution
- Community building

### 2. Growth Phase
- Reward acceleration
- Referral mechanisms
- Partnership integration

### 3. Scaling Phase
- Cross-chain bridges
- Advanced features
- Institutional adoption

### 4. Maturity Phase
- Full governance decentralization
- Protocol sustainability
- Long-term value accrual

## 🤝 Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🆘 Support

- Documentation: [docs.factrade.io](https://docs.factrade.io)
- Discord: [discord.gg/factrade](https://discord.gg/factrade)
- Email: support@factrade.io

## 🎯 Roadmap

- [x] Core protocol development
- [x] Frontend dApp
- [x] Backend API infrastructure
- [x] Task orchestration system
- [ ] Security audit
- [ ] Testnet launch
- [ ] Mainnet deployment
- [ ] Governance activation

---

**Built with ❤️ by the FACTRADE team**
