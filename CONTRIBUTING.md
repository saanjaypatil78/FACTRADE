# Contributing to FACTRADE FGDA

Thank you for your interest in contributing to FACTRADE FGDA! This document provides guidelines and instructions for contributing.

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on the best outcome for the community

## Development Setup

### Prerequisites

- Node.js 18+
- Rust 1.70+
- Solana CLI 1.16+
- Anchor 0.29+
- Docker & Docker Compose
- Git

### Local Setup

```bash
# Clone repository
git clone <repository-url>
cd factrade-fgda

# Install dependencies
npm install

# Set up environment
cp .env.example .env
# Edit .env with your configuration

# Start local development
npm run dev
```

## Contribution Workflow

### 1. Fork & Clone

```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/factrade-fgda.git
cd factrade-fgda

# Add upstream remote
git remote add upstream https://github.com/factrade/factrade-fgda.git
```

### 2. Create Branch

```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Or bug fix branch
git checkout -b fix/bug-description
```

### 3. Make Changes

- Write clean, documented code
- Follow existing code style
- Add tests for new features
- Update documentation as needed

### 4. Test Changes

```bash
# Run all tests
npm run test

# Run linter
npm run lint

# Run type checking
npm run build
```

### 5. Commit Changes

```bash
# Stage changes
git add .

# Commit with descriptive message
git commit -m "feat: add new staking feature"
```

**Commit Message Format**:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes
- `refactor:` Code refactoring
- `test:` Test additions/changes
- `chore:` Build/tooling changes

### 6. Push & Create PR

```bash
# Push to your fork
git push origin feature/your-feature-name

# Create Pull Request on GitHub
```

## Code Style Guidelines

### TypeScript/JavaScript

```typescript
// Use TypeScript for type safety
interface User {
  wallet: string;
  balance: number;
}

// Use async/await over promises
async function fetchUser(wallet: string): Promise<User> {
  const response = await api.get(`/users/${wallet}`);
  return response.data;
}

// Use meaningful variable names
const userBalance = await fetchBalance(wallet);

// Add comments for complex logic
// Calculate rewards based on staking duration and APY
const rewards = calculateRewards(amount, duration, apy);
```

### Rust

```rust
// Use idiomatic Rust patterns
use anchor_lang::prelude::*;

// Document public functions
/// Initializes the rewards pool with given parameters
pub fn initialize_rewards_pool(
    ctx: Context<InitializeRewardsPool>,
    base_apy: u64,
) -> Result<()> {
    // Implementation
    Ok(())
}

// Use descriptive error messages
#[error_code]
pub enum ErrorCode {
    #[msg("Rewards pool is paused")]
    PoolPaused,
}
```

## Testing Guidelines

### Unit Tests

```typescript
describe('RewardsCalculator', () => {
  it('should calculate rewards correctly', () => {
    const rewards = calculateRewards(1000, 365, 12);
    expect(rewards).toBe(120);
  });

  it('should handle edge cases', () => {
    expect(calculateRewards(0, 365, 12)).toBe(0);
    expect(calculateRewards(1000, 0, 12)).toBe(0);
  });
});
```

### Integration Tests

```typescript
describe('Staking API', () => {
  it('should stake tokens successfully', async () => {
    const response = await request(app)
      .post('/api/v1/staking/stake')
      .send({ wallet, poolId, amount: 1000 });
    
    expect(response.status).toBe(200);
    expect(response.body.success).toBe(true);
  });
});
```

## Documentation

### Code Documentation

- Add JSDoc comments for functions
- Document complex algorithms
- Include usage examples
- Update README.md if adding new features

### API Documentation

- Document all endpoints
- Include request/response examples
- Specify error codes
- Note authentication requirements

## Review Process

### What We Look For

- Code quality and style
- Test coverage
- Documentation completeness
- Performance considerations
- Security implications

### Review Timeline

- Initial review: Within 2 business days
- Follow-up reviews: Within 1 business day
- Merge decision: After all checks pass

## Community

### Communication Channels

- GitHub Issues: Bug reports and feature requests
- Discord: Real-time discussion
- Twitter: Announcements and updates

### Getting Help

- Check existing documentation
- Search closed issues
- Ask in Discord #dev channel
- Create detailed GitHub issue

## Recognition

Contributors will be:
- Listed in CONTRIBUTORS.md
- Mentioned in release notes
- Eligible for community rewards

Thank you for contributing to FACTRADE FGDA! 🚀
