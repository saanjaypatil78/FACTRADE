#!/bin/bash

echo "🎯 FACTRADE FGDA Live Demo & Testing"
echo "===================================="
echo ""

echo "✅ 1. Backend Health Check"
curl -s http://localhost:4000/health
echo -e "\n"

echo "✅ 2. Task Orchestrator Health"
curl -s http://localhost:5000/health
echo -e "\n"

echo "✅ 3. Rewards Statistics"
curl -s http://localhost:4000/api/v1/rewards/stats
echo -e "\n"

echo "✅ 4. Staking Pools"
curl -s http://localhost:4000/api/v1/staking/pools
echo -e "\n"

echo "✅ 5. Governance Proposals"
curl -s http://localhost:4000/api/v1/governance/proposals
echo -e "\n"

echo "✅ 6. Analytics Overview"
curl -s http://localhost:4000/api/v1/analytics/overview
echo -e "\n"

echo "✅ 7. Task Orchestrator Status"
curl -s http://localhost:5000/status
echo -e "\n"

echo "✅ 8. Create Test Task"
curl -s -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"type":"demo_task","priority":5,"metadata":{"test":true}}'
echo -e "\n"

echo ""
echo "🎉 All API tests complete!"
echo "🌐 Frontend: http://localhost:3000"
echo "🔧 Backend: http://localhost:4000"
echo "🤖 Orchestrator: http://localhost:5000"
