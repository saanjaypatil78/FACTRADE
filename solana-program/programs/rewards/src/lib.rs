use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};

declare_id!("rewrDSBhqKMxLkhJRnEKRsJKt7rPt5bBF4VVXsEK6Nx");

#[program]
pub mod rewards_program {
    use super::*;

    pub fn initialize_rewards_pool(
        ctx: Context<InitializeRewardsPool>,
        base_apy: u64,
        min_apy: u64,
        max_apy: u64,
        compound_frequency: u64,
        emergency_pause: bool,
    ) -> Result<()> {
        let rewards_pool = &mut ctx.accounts.rewards_pool;
        rewards_pool.authority = ctx.accounts.authority.key();
        rewards_pool.reward_mint = ctx.accounts.reward_mint.key();
        rewards_pool.reward_vault = ctx.accounts.reward_vault.key();
        rewards_pool.base_apy = base_apy;
        rewards_pool.current_apy = base_apy;
        rewards_pool.min_apy = min_apy;
        rewards_pool.max_apy = max_apy;
        rewards_pool.compound_frequency = compound_frequency;
        rewards_pool.total_staked = 0;
        rewards_pool.total_rewards_distributed = 0;
        rewards_pool.emergency_pause = emergency_pause;
        rewards_pool.last_update_slot = Clock::get()?.slot;
        rewards_pool.bump = ctx.bumps.rewards_pool;

        emit!(RewardsPoolInitialized {
            pool: rewards_pool.key(),
            authority: rewards_pool.authority,
            base_apy,
        });

        Ok(())
    }

    pub fn update_apy_dynamic(ctx: Context<UpdateAPY>, tvl: u64) -> Result<()> {
        let rewards_pool = &mut ctx.accounts.rewards_pool;
        require!(!rewards_pool.emergency_pause, ErrorCode::PoolPaused);

        let new_apy = calculate_dynamic_apy(
            rewards_pool.base_apy,
            rewards_pool.min_apy,
            rewards_pool.max_apy,
            tvl,
        );

        rewards_pool.current_apy = new_apy;
        rewards_pool.last_update_slot = Clock::get()?.slot;

        emit!(APYUpdated {
            pool: rewards_pool.key(),
            old_apy: rewards_pool.current_apy,
            new_apy,
            tvl,
        });

        Ok(())
    }

    pub fn claim_rewards(ctx: Context<ClaimRewards>) -> Result<()> {
        let rewards_pool = &ctx.accounts.rewards_pool;
        require!(!rewards_pool.emergency_pause, ErrorCode::PoolPaused);

        let user_stake = &mut ctx.accounts.user_stake;
        let clock = Clock::get()?;

        let pending_rewards = calculate_rewards(
            user_stake.staked_amount,
            rewards_pool.current_apy,
            user_stake.last_claim_slot,
            clock.slot,
        );

        require!(pending_rewards > 0, ErrorCode::NoRewardsToClaim);

        let seeds = &[
            b"rewards_pool",
            rewards_pool.reward_mint.as_ref(),
            &[rewards_pool.bump],
        ];
        let signer = &[&seeds[..]];

        let cpi_accounts = Transfer {
            from: ctx.accounts.reward_vault.to_account_info(),
            to: ctx.accounts.user_reward_account.to_account_info(),
            authority: rewards_pool.to_account_info(),
        };
        let cpi_program = ctx.accounts.token_program.to_account_info();
        let cpi_ctx = CpiContext::new_with_signer(cpi_program, cpi_accounts, signer);

        token::transfer(cpi_ctx, pending_rewards)?;

        user_stake.total_rewards_claimed += pending_rewards;
        user_stake.last_claim_slot = clock.slot;

        let rewards_pool = &mut ctx.accounts.rewards_pool;
        rewards_pool.total_rewards_distributed += pending_rewards;

        emit!(RewardsClaimed {
            user: ctx.accounts.user.key(),
            amount: pending_rewards,
            slot: clock.slot,
        });

        Ok(())
    }

    pub fn compound_rewards(ctx: Context<CompoundRewards>) -> Result<()> {
        let rewards_pool = &ctx.accounts.rewards_pool;
        require!(!rewards_pool.emergency_pause, ErrorCode::PoolPaused);

        let user_stake = &mut ctx.accounts.user_stake;
        let clock = Clock::get()?;

        let pending_rewards = calculate_rewards(
            user_stake.staked_amount,
            rewards_pool.current_apy,
            user_stake.last_claim_slot,
            clock.slot,
        );

        require!(pending_rewards > 0, ErrorCode::NoRewardsToCompound);

        user_stake.staked_amount += pending_rewards;
        user_stake.last_claim_slot = clock.slot;

        emit!(RewardsCompounded {
            user: ctx.accounts.user.key(),
            amount: pending_rewards,
            new_staked_amount: user_stake.staked_amount,
        });

        Ok(())
    }

    pub fn emergency_pause(ctx: Context<EmergencyPause>, pause: bool) -> Result<()> {
        let rewards_pool = &mut ctx.accounts.rewards_pool;
        rewards_pool.emergency_pause = pause;

        emit!(EmergencyPauseToggled {
            pool: rewards_pool.key(),
            paused: pause,
        });

        Ok(())
    }
}

#[derive(Accounts)]
pub struct InitializeRewardsPool<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + RewardsPool::INIT_SPACE,
        seeds = [b"rewards_pool", reward_mint.key().as_ref()],
        bump
    )]
    pub rewards_pool: Account<'info, RewardsPool>,

    #[account(mut)]
    pub authority: Signer<'info>,

    pub reward_mint: Account<'info, Mint>,

    #[account(
        init,
        payer = authority,
        token::mint = reward_mint,
        token::authority = rewards_pool,
    )]
    pub reward_vault: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct UpdateAPY<'info> {
    #[account(
        mut,
        seeds = [b"rewards_pool", rewards_pool.reward_mint.as_ref()],
        bump = rewards_pool.bump,
        has_one = authority
    )]
    pub rewards_pool: Account<'info, RewardsPool>,

    pub authority: Signer<'info>,
}

#[derive(Accounts)]
pub struct ClaimRewards<'info> {
    #[account(
        mut,
        seeds = [b"rewards_pool", rewards_pool.reward_mint.as_ref()],
        bump = rewards_pool.bump
    )]
    pub rewards_pool: Account<'info, RewardsPool>,

    #[account(mut)]
    pub reward_vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        seeds = [b"user_stake", user.key().as_ref(), rewards_pool.key().as_ref()],
        bump = user_stake.bump
    )]
    pub user_stake: Account<'info, UserStake>,

    #[account(mut)]
    pub user: Signer<'info>,

    #[account(mut)]
    pub user_reward_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct CompoundRewards<'info> {
    #[account(
        seeds = [b"rewards_pool", rewards_pool.reward_mint.as_ref()],
        bump = rewards_pool.bump
    )]
    pub rewards_pool: Account<'info, RewardsPool>,

    #[account(
        mut,
        seeds = [b"user_stake", user.key().as_ref(), rewards_pool.key().as_ref()],
        bump = user_stake.bump
    )]
    pub user_stake: Account<'info, UserStake>,

    #[account(mut)]
    pub user: Signer<'info>,
}

#[derive(Accounts)]
pub struct EmergencyPause<'info> {
    #[account(
        mut,
        seeds = [b"rewards_pool", rewards_pool.reward_mint.as_ref()],
        bump = rewards_pool.bump,
        has_one = authority
    )]
    pub rewards_pool: Account<'info, RewardsPool>,

    pub authority: Signer<'info>,
}

#[account]
#[derive(InitSpace)]
pub struct RewardsPool {
    pub authority: Pubkey,
    pub reward_mint: Pubkey,
    pub reward_vault: Pubkey,
    pub base_apy: u64,
    pub current_apy: u64,
    pub min_apy: u64,
    pub max_apy: u64,
    pub compound_frequency: u64,
    pub total_staked: u64,
    pub total_rewards_distributed: u64,
    pub emergency_pause: bool,
    pub last_update_slot: u64,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct UserStake {
    pub user: Pubkey,
    pub pool: Pubkey,
    pub staked_amount: u64,
    pub total_rewards_claimed: u64,
    pub last_claim_slot: u64,
    pub bump: u8,
}

#[event]
pub struct RewardsPoolInitialized {
    pub pool: Pubkey,
    pub authority: Pubkey,
    pub base_apy: u64,
}

#[event]
pub struct APYUpdated {
    pub pool: Pubkey,
    pub old_apy: u64,
    pub new_apy: u64,
    pub tvl: u64,
}

#[event]
pub struct RewardsClaimed {
    pub user: Pubkey,
    pub amount: u64,
    pub slot: u64,
}

#[event]
pub struct RewardsCompounded {
    pub user: Pubkey,
    pub amount: u64,
    pub new_staked_amount: u64,
}

#[event]
pub struct EmergencyPauseToggled {
    pub pool: Pubkey,
    pub paused: bool,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Rewards pool is paused")]
    PoolPaused,
    #[msg("No rewards to claim")]
    NoRewardsToClaim,
    #[msg("No rewards to compound")]
    NoRewardsToCompound,
    #[msg("Invalid APY parameters")]
    InvalidAPY,
}

fn calculate_dynamic_apy(base_apy: u64, min_apy: u64, max_apy: u64, tvl: u64) -> u64 {
    const TVL_THRESHOLD_LOW: u64 = 1_000_000;
    const TVL_THRESHOLD_HIGH: u64 = 100_000_000;

    if tvl < TVL_THRESHOLD_LOW {
        max_apy
    } else if tvl > TVL_THRESHOLD_HIGH {
        min_apy
    } else {
        let ratio = (tvl - TVL_THRESHOLD_LOW) * 10000 / (TVL_THRESHOLD_HIGH - TVL_THRESHOLD_LOW);
        let apy_range = max_apy - min_apy;
        max_apy - (apy_range * ratio / 10000)
    }
}

fn calculate_rewards(
    staked_amount: u64,
    apy: u64,
    last_claim_slot: u64,
    current_slot: u64,
) -> u64 {
    const SLOTS_PER_YEAR: u64 = 78_840_000;

    let slots_elapsed = current_slot.saturating_sub(last_claim_slot);
    let annual_reward = (staked_amount as u128)
        .checked_mul(apy as u128)
        .unwrap_or(0)
        / 10000;

    let reward = annual_reward
        .checked_mul(slots_elapsed as u128)
        .unwrap_or(0)
        / SLOTS_PER_YEAR as u128;

    reward as u64
}
