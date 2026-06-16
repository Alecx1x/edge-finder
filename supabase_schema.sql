-- Edge Finder — Supabase schema
-- Run this ONCE in your Supabase project:  Dashboard > SQL Editor > New query > paste > Run.
-- The app then reads/writes these tables with your project URL + anon key over REST.
--
-- Note: public_a / public_b on odds_history are NOT in the minimal spec — they are
-- added (nullable) so the "sharp money vs public %" indicator keeps working. Drop
-- them if you want the strict minimal schema; the app treats them as optional.

-- ---------------------------------------------------------------------------
create table if not exists public.odds_history (
    id              bigint generated always as identity primary key,
    fighter_a       text,
    fighter_b       text,
    sport           text,
    odds_a          double precision,
    odds_b          double precision,
    implied_prob_a  double precision,
    implied_prob_b  double precision,
    public_a        double precision,   -- optional: public ticket % on side A
    public_b        double precision,   -- optional: public ticket % on side B
    "timestamp"     timestamptz not null default now()
);

create table if not exists public.bets_log (
    id          bigint generated always as identity primary key,
    fighter_a   text,
    fighter_b   text,
    sport       text,
    odds_a      double precision,
    odds_b      double precision,
    bet_side    text,                    -- 'a' | 'b'
    bet_name    text,
    bet_odds    double precision,
    edge        double precision,
    model_prob  double precision,
    stake       double precision,
    result      text,                    -- null | 'win' | 'loss' | 'push'
    "timestamp" timestamptz not null default now(),
    settled_at  timestamptz,
    -- closing-line-value tracking (Phase 4); all optional / nullable
    close_odds        double precision,  -- closing odds for the side you bet
    other_close_odds  double precision,  -- closing odds for the other side
    close_prob        double precision,  -- de-vigged closing fair prob (bet side)
    clv_pct           double precision,  -- your price vs the close (decimal basis)
    ev_vs_close       double precision,  -- EV of the bet judged by the closing line
    beat              boolean,           -- did you beat the close?
    captured_at       timestamptz
);

-- If bets_log already existed before Phase 4, add the CLV columns in place:
alter table public.bets_log add column if not exists close_odds       double precision;
alter table public.bets_log add column if not exists other_close_odds double precision;
alter table public.bets_log add column if not exists close_prob       double precision;
alter table public.bets_log add column if not exists clv_pct          double precision;
alter table public.bets_log add column if not exists ev_vs_close      double precision;
alter table public.bets_log add column if not exists beat             boolean;
alter table public.bets_log add column if not exists captured_at      timestamptz;

create table if not exists public.matchup_history (
    id          bigint generated always as identity primary key,
    fighter_a   text,
    fighter_b   text,
    sport       text,
    edge        double precision,
    edge_a      double precision,
    side        text,
    "timestamp" timestamptz not null default now()
);

create table if not exists public.presets (
    id           bigint generated always as identity primary key,
    name         text not null,
    sport        text,
    weights_json jsonb not null default '{}'::jsonb,
    is_default   boolean not null default false,
    created_at   timestamptz not null default now()
);

-- helpful indexes for the per-matchup lookups the app does
create index if not exists odds_history_match_idx   on public.odds_history   (sport, fighter_a, fighter_b);
create index if not exists matchup_history_match_idx on public.matchup_history (sport, fighter_a, fighter_b);
create index if not exists presets_default_idx       on public.presets        (is_default);

-- ---------------------------------------------------------------------------
-- Row Level Security. This is a local single-user tool, so the anon role gets
-- full access to your own project's tables. Tighten these if you expose the URL.
alter table public.odds_history    enable row level security;
alter table public.bets_log        enable row level security;
alter table public.matchup_history enable row level security;
alter table public.presets         enable row level security;

create policy "anon full access" on public.odds_history
    for all to anon using (true) with check (true);
create policy "anon full access" on public.bets_log
    for all to anon using (true) with check (true);
create policy "anon full access" on public.matchup_history
    for all to anon using (true) with check (true);
create policy "anon full access" on public.presets
    for all to anon using (true) with check (true);
