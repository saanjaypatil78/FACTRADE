# FACTRADE FGDA Deployment Guide

## Production Deployment Checklist

### Pre-Deployment

- [ ] Security audit completed for all smart contracts
- [ ] Code review completed
- [ ] All tests passing (unit, integration, E2E)
- [ ] Load testing completed
- [ ] Monitoring and alerting configured
- [ ] Backup and recovery procedures tested
- [ ] Multi-sig wallet configured for program upgrades
- [ ] Environment variables configured and encrypted
- [ ] DNS and SSL certificates configured
- [ ] Rate limiting configured

### Smart Contract Deployment

#### 1. Build Programs

```bash
cd solana-program
anchor build
```

#### 2. Deploy to Devnet (Testing)

```bash
# Configure Solana CLI
solana config set --url devnet
solana config set --keypair ~/.config/solana/id.json

# Deploy programs
anchor deploy --provider.cluster devnet

# Verify deployment
solana program show <PROGRAM_ID> --url devnet
```

#### 3. Deploy to Mainnet (Production)

```bash
# CRITICAL: Ensure you have sufficient SOL for deployment
solana balance

# Switch to mainnet
solana config set --url mainnet-beta

# Deploy programs
anchor deploy --provider.cluster mainnet

# Verify deployment
solana program show <PROGRAM_ID> --url mainnet-beta
```

#### 4. Initialize Programs

```bash
# Initialize rewards pool
anchor run initialize-rewards --provider.cluster mainnet

# Initialize staking pool
anchor run initialize-staking --provider.cluster mainnet

# Initialize governance
anchor run initialize-governance --provider.cluster mainnet
```

### Backend Deployment

#### 1. Build Backend

```bash
cd backend
npm run build
```

#### 2. Deploy to Production Server

```bash
# Using Docker
docker build -t factrade-backend .
docker push factrade-backend:latest

# Deploy to Kubernetes
kubectl apply -f infrastructure/k8s/backend-deployment.yml
```

#### 3. Verify Backend

```bash
curl https://api.factrade.io/health
```

### Frontend Deployment

#### 1. Build Frontend

```bash
cd frontend
npm run build
```

#### 2. Deploy to CDN

```bash
# Deploy to Vercel/Netlify/CloudFlare
npm run deploy
```

#### 3. Verify Frontend

```bash
curl https://app.factrade.io
```

### Task Orchestrator Deployment

```bash
cd task-orchestrator
npm run build
docker build -t factrade-orchestrator .
docker push factrade-orchestrator:latest
kubectl apply -f infrastructure/k8s/orchestrator-deployment.yml
```

### Post-Deployment

- [ ] Smoke tests completed
- [ ] Monitoring dashboards active
- [ ] Alerts configured and tested
- [ ] Documentation updated
- [ ] Team notified
- [ ] Social media announcement prepared

## Rollback Procedures

### Smart Contract Rollback

```bash
# Upgrade to previous version
anchor upgrade <PROGRAM_ID> --program-keypair <OLD_KEYPAIR>
```

### Backend Rollback

```bash
# Rollback to previous version
kubectl rollout undo deployment/factrade-backend
```

### Frontend Rollback

```bash
# Revert to previous deployment
vercel rollback
```

## Monitoring

### Health Endpoints

- Backend: `https://api.factrade.io/health`
- Orchestrator: `https://orchestrator.factrade.io/health`

### Dashboards

- Grafana: `https://grafana.factrade.io`
- Prometheus: `https://prometheus.factrade.io`

### Alerts

Configured via Prometheus AlertManager:
- High error rate
- Low success rate
- Circuit breaker triggered
- Database connection issues
- High response times

## Emergency Procedures

### Emergency Pause

```bash
# Pause rewards pool
anchor run emergency-pause --provider.cluster mainnet

# Pause staking pool
anchor run pause-staking --provider.cluster mainnet
```

### Contact Information

- DevOps Lead: devops@factrade.io
- Security Team: security@factrade.io
- On-Call: +1-xxx-xxx-xxxx

## Performance Benchmarks

### Expected Metrics

- API Response Time: < 200ms (p95)
- Transaction Confirmation: < 30s
- Uptime: 99.9%
- Error Rate: < 0.1%

## Scaling Considerations

### Horizontal Scaling

```bash
# Scale backend
kubectl scale deployment factrade-backend --replicas=5

# Scale orchestrator
kubectl scale deployment factrade-orchestrator --replicas=3
```

### Database Scaling

- Read replicas configured
- Connection pooling enabled
- Query optimization completed

## Maintenance Windows

- Weekly: Sunday 2:00 AM - 4:00 AM UTC
- Monthly: First Sunday of month, 2:00 AM - 6:00 AM UTC
