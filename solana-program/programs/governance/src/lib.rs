use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};

declare_id!("govnNQF7Z8k9pVwJLzY4XpKj6h1rGE3tqTmE9xKvPp");

#[program]
pub mod governance_program {
    use super::*;

    pub fn initialize_governance(
        ctx: Context<InitializeGovernance>,
        voting_period: i64,
        min_voting_power: u64,
        quorum_percentage: u64,
    ) -> Result<()> {
        let governance = &mut ctx.accounts.governance;
        governance.authority = ctx.accounts.authority.key();
        governance.governance_token = ctx.accounts.governance_token.key();
        governance.voting_period = voting_period;
        governance.min_voting_power = min_voting_power;
        governance.quorum_percentage = quorum_percentage;
        governance.proposal_count = 0;
        governance.bump = ctx.bumps.governance;

        emit!(GovernanceInitialized {
            governance: governance.key(),
            authority: governance.authority,
            voting_period,
        });

        Ok(())
    }

    pub fn create_proposal(
        ctx: Context<CreateProposal>,
        title: String,
        description: String,
        proposal_type: ProposalType,
    ) -> Result<()> {
        let governance = &ctx.accounts.governance;
        let voter_account = &ctx.accounts.voter_account;

        require!(
            voter_account.amount >= governance.min_voting_power,
            ErrorCode::InsufficientVotingPower
        );

        let clock = Clock::get()?;
        let proposal = &mut ctx.accounts.proposal;
        proposal.governance = governance.key();
        proposal.proposer = ctx.accounts.proposer.key();
        proposal.title = title;
        proposal.description = description;
        proposal.proposal_type = proposal_type;
        proposal.start_time = clock.unix_timestamp;
        proposal.end_time = clock.unix_timestamp + governance.voting_period;
        proposal.yes_votes = 0;
        proposal.no_votes = 0;
        proposal.status = ProposalStatus::Active;
        proposal.executed = false;
        proposal.bump = ctx.bumps.proposal;

        let governance = &mut ctx.accounts.governance;
        governance.proposal_count += 1;

        emit!(ProposalCreated {
            proposal: proposal.key(),
            proposer: proposal.proposer,
            title: proposal.title.clone(),
            end_time: proposal.end_time,
        });

        Ok(())
    }

    pub fn cast_vote(
        ctx: Context<CastVote>,
        vote: Vote,
    ) -> Result<()> {
        let proposal = &ctx.accounts.proposal;
        require!(
            proposal.status == ProposalStatus::Active,
            ErrorCode::ProposalNotActive
        );

        let clock = Clock::get()?;
        require!(
            clock.unix_timestamp <= proposal.end_time,
            ErrorCode::VotingPeriodEnded
        );

        let voter_account = &ctx.accounts.voter_account;
        let voting_power = voter_account.amount;

        let vote_record = &mut ctx.accounts.vote_record;
        vote_record.proposal = proposal.key();
        vote_record.voter = ctx.accounts.voter.key();
        vote_record.vote = vote;
        vote_record.voting_power = voting_power;
        vote_record.timestamp = clock.unix_timestamp;
        vote_record.bump = ctx.bumps.vote_record;

        let proposal = &mut ctx.accounts.proposal;
        match vote {
            Vote::Yes => proposal.yes_votes += voting_power,
            Vote::No => proposal.no_votes += voting_power,
        }

        emit!(VoteCast {
            proposal: proposal.key(),
            voter: vote_record.voter,
            vote,
            voting_power,
        });

        Ok(())
    }

    pub fn finalize_proposal(ctx: Context<FinalizeProposal>) -> Result<()> {
        let proposal = &mut ctx.accounts.proposal;
        require!(
            proposal.status == ProposalStatus::Active,
            ErrorCode::ProposalNotActive
        );

        let clock = Clock::get()?;
        require!(
            clock.unix_timestamp > proposal.end_time,
            ErrorCode::VotingPeriodNotEnded
        );

        let governance = &ctx.accounts.governance;
        let total_votes = proposal.yes_votes + proposal.no_votes;
        let total_supply = ctx.accounts.governance_token.supply;

        let quorum_met = (total_votes * 100) >= (total_supply * governance.quorum_percentage);
        let passed = proposal.yes_votes > proposal.no_votes;

        proposal.status = if quorum_met && passed {
            ProposalStatus::Passed
        } else {
            ProposalStatus::Rejected
        };

        emit!(ProposalFinalized {
            proposal: proposal.key(),
            status: proposal.status,
            yes_votes: proposal.yes_votes,
            no_votes: proposal.no_votes,
        });

        Ok(())
    }

    pub fn execute_proposal(ctx: Context<ExecuteProposal>) -> Result<()> {
        let proposal = &mut ctx.accounts.proposal;
        require!(
            proposal.status == ProposalStatus::Passed,
            ErrorCode::ProposalNotPassed
        );
        require!(!proposal.executed, ErrorCode::AlreadyExecuted);

        proposal.executed = true;

        emit!(ProposalExecuted {
            proposal: proposal.key(),
            executor: ctx.accounts.executor.key(),
        });

        Ok(())
    }
}

#[derive(Accounts)]
pub struct InitializeGovernance<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + Governance::INIT_SPACE,
        seeds = [b"governance", governance_token.key().as_ref()],
        bump
    )]
    pub governance: Account<'info, Governance>,

    #[account(mut)]
    pub authority: Signer<'info>,

    pub governance_token: Account<'info, Mint>,

    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
#[instruction(title: String)]
pub struct CreateProposal<'info> {
    #[account(
        seeds = [b"governance", governance.governance_token.as_ref()],
        bump = governance.bump
    )]
    pub governance: Account<'info, Governance>,

    #[account(
        init,
        payer = proposer,
        space = 8 + Proposal::INIT_SPACE,
        seeds = [b"proposal", governance.key().as_ref(), &governance.proposal_count.to_le_bytes()],
        bump
    )]
    pub proposal: Account<'info, Proposal>,

    #[account(mut)]
    pub proposer: Signer<'info>,

    pub voter_account: Account<'info, TokenAccount>,

    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct CastVote<'info> {
    #[account(
        seeds = [b"governance", governance.governance_token.as_ref()],
        bump = governance.bump
    )]
    pub governance: Account<'info, Governance>,

    #[account(
        mut,
        seeds = [b"proposal", proposal.governance.as_ref(), &(governance.proposal_count - 1).to_le_bytes()],
        bump = proposal.bump
    )]
    pub proposal: Account<'info, Proposal>,

    #[account(
        init,
        payer = voter,
        space = 8 + VoteRecord::INIT_SPACE,
        seeds = [b"vote_record", proposal.key().as_ref(), voter.key().as_ref()],
        bump
    )]
    pub vote_record: Account<'info, VoteRecord>,

    #[account(mut)]
    pub voter: Signer<'info>,

    pub voter_account: Account<'info, TokenAccount>,

    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct FinalizeProposal<'info> {
    #[account(
        seeds = [b"governance", governance.governance_token.as_ref()],
        bump = governance.bump
    )]
    pub governance: Account<'info, Governance>,

    pub governance_token: Account<'info, Mint>,

    #[account(
        mut,
        seeds = [b"proposal", proposal.governance.as_ref(), &(governance.proposal_count - 1).to_le_bytes()],
        bump = proposal.bump
    )]
    pub proposal: Account<'info, Proposal>,
}

#[derive(Accounts)]
pub struct ExecuteProposal<'info> {
    #[account(
        seeds = [b"governance", governance.governance_token.as_ref()],
        bump = governance.bump,
        has_one = authority
    )]
    pub governance: Account<'info, Governance>,

    #[account(
        mut,
        seeds = [b"proposal", proposal.governance.as_ref(), &(governance.proposal_count - 1).to_le_bytes()],
        bump = proposal.bump
    )]
    pub proposal: Account<'info, Proposal>,

    pub authority: Signer<'info>,

    pub executor: Signer<'info>,
}

#[account]
#[derive(InitSpace)]
pub struct Governance {
    pub authority: Pubkey,
    pub governance_token: Pubkey,
    pub voting_period: i64,
    pub min_voting_power: u64,
    pub quorum_percentage: u64,
    pub proposal_count: u64,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct Proposal {
    pub governance: Pubkey,
    pub proposer: Pubkey,
    #[max_len(128)]
    pub title: String,
    #[max_len(512)]
    pub description: String,
    pub proposal_type: ProposalType,
    pub start_time: i64,
    pub end_time: i64,
    pub yes_votes: u64,
    pub no_votes: u64,
    pub status: ProposalStatus,
    pub executed: bool,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct VoteRecord {
    pub proposal: Pubkey,
    pub voter: Pubkey,
    pub vote: Vote,
    pub voting_power: u64,
    pub timestamp: i64,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum ProposalType {
    ParameterChange,
    TreasurySpend,
    ProtocolUpgrade,
    General,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum ProposalStatus {
    Active,
    Passed,
    Rejected,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum Vote {
    Yes,
    No,
}

#[event]
pub struct GovernanceInitialized {
    pub governance: Pubkey,
    pub authority: Pubkey,
    pub voting_period: i64,
}

#[event]
pub struct ProposalCreated {
    pub proposal: Pubkey,
    pub proposer: Pubkey,
    pub title: String,
    pub end_time: i64,
}

#[event]
pub struct VoteCast {
    pub proposal: Pubkey,
    pub voter: Pubkey,
    pub vote: Vote,
    pub voting_power: u64,
}

#[event]
pub struct ProposalFinalized {
    pub proposal: Pubkey,
    pub status: ProposalStatus,
    pub yes_votes: u64,
    pub no_votes: u64,
}

#[event]
pub struct ProposalExecuted {
    pub proposal: Pubkey,
    pub executor: Pubkey,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Insufficient voting power")]
    InsufficientVotingPower,
    #[msg("Proposal is not active")]
    ProposalNotActive,
    #[msg("Voting period has ended")]
    VotingPeriodEnded,
    #[msg("Voting period has not ended")]
    VotingPeriodNotEnded,
    #[msg("Proposal has not passed")]
    ProposalNotPassed,
    #[msg("Proposal already executed")]
    AlreadyExecuted,
}
