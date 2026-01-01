# FACTRADE FGDA - Interactive Live Demo

## 🎮 Access Points

### 🌐 Frontend dApp
**URL**: http://localhost:3000

The main user interface for the FACTRADE FGDA protocol.

### 🔧 Backend API
**URL**: http://localhost:4000  
**Docs**: See below for all available endpoints

### 🤖 Task Orchestrator
**URL**: http://localhost:5000  
**Purpose**: Autonomous workflow and lifecycle management

---

## 📱 Frontend Pages

### 1. Dashboard (/)
**Features to Test**:
- **Stats Cards**: View 4 key metrics
  - Total Rewards
  - Current APY (12.5%)
  - Total Staked
  - Pending Rewards
- **Rewards Chart**: Line chart showing 7-day reward history
- **Quick Actions**:
  - Claim Rewards button
  - Compound Rewards button
  - Stake Tokens button
- **Lifecycle Phase**: Progress bar showing current phase (Seeding → Growth → Scaling → Maturity)

**Without Wallet**: Shows "Connect Your Wallet" message  
**With Wallet Connected**: Shows full dashboard

### 2. Staking (/staking)
**Features to Test**:
- **Three Staking Pools**:
  1. **7-Day Pool**: 10% APY, 1.0x multiplier
  2. **14-Day Pool**: 15% APY, 1.5x multiplier  
  3. **30-Day Pool**: 25% APY, 2.5x multiplier
  
- **Each Pool Shows**:
  - APY percentage
  - Lock period
  - Total staked amount
  - Reward multiplier
  - Amount input field
  - "Stake" button

- **Your Positions**: List of active staking positions

### 3. Governance (/governance)
**Features to Test**:
- **Active Proposals List**:
  - Proposal title and description
  - Current vote counts (Yes/No)
  - Vote percentages with progress bars
  - Status badge (active/passed/rejected)
  - End time countdown

- **Voting Interface**:
  - "Vote Yes" button (green)
  - "Vote No" button (gray)
  - Vote confirmation

### 4. Analytics (/analytics)
**Features to Test**:
- **Protocol Metrics**:
  - Total Value Locked: $12.5M
  - Total Users: 4,523
  - Total Transactions: 89,456

- **Top Stakers List**: Shows top 5 stakers
- **Recent Transactions**: Latest 5 transactions
- **Protocol Performance Chart**: Historical TVL data

### UI Features
- ☀️ **Dark Mode Toggle**: Click sun/moon icon in header
- 📱 **Responsive Design**: Resize browser to test mobile view
- 🔗 **Navigation**: All links in header work
- 💼 **Wallet Button**: Solana wallet connect button in header

---

## 🔧 Backend API Endpoints

### Rewards APIs

#### GET /api/v1/rewards/stats
Get global rewards statistics

**Example**:
```bash
curl http://localhost:4000/api/v1/rewards/stats
```

**Response**:
```json
{
  "totalRewardsDistributed": 1234567.89,
  "currentAPY": 12.5,
  "totalStaked": 9876543.21,
  "activeUsers": 4523
}
```

#### GET /api/v1/rewards/user/:wallet
Get rewards for specific user

**Example**:
```bash
curl http://localhost:4000/api/v1/rewards/user/YourWalletAddress
```

**Response**:
```json
{
  "wallet": "YourWalletAddress",
  "totalRewards": 1234.56,
  "pendingRewards": 12.34,
  "claimedRewards": 1222.22,
  "lastClaimTime": "2024-01-01T12:00:00.000Z"
}
```

#### POST /api/v1/rewards/claim
Claim pending rewards

**Example**:
```bash
curl -X POST http://localhost:4000/api/v1/rewards/claim \
  -H "Content-Type: application/json" \
  -d '{"wallet":"YourWallet","signature":"sig123"}'
```

### Staking APIs

#### GET /api/v1/staking/pools
List all staking pools

**Example**:
```bash
curl http://localhost:4000/api/v1/staking/pools
```

**Response**:
```json
[
  {
    "id": "pool_7day",
    "name": "7-Day Staking",
    "apy": 10.0,
    "lockPeriod": 7,
    "totalStaked": 1000000,
    "rewardMultiplier": 1.0
  },
  ...
]
```

#### GET /api/v1/staking/positions/:wallet
Get user staking positions

#### POST /api/v1/staking/stake
Stake tokens

#### POST /api/v1/staking/unstake
Unstake tokens

### Governance APIs

#### GET /api/v1/governance/proposals
Get active proposals

**Example**:
```bash
curl http://localhost:4000/api/v1/governance/proposals
```

#### POST /api/v1/governance/vote
Cast vote on proposal

**Example**:
```bash
curl -X POST http://localhost:4000/api/v1/governance/vote \
  -H "Content-Type: application/json" \
  -d '{
    "wallet":"YourWallet",
    "proposalId":"prop_1",
    "vote":"yes",
    "signature":"sig123"
  }'
```

### Analytics APIs

#### GET /api/v1/analytics/overview
Get protocol overview

**Example**:
```bash
curl http://localhost:4000/api/v1/analytics/overview
```

**Response**:
```json
{
  "totalValueLocked": 12500000,
  "totalUsers": 4523,
  "totalTransactions": 89456,
  "averageAPY": 12.5,
  "last24hVolume": 450000,
  "last24hTransactions": 1234
}
```

#### GET /api/v1/analytics/chart/:metric
Get historical chart data

**Example**:
```bash
curl "http://localhost:4000/api/v1/analytics/chart/tvl?period=7d"
```

---

## 🤖 Task Orchestrator APIs

### GET /health
Simple health check

**Example**:
```bash
curl http://localhost:5000/health
```

**Response**:
```json
{
  "status": "healthy",
  "phase": "SEEDING",
  "queueSize": 0,
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

### GET /status
Detailed system status

**Example**:
```bash
curl http://localhost:5000/status
```

**Response**:
```json
{
  "currentPhase": "SEEDING",
  "phaseProgress": 35.5,
  "activeTasks": [],
  "failedTasks": [],
  "statistics": {
    "total": 10,
    "pending": 2,
    "running": 1,
    "completed": 7,
    "failed": 0,
    "escalated": 0
  }
}
```

### POST /tasks
Create new task

**Example**:
```bash
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "type":"reward_distribution",
    "priority":8,
    "maxAttempts":3,
    "metadata":{"pool":"pool_30day"}
  }'
```

### GET /tasks/:id
Get task details

**Example**:
```bash
curl http://localhost:5000/tasks/task_123456
```

---

## 🎯 Test Scenarios

### Scenario 1: View Dashboard
1. Open http://localhost:3000
2. See 4 stat cards with metrics
3. View rewards chart
4. Check lifecycle phase progress
5. Toggle dark mode (sun/moon icon)

### Scenario 2: Explore Staking
1. Navigate to http://localhost:3000/staking
2. View all 3 staking pools
3. Compare APY rates (10%, 15%, 25%)
4. Note lock periods (7, 14, 30 days)
5. See reward multipliers (1x, 1.5x, 2.5x)

### Scenario 3: Check Governance
1. Navigate to http://localhost:3000/governance
2. View active proposal
3. See vote counts and percentages
4. Note vote bars (Yes in green, No in red)
5. Check proposal end time

### Scenario 4: Analytics Review
1. Navigate to http://localhost:3000/analytics
2. View TVL ($12.5M)
3. See user count (4,523)
4. Check transaction volume
5. Review top stakers list
6. See recent transactions

### Scenario 5: Test Backend APIs
```bash
# Check all backend endpoints work
curl http://localhost:4000/health
curl http://localhost:4000/api/v1/rewards/stats
curl http://localhost:4000/api/v1/staking/pools
curl http://localhost:4000/api/v1/governance/proposals
curl http://localhost:4000/api/v1/analytics/overview
```

### Scenario 6: Test Task Orchestrator
```bash
# Check orchestrator status
curl http://localhost:5000/health
curl http://localhost:5000/status

# Create a task
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"type":"test_task","priority":5}'

# Check task statistics
curl http://localhost:5000/status | grep -o '"statistics":{[^}]*}'
```

### Scenario 7: Mobile Responsiveness
1. Open http://localhost:3000
2. Resize browser window to mobile size (< 768px width)
3. Verify nav collapses
4. Check cards stack vertically
5. Ensure all content remains accessible

### Scenario 8: Dark Mode
1. Open http://localhost:3000
2. Click sun icon in header (top right)
3. Page switches to dark theme
4. Navigate between pages
5. Dark mode persists
6. Click moon icon to return to light mode

---

## 🔍 Browser DevTools Testing

### Open DevTools
Press `F12` or right-click → "Inspect"

### Network Tab
1. Open Network tab
2. Refresh page
3. See all API calls
4. Check response times
5. Verify status codes (200 = success)

### Console Tab
1. Open Console tab
2. Look for errors (red text)
3. See info logs (blue text)
4. Check for warnings

### Application Tab
1. Open Application tab
2. Check Local Storage (for theme preference)
3. View Session Storage

---

## 📊 What You Should See

### Dashboard
- ✅ 4 stat cards with icons
- ✅ Line chart with 7 data points
- ✅ 3 action buttons
- ✅ Phase progress bar at bottom
- ✅ Smooth animations

### Staking
- ✅ 3 cards side-by-side (desktop)
- ✅ 3 cards stacked (mobile)
- ✅ Different APY for each pool
- ✅ Input fields working
- ✅ Hover effects on cards

### Governance
- ✅ Proposal card with details
- ✅ Vote percentages add up to 100%
- ✅ Progress bars showing votes
- ✅ Active status badge
- ✅ Vote buttons responsive

### Analytics
- ✅ 3 metric cards at top
- ✅ Top 5 stakers with amounts
- ✅ Recent transactions list
- ✅ All numbers formatted with commas

---

## 🐛 Known Limitations

### Current State
- **Mock Data**: All data is currently mocked (not real blockchain)
- **No Wallet Connection**: Wallet buttons are UI-only (no actual connection)
- **No Transactions**: No real blockchain transactions happen
- **No Database**: Data doesn't persist between restarts

### What Works
- ✅ All UI pages load and render
- ✅ Navigation between pages
- ✅ Dark mode toggle
- ✅ Responsive design
- ✅ Backend APIs return data
- ✅ Task orchestrator manages tasks
- ✅ Logging and monitoring

### What's Needed for Production
- [ ] Deploy Solana programs to devnet
- [ ] Connect frontend to real programs
- [ ] Implement actual wallet connection
- [ ] Add database for persistence
- [ ] Security audit
- [ ] Load testing

---

## 💡 Tips for Testing

### 1. Use Browser Extensions
- Install React DevTools to inspect components
- Use JSON Formatter for better API response viewing

### 2. Test Different Browsers
- Chrome
- Firefox
- Safari
- Edge

### 3. Test Different Screen Sizes
- Desktop (1920x1080)
- Laptop (1366x768)
- Tablet (768x1024)
- Mobile (375x667)

### 4. Check Accessibility
- Tab through interface (keyboard navigation)
- Check color contrast
- Test with screen reader (if available)

### 5. Performance Testing
- Check page load times
- Monitor memory usage in DevTools
- Watch network waterfall

---

## 📞 Support

If you encounter issues:

1. **Check logs**:
   ```bash
   tail -f /tmp/backend.log
   tail -f /tmp/orchestrator.log
   tail -f /tmp/frontend.log
   ```

2. **Restart services**:
   ```bash
   # Kill all services
   pkill -f "npm run dev"
   
   # Restart
   cd /home/engine/project/backend && npm run dev &
   cd /home/engine/project/task-orchestrator && npm run dev &
   cd /home/engine/project/frontend && npm run dev &
   ```

3. **Check ports**:
   ```bash
   lsof -i :3000  # Frontend
   lsof -i :4000  # Backend
   lsof -i :5000  # Orchestrator
   ```

---

## 🎉 Happy Testing!

Explore all the features, test different scenarios, and see how the FACTRADE FGDA protocol works!

**Remember**: This is a development preview with mock data. The real magic happens when connected to Solana blockchain! 🚀
