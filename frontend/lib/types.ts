export type Site = "dk" | "fd";
export type LineupStatus = "confirmed" | "expected" | "unconfirmed" | "dnp";
export type DataStatus = "live" | "cached" | "partial" | "mock" | "error";

export interface GameSummary {
  game_id: number;
  game_time: string;
  away_team: string;
  home_team: string;
  away_starter?: Starter | null;
  home_starter?: Starter | null;
  away_lineup_confirmed: boolean;
  home_lineup_confirmed: boolean;
  venue?: string | null;
}

export interface Starter {
  name: string;
  mlbam_id?: number | null;
  hand?: "L" | "R" | null;
}

export interface Player {
  mlbam_id: number;
  name: string;
  team: string;
  opponent: string;
  position: string[];
  position_dk?: string[] | null;
  position_fd?: string[] | null;
  salary_dk: number;
  salary_fd: number;
  external_id_dk?: string | null;
  external_id_fd?: string | null;
  name_id_dk?: string | null;
  name_id_fd?: string | null;
  salary_source_dk?: string | null;
  salary_source_fd?: string | null;
  source_projection_dk?: number | null;
  source_projection_fd?: number | null;
  pitcher_last_start_date?: string | null;
  pitcher_days_rest?: number | null;
  pitcher_last_start_pitches?: number | null;
  pitcher_avg_pitches_last_3?: number | null;
  pitcher_avg_innings_last_3?: number | null;
  pitcher_workload_risk?: "low" | "medium" | "high" | "unknown" | null;
  pitcher_workload_factor?: number | null;
  batting_order: number | null;
  opposing_pitcher: string | null;
  opposing_pitcher_hand: "L" | "R" | null;
  lineup_status: LineupStatus;
  projected_dk: number;
  projected_fd: number;
  projection_source:
    | "15d_counts_cached_season_splits"
    | "season_with_15d_form_blend"
    | "season_avg_fallback"
    | "pitcher_season_rates"
    | "daily_fantasy_fuel"
    | "mock_projection"
    | "user_override";
  last_15_avg_dk: number;
  vs_lhp_avg: number;
  vs_rhp_avg: number;
  last_updated: string;
}

export interface PlayerPoolResponse {
  game_date: string;
  site?: Site | null;
  slate_key?: string | null;
  last_updated: string;
  data_status: DataStatus;
  warnings: string[];
  changes: {
    added: number;
    removed: number;
    batting_order_changed: number;
    status_changed: number;
  };
  games: GameSummary[];
  players: Player[];
  message?: string | null;
}

export type SlateType = "classic" | "showdown" | "tiers" | "unknown";

export interface SlateSummary {
  site: Site;
  slate_key: string;
  provider: string;
  provider_slate_id: string;
  name: string;
  slate_type: SlateType;
  game_date: string;
  start_time: string;
  lock_time?: string | null;
  game_count: number;
  team_count: number;
  game_ids: number[];
  teams: string[];
  is_default: boolean;
  fetched_at: string;
}

export interface SlateListResponse {
  game_date: string;
  site: Site;
  last_updated: string;
  slates: SlateSummary[];
  warnings: string[];
}

export interface OptimizerSettings {
  stack_team: string | null;
  stack_count: number;
  pitcher_vs_batter_same_team: "allow" | "avoid";
  min_salary_used: number;
  unique_lineups: boolean;
}

export interface PlayerInput {
  mlbam_id: number;
  name: string;
  team: string;
  opponent?: string | null;
  position: string[];
  salary: number;
  projected_points: number;
  lock: boolean;
  exclude: boolean;
  max_exposure: number;
  lineup_status?: LineupStatus | null;
  external_id?: string | null;
  name_id?: string | null;
}

export interface OptimizeRequest {
  site: Site;
  num_lineups: number;
  players: PlayerInput[];
  settings: OptimizerSettings;
}

export interface LineupPlayer {
  mlbam_id: number;
  name: string;
  position_slot: string;
  salary: number;
  projected_points: number;
  team: string;
  external_id?: string | null;
  name_id?: string | null;
}

export interface Lineup {
  lineup_number: number;
  players: LineupPlayer[];
  total_salary: number;
  projected_points: number;
}

export interface OptimizeResponse {
  lineups: Lineup[];
  solve_time_ms: number;
  warnings: string[];
}
