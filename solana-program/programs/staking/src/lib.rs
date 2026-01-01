use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};

declare_id!("stkePW8VgQF8CxNm6k7q1FKzGvzRgJ7xNJ8jT6ZVXy");

#[program]
pub mod staking_program {
    use super::*;

    pub fn initialize_staking_pool(
        ctx: Context<InitializeStakingPool>,
        unbonding_period_7: u64,
        unbonding_period_14: u64,
        unbonding_period_30: u64,
        reward_multiplier_7: u64,
        reward_multiplier_14: u64,
        reward_multiplier_30: u64,
        min_stake_amount: u64,
    ) -> Result<()> {
        let staking_pool = &mut ctx.accounts.staking_pool;
        staking_pool.authority = ctx.accounts.authority.key();
        staking_pool.stake_mint = ctx.accounts.stake_mint.key();
        staking_pool.stake_vault = ctx.accounts.stake_vault.key();
        staking_pool.unbonding_period_7 = unbonding_period_7;
        staking_pool.unbonding_period_14 = unbonding_period_14;
        staking_pool.unbonding_period_30 = unbonding_period_30;
        staking_pool.reward_multiplier_7 = reward_multiplier_7;
        staking_pool.reward_multiplier_14 = reward_multiplier_14;
        staking_pool.reward_multiplier_30 = reward_multiplier_30;
        staking_pool.min_stake_amount = min_stake_amount;
        staking_pool.total_staked = 0;
        staking_pool.total_stakers = 0;
        staking_pool.emergency_pause = false;
        staking_pool.bump = ctx.bumps.staking_pool;

        emit!(StakingPoolInitialized {
            pool: staking_pool.key(),
            authority: staking_pool.authority,
            min_stake_amount,
        });

        Ok(())
    }

    pub fn stake_tokens(
        ctx: Context<StakeTokens>,
        amount: u64,
        lock_period: LockPeriod,
    ) -> Result<()> {
        let staking_pool = &ctx.accounts.staking_pool;
        require!(!staking_pool.emergency_pause, ErrorCode::PoolPaused);
        require!(amount >= staking_pool.min_stake_amount, ErrorCode::BelowMinStake);

        let clock = Clock::get()?;
        let unbonding_end = clock.unix_timestamp
            + match lock_period {
                LockPeriod::Days7 => staking_pool.unbonding_period_7 as i64,
                LockPeriod::Days14 => staking_pool.unbonding_period_14 as i64,
                LockPeriod::Days30 => staking_pool.unbonding_period_30 as i64,
            };

        let reward_multiplier = match lock_period {
            LockPeriod::Days7 => staking_pool.reward_multiplier_7,
            LockPeriod::Days14 => staking_pool.reward_multiplier_14,
            LockPeriod::Days30 => staking_pool.reward_multiplier_30,
        };

        let cpi_accounts = Transfer {
            from: ctx.accounts.user_token_account.to_account_info(),
            to: ctx.accounts.stake_vault.to_account_info(),
            authority: ctx.accounts.user.to_account_info(),
        };
        let cpi_program = ctx.accounts.token_program.to_account_info();
        let cpi_ctx = CpiContext::new(cpi_program, cpi_accounts);

        token::transfer(cpi_ctx, amount)?;

        let stake_position = &mut ctx.accounts.stake_position;
        stake_position.user = ctx.accounts.user.key();
        stake_position.pool = staking_pool.key();
        stake_position.amount = amount;
        stake_position.lock_period = lock_period;
        stake_position.reward_multiplier = reward_multiplier;
        stake_position.stake_timestamp = clock.unix_timestamp;
        stake_position.unbonding_end = unbonding_end;
        stake_position.is_unbonding = false;
        stake_position.bump = ctx.bumps.stake_position;

        let staking_pool = &mut ctx.accounts.staking_pool;
        staking_pool.total_staked += amount;
        staking_pool.total_stakers += 1;

        emit!(TokensStaked {
            user: ctx.accounts.user.key(),
            amount,
            lock_period,
            unbonding_end,
        });

        Ok(())
    }

    pub fn initiate_unstake(ctx: Context<InitiateUnstake>) -> Result<()> {
        let staking_pool = &ctx.accounts.staking_pool;
        require!(!staking_pool.emergency_pause, ErrorCode::PoolPaused);

        let stake_position = &mut ctx.accounts.stake_position;
        require!(!stake_position.is_unbonding, ErrorCode::AlreadyUnbonding);

        stake_position.is_unbonding = true;

        emit!(UnstakeInitiated {
            user: ctx.accounts.user.key(),
            amount: stake_position.amount,
            unbonding_end: stake_position.unbonding_end,
        });

        Ok(())
    }

    pub fn complete_unstake(ctx: Context<CompleteUnstake>) -> Result<()> {
        let staking_pool = &ctx.accounts.staking_pool;
        let stake_position = &ctx.accounts.stake_position;

        require!(stake_position.is_unbonding, ErrorCode::NotUnbonding);

        let clock = Clock::get()?;
        require!(
            clock.unix_timestamp >= stake_position.unbonding_end,
            ErrorCode::UnbondingPeriodNotComplete
        );

        let seeds = &[
            b"staking_pool",
            staking_pool.stake_mint.as_ref(),
            &[staking_pool.bump],
        ];
        let signer = &[&seeds[..]];

        let cpi_accounts = Transfer {
            from: ctx.accounts.stake_vault.to_account_info(),
            to: ctx.accounts.user_token_account.to_account_info(),
            authority: staking_pool.to_account_info(),
        };
        let cpi_program = ctx.accounts.token_program.to_account_info();
        let cpi_ctx = CpiContext::new_with_signer(cpi_program, cpi_accounts, signer);

        token::transfer(cpi_ctx, stake_position.amount)?;

        let staking_pool = &mut ctx.accounts.staking_pool;
        staking_pool.total_staked -= stake_position.amount;
        staking_pool.total_stakers -= 1;

        emit!(UnstakeCompleted {
            user: ctx.accounts.user.key(),
            amount: stake_position.amount,
        });

        Ok(())
    }

    pub fn emergency_withdraw(ctx: Context<EmergencyWithdraw>) -> Result<()> {
        let staking_pool = &ctx.accounts.staking_pool;
        require!(staking_pool.emergency_pause, ErrorCode::PoolNotPaused);

        let stake_position = &ctx.accounts.stake_position;

        let seeds = &[
            b"staking_pool",
            staking_pool.stake_mint.as_ref(),
            &[staking_pool.bump],
        ];
        let signer = &[&seeds[..]];

        let cpi_accounts = Transfer {
            from: ctx.accounts.stake_vault.to_account_info(),
            to: ctx.accounts.user_token_account.to_account_info(),
            authority: staking_pool.to_account_info(),
        };
        let cpi_program = ctx.accounts.token_program.to_account_info();
        let cpi_ctx = CpiContext::new_with_signer(cpi_program, cpi_accounts, signer);

        token::transfer(cpi_ctx, stake_position.amount)?;

        let staking_pool = &mut ctx.accounts.staking_pool;
        staking_pool.total_staked -= stake_position.amount;
        staking_pool.total_stakers -= 1;

        emit!(EmergencyWithdrawal {
            user: ctx.accounts.user.key(),
            amount: stake_position.amount,
        });

        Ok(())
    }

    pub fn toggle_emergency_pause(ctx: Context<ToggleEmergencyPause>, pause: bool) -> Result<()> {
        let staking_pool = &mut ctx.accounts.staking_pool;
        staking_pool.emergency_pause = pause;

        emit!(EmergencyPauseToggled {
            pool: staking_pool.key(),
            paused: pause,
        });

        Ok(())
    }
}

#[derive(Accounts)]
pub struct InitializeStakingPool<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + StakingPool::INIT_SPACE,
        seeds = [b"staking_pool", stake_mint.key().as_ref()],
        bump
    )]
    pub staking_pool: Account<'info, StakingPool>,

    #[account(mut)]
    pub authority: Signer<'info>,

    pub stake_mint: Account<'info, Mint>,

    #[account(
        init,
        payer = authority,
        token::mint = stake_mint,
        token::authority = staking_pool,
    )]
    pub stake_vault: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct StakeTokens<'info> {
    #[account(
        mut,
        seeds = [b"staking_pool", staking_pool.stake_mint.as_ref()],
        bump = staking_pool.bump
    )]
    pub staking_pool: Account<'info, StakingPool>,

    #[account(mut)]
    pub stake_vault: Account<'info, TokenAccount>,

    #[account(
        init,
        payer = user,
        space = 8 + StakePosition::INIT_SPACE,
        seeds = [b"stake_position", user.key().as_ref(), staking_pool.key().as_ref()],
        bump
    )]
    pub stake_position: Account<'info, StakePosition>,

    #[account(mut)]
    pub user: Signer<'info>,

    #[account(mut)]
    pub user_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct InitiateUnstake<'info> {
    #[account(
        seeds = [b"staking_pool", staking_pool.stake_mint.as_ref()],
        bump = staking_pool.bump
    )]
    pub staking_pool: Account<'info, StakingPool>,

    #[account(
        mut,
        seeds = [b"stake_position", user.key().as_ref(), staking_pool.key().as_ref()],
        bump = stake_position.bump,
        has_one = user
    )]
    pub stake_position: Account<'info, StakePosition>,

    pub user: Signer<'info>,
}

#[derive(Accounts)]
pub struct CompleteUnstake<'info> {
    #[account(
        mut,
        seeds = [b"staking_pool", staking_pool.stake_mint.as_ref()],
        bump = staking_pool.bump
    )]
    pub staking_pool: Account<'info, StakingPool>,

    #[account(mut)]
    pub stake_vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        seeds = [b"stake_position", user.key().as_ref(), staking_pool.key().as_ref()],
        bump = stake_position.bump,
        has_one = user,
        close = user
    )]
    pub stake_position: Account<'info, StakePosition>,

    #[account(mut)]
    pub user: Signer<'info>,

    #[account(mut)]
    pub user_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct EmergencyWithdraw<'info> {
    #[account(
        mut,
        seeds = [b"staking_pool", staking_pool.stake_mint.as_ref()],
        bump = staking_pool.bump
    )]
    pub staking_pool: Account<'info, StakingPool>,

    #[account(mut)]
    pub stake_vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        seeds = [b"stake_position", user.key().as_ref(), staking_pool.key().as_ref()],
        bump = stake_position.bump,
        has_one = user,
        close = user
    )]
    pub stake_position: Account<'info, StakePosition>,

    #[account(mut)]
    pub user: Signer<'info>,

    #[account(mut)]
    pub user_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct ToggleEmergencyPause<'info> {
    #[account(
        mut,
        seeds = [b"staking_pool", staking_pool.stake_mint.as_ref()],
        bump = staking_pool.bump,
        has_one = authority
    )]
    pub staking_pool: Account<'info, StakingPool>,

    pub authority: Signer<'info>,
}

#[account]
#[derive(InitSpace)]
pub struct StakingPool {
    pub authority: Pubkey,
    pub stake_mint: Pubkey,
    pub stake_vault: Pubkey,
    pub unbonding_period_7: u64,
    pub unbonding_period_14: u64,
    pub unbonding_period_30: u64,
    pub reward_multiplier_7: u64,
    pub reward_multiplier_14: u64,
    pub reward_multiplier_30: u64,
    pub min_stake_amount: u64,
    pub total_staked: u64,
    pub total_stakers: u64,
    pub emergency_pause: bool,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct StakePosition {
    pub user: Pubkey,
    pub pool: Pubkey,
    pub amount: u64,
    pub lock_period: LockPeriod,
    pub reward_multiplier: u64,
    pub stake_timestamp: i64,
    pub unbonding_end: i64,
    pub is_unbonding: bool,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum LockPeriod {
    Days7,
    Days14,
    Days30,
}

#[event]
pub struct StakingPoolInitialized {
    pub pool: Pubkey,
    pub authority: Pubkey,
    pub min_stake_amount: u64,
}

#[event]
pub struct TokensStaked {
    pub user: Pubkey,
    pub amount: u64,
    pub lock_period: LockPeriod,
    pub unbonding_end: i64,
}

#[event]
pub struct UnstakeInitiated {
    pub user: Pubkey,
    pub amount: u64,
    pub unbonding_end: i64,
}

#[event]
pub struct UnstakeCompleted {
    pub user: Pubkey,
    pub amount: u64,
}

#[event]
pub struct EmergencyWithdrawal {
    pub user: Pubkey,
    pub amount: u64,
}

#[event]
pub struct EmergencyPauseToggled {
    pub pool: Pubkey,
    pub paused: bool,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Staking pool is paused")]
    PoolPaused,
    #[msg("Staking pool is not paused")]
    PoolNotPaused,
    #[msg("Amount below minimum stake")]
    BelowMinStake,
    #[msg("Already unbonding")]
    AlreadyUnbonding,
    #[msg("Not unbonding")]
    NotUnbonding,
    #[msg("Unbonding period not complete")]
    UnbondingPeriodNotComplete,
}
