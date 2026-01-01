# FACTRADE FGDA - Live Testing Guide

## 🚀 System Status

All services are now running:

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:4000
- **Task Orchestrator**: http://localhost:5000

## 📋 Quick Test Commands

### Test Backend API

```bash
# Health check
curl http://localhost:4000/health

# Get rewards stats
curl http://localhost:4000/api/v1/rewards/stats

# Get staking pools
curl http://localhost:4000/api/v1/staking/pools

# Get governance proposals
curl http://localhost:4000/api/v1/governance/proposals

# Get analytics overview
curl http://localhost:4000/api/v1/analytics/overview
```

### Test Task Orchestrator

```bash
# Health check with phase status
curl http://localhost:5000/health

# Get full system status
curl http://localhost:5000/status

# Create a test task
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"type":"test","priority":5,"metadata":{"test":true}}'

# Get task by ID (replace with actual ID)
curl http://localhost:5000/tasks/<TASK_ID>
```

## 🧪 Component Testing

### 1. Backend API Testing

#### Rewards Endpoints
```bash
# Global rewards statistics
curl http://localhost:4000/api/v1/rewards/stats | jq

# User rewards (example wallet)
curl http://localhost:4000/api/v1/rewards/user/YourWalletAddressHere | jq

# Claim rewards (POST)
curl -X POST http://localhost:4000/api/v1/rewards/claim \
  -H "Content-Type: application/json" \
  -d '{"wallet":"YourWalletAddress","signature":"mock_sig"}' | jq
```

#### Staking Endpoints
```bash
# List all staking pools
curl http://localhost:4000/api/v1/staking/pools | jq

# Get user staking positions
curl http://localhost:4000/api/v1/staking/positions/YourWalletAddress | jq

# Stake tokens
curl -X POST http://localhost:4000/api/v1/staking/stake \
  -H "Content-Type: application/json" \
  -d '{
    "wallet":"YourWalletAddress",
    "poolId":"pool_30day",
    "amount":10000,
    "signature":"mock_sig"
  }' | jq

# Unstake tokens
curl -X POST http://localhost:4000/api/v1/staking/unstake \
  -H "Content-Type: application/json" \
  -d '{
    "wallet":"YourWalletAddress",
    "positionId":"pos_123",
    "signature":"mock_sig"
  }' | jq
```

#### Governance Endpoints
```bash
# Get active proposals
curl http://localhost:4000/api/v1/governance/proposals | jq

# Cast vote
curl -X POST http://localhost:4000/api/v1/governance/vote \
  -H "Content-Type: application/json" \
  -d '{
    "wallet":"YourWalletAddress",
    "proposalId":"prop_1",
    "vote":"yes",
    "signature":"mock_sig"
  }' | jq
```

#### Analytics Endpoints
```bash
# Protocol overview
curl http://localhost:4000/api/v1/analytics/overview | jq

# Chart data
curl "http://localhost:4000/api/v1/analytics/chart/tvl?period=7d" | jq
```

#### Task Management
```bash
# List all tasks
curl http://localhost:4000/api/v1/tasks | jq

# Create task
curl -X POST http://localhost:4000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "type":"reward_distribution",
    "priority":8,
    "metadata":{"pool":"pool_30day"}
  }' | jq

# Get specific task
curl http://localhost:4000/api/v1/tasks/task_123 | jq

# Update task status
curl -X PATCH http://localhost:4000/api/v1/tasks/task_123 \
  -H "Content-Type: application/json" \
  -d '{"status":"completed"}' | jq
```

### 2. Task Orchestrator Testing

#### Health & Status
```bash
# Simple health check
curl http://localhost:5000/health | jq

# Detailed status with phase info
curl http://localhost:5000/status | jq
```

#### Phase Management Testing
```bash
# Check current phase
curl http://localhost:5000/status | jq '.currentPhase'

# Check phase progress
curl http://localhost:5000/status | jq '.phaseProgress'
```

#### Task Queue Testing
```bash
# Create high priority task
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "type":"NETWORK_ERROR",
    "priority":10,
    "maxAttempts":3,
    "metadata":{"critical":true}
  }' | jq

# Create low priority task
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "type":"test_task",
    "priority":1,
    "metadata":{"test":true}
  }' | jq

# Check task statistics
curl http://localhost:5000/status | jq '.statistics'

# View active tasks
curl http://localhost:5000/status | jq '.activeTasks'

# View failed tasks (for escalation testing)
curl http://localhost:5000/status | jq '.failedTasks'
```

#### Retry Strategy Testing

Create tasks that will trigger different retry strategies:

```bash
# Test exponential backoff
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"type":"NETWORK_ERROR","priority":5}' | jq

# Test rate limiting
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"type":"RATE_LIMIT","priority":5}' | jq

# Test temporary failure
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"type":"TEMPORARY_FAILURE","priority":5}' | jq
```

### 3. Frontend Testing

#### Access the dApp
Open your browser and navigate to: **http://localhost:3000**

#### Testing Checklist

**Dashboard Page** (/)
- [ ] Page loads without errors
- [ ] Stats cards display (Total Rewards, APY, Total Staked, Pending Rewards)
- [ ] Rewards history chart renders
- [ ] Quick actions buttons visible
- [ ] Lifecycle phase progress bar shows
- [ ] Dark mode toggle works
- [ ] Wallet connect button visible

**Staking Page** (/staking)
- [ ] Three staking pools displayed (7, 14, 30 days)
- [ ] Each pool shows APY, lock period, total staked
- [ ] Stake amount input field works
- [ ] Stake button present
- [ ] "Your Staking Positions" section visible

**Governance Page** (/governance)
- [ ] Active proposals list displays
- [ ] Vote percentages calculate correctly
- [ ] Vote Yes/No buttons present
- [ ] Proposal details show (title, description, status)
- [ ] Vote counts display

**Analytics Page** (/analytics)
- [ ] TVL, Users, Transactions metrics show
- [ ] Top stakers list displays
- [ ] Recent transactions list shows
- [ ] All numbers format correctly

**Navigation**
- [ ] All nav links work (Dashboard, Staking, Governance, Analytics)
- [ ] Dark mode persists across pages
- [ ] Responsive design works on mobile (resize browser)
- [ ] Wallet button in header

## 🔍 Integration Testing

### Full User Flow Test

```bash
# 1. Check system health
curl http://localhost:4000/health && \
curl http://localhost:5000/health

# 2. Get initial rewards stats
curl http://localhost:4000/api/v1/rewards/stats

# 3. View staking pools
curl http://localhost:4000/api/v1/staking/pools

# 4. Stake tokens
curl -X POST http://localhost:4000/api/v1/staking/stake \
  -H "Content-Type: application/json" \
  -d '{
    "wallet":"TestWallet123",
    "poolId":"pool_30day",
    "amount":10000,
    "signature":"test_sig"
  }'

# 5. Check user positions
curl http://localhost:4000/api/v1/staking/positions/TestWallet123

# 6. View proposals
curl http://localhost:4000/api/v1/governance/proposals

# 7. Cast vote
curl -X POST http://localhost:4000/api/v1/governance/vote \
  -H "Content-Type: application/json" \
  -d '{
    "wallet":"TestWallet123",
    "proposalId":"prop_1",
    "vote":"yes",
    "signature":"test_sig"
  }'

# 8. Check analytics
curl http://localhost:4000/api/v1/analytics/overview
```

## 📊 Monitoring

### Check Logs

```bash
# Backend logs
tail -f /tmp/backend.log

# Task Orchestrator logs
tail -f /tmp/orchestrator.log

# Frontend logs (build output)
tail -f /tmp/frontend.log
```

### Performance Checks

```bash
# API response time
time curl http://localhost:4000/api/v1/rewards/stats

# Check concurrent requests
for i in {1..10}; do
  curl -s http://localhost:4000/api/v1/staking/pools &
done
wait
echo "All requests completed"
```

## 🐛 Troubleshooting

### Services Not Running

```bash
# Check if ports are in use
lsof -i :3000  # Frontend
lsof -i :4000  # Backend
lsof -i :5000  # Orchestrator

# Restart individual services
cd /home/engine/project/backend && npm run dev &
cd /home/engine/project/frontend && npm run dev &
cd /home/engine/project/task-orchestrator && npm run dev &
```

### Check Service Status

```bash
# List running Node processes
ps aux | grep node

# Check logs for errors
grep -i error /tmp/backend.log
grep -i error /tmp/orchestrator.log
```

## 🎯 Test Scenarios

### Scenario 1: New User Stakes Tokens

1. Open http://localhost:3000/staking
2. View available pools
3. Select 30-day pool
4. Enter amount: 10000
5. Click "Stake" button
6. Verify API call in browser DevTools Network tab

### Scenario 2: User Claims Rewards

1. Open http://localhost:3000
2. View "Pending Rewards" card
3. Click "Claim Rewards" button
4. Check confirmation in console

### Scenario 3: User Votes on Proposal

1. Open http://localhost:3000/governance
2. View active proposals
3. Click "Vote Yes" on a proposal
4. Check vote recorded in API

### Scenario 4: Task Orchestration

1. Create task via API: `curl -X POST http://localhost:5000/tasks ...`
2. Monitor task execution: `curl http://localhost:5000/status`
3. Check task completion
4. Verify retry logic on failure

### Scenario 5: Phase Transition

1. Check current phase: `curl http://localhost:5000/status | jq '.currentPhase'`
2. View progress: `curl http://localhost:5000/status | jq '.phaseProgress'`
3. Monitor for automatic phase transitions

## 📝 Test Results Template

```markdown
## Test Session: [Date/Time]

### Backend API
- [ ] Health check: PASS/FAIL
- [ ] Rewards endpoints: PASS/FAIL
- [ ] Staking endpoints: PASS/FAIL
- [ ] Governance endpoints: PASS/FAIL
- [ ] Analytics endpoints: PASS/FAIL
- [ ] Task management: PASS/FAIL

### Task Orchestrator
- [ ] Health check: PASS/FAIL
- [ ] Status endpoint: PASS/FAIL
- [ ] Task creation: PASS/FAIL
- [ ] Task execution: PASS/FAIL
- [ ] Retry strategies: PASS/FAIL
- [ ] Phase management: PASS/FAIL

### Frontend
- [ ] Dashboard loads: PASS/FAIL
- [ ] Staking page works: PASS/FAIL
- [ ] Governance page works: PASS/FAIL
- [ ] Analytics page works: PASS/FAIL
- [ ] Navigation works: PASS/FAIL
- [ ] Dark mode works: PASS/FAIL

### Integration
- [ ] Full user flow: PASS/FAIL
- [ ] API → Frontend: PASS/FAIL
- [ ] Error handling: PASS/FAIL

### Notes:
[Add any observations, bugs, or issues here]
```

## 🚀 Quick Demo Script

Run this script to demonstrate all features:

```bash
#!/bin/bash

echo "🎯 FACTRADE FGDA Live Demo"
echo "=========================="
echo ""

echo "1️⃣ Backend Health Check..."
curl -s http://localhost:4000/health | jq
echo ""

echo "2️⃣ Task Orchestrator Status..."
curl -s http://localhost:5000/health | jq
echo ""

echo "3️⃣ Staking Pools..."
curl -s http://localhost:4000/api/v1/staking/pools | jq
echo ""

echo "4️⃣ Governance Proposals..."
curl -s http://localhost:4000/api/v1/governance/proposals | jq
echo ""

echo "5️⃣ Analytics Overview..."
curl -s http://localhost:4000/api/v1/analytics/overview | jq
echo ""

echo "6️⃣ Create Test Task..."
curl -s -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"type":"demo","priority":5}' | jq
echo ""

echo "✅ Demo Complete!"
echo "🌐 Open http://localhost:3000 in your browser to see the dApp!"
```

---

**Ready to test!** Open http://localhost:3000 in your browser to start exploring the FACTRADE FGDA dApp!
