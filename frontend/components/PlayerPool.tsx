"use client";

import { Ban, Loader2, Lock, Search, Unlock, Zap } from "lucide-react";
import { useMemo, useState } from "react";
import type { Player, Site } from "@/lib/types";

interface PlayerPoolProps {
  players: Player[];
  site: Site;
  numLineups: number;
  overriddenPlayers: Record<string, number>;
  salaryOverrides: Record<string, { salary?: number; positions?: string[] }>;
  exposureOverrides: Record<string, number>;
  lockedPlayers: Record<string, boolean>;
  excludedPlayers: Record<string, boolean>;
  isOptimizing: boolean;
  optimizingMessage: string;
  onOptimize: () => void;
  onProjectionOverride: (playerId: string, projection: number) => void;
  onExposureChange: (playerId: string, exposure: number) => void;
  onLockToggle: (playerId: string) => void;
  onExcludeToggle: (playerId: string) => void;
  salaryWarning?: string;
  lastUpdated?: string;
}

const positions = ["All", "P", "C", "1B", "2B", "3B", "SS", "OF"];

export function PlayerPool({
  players,
  site,
  numLineups,
  overriddenPlayers,
  salaryOverrides,
  exposureOverrides,
  lockedPlayers,
  excludedPlayers,
  isOptimizing,
  optimizingMessage,
  onOptimize,
  onProjectionOverride,
  onExposureChange,
  onLockToggle,
  onExcludeToggle,
  salaryWarning,
  lastUpdated,
}: PlayerPoolProps) {
  const [search, setSearch] = useState("");
  const [positionFilter, setPositionFilter] = useState("All");
  const [confirmedOnly, setConfirmedOnly] = useState(false);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return players
      .filter((player) => !query || player.name.toLowerCase().includes(query))
      .filter((player) => {
        const playerPositions = salaryOverrides[String(player.mlbam_id)]?.positions ?? player.position;
        return positionFilter === "All" || playerPositions.includes(positionFilter);
      })
      .filter((player) => !confirmedOnly || player.lineup_status === "confirmed")
      .sort((a, b) => {
        const dnpA = a.lineup_status === "dnp" ? 1 : 0;
        const dnpB = b.lineup_status === "dnp" ? 1 : 0;
        if (dnpA !== dnpB) return dnpA - dnpB;
        return projectionFor(b, site, overriddenPlayers) - projectionFor(a, site, overriddenPlayers);
      });
  }, [players, search, positionFilter, confirmedOnly, site, overriddenPlayers, salaryOverrides]);

  const confirmedCount = players.filter((player) => player.lineup_status === "confirmed").length;
  const dnpCount = players.filter((player) => player.lineup_status === "dnp").length;
  const excludedCount = Object.values(excludedPlayers).filter(Boolean).length;
  const unconfirmedCount = players.length - confirmedCount - dnpCount;
  const lastUpdatedStr = lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : "waiting";

  return (
    <section className="flex min-h-full flex-col bg-white/70 md:h-full md:min-h-0">
      <div className="border-b border-border/80 px-4 py-3 md:px-5 md:py-4">
        <label className="relative block">
          <Search className="absolute left-3 top-2.5 text-muted-foreground" size={16} />
          <input
            className="focus-ring h-10 w-full rounded-xl border border-border bg-white py-2 pl-9 pr-3 text-sm shadow-sm"
            placeholder="Search players"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </div>

      <div className="scrollbar-none flex gap-2 overflow-x-auto border-b border-border/80 bg-muted/40 px-4 py-2 md:px-5">
        <span className="shrink-0 whitespace-nowrap rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-[10px] font-medium text-green-700">
          {confirmedCount} confirmed
        </span>
        {unconfirmedCount > 0 ? (
          <span className="shrink-0 whitespace-nowrap rounded-full border border-yellow-200 bg-yellow-50 px-2.5 py-1 text-[10px] font-medium text-yellow-700">
            {unconfirmedCount} unconfirmed
          </span>
        ) : null}
        {dnpCount > 0 ? (
          <span className="shrink-0 whitespace-nowrap rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-[10px] font-medium text-red-700">
            {dnpCount} DNP - excluded
          </span>
        ) : null}
        {excludedCount > 0 ? (
          <span className="shrink-0 whitespace-nowrap rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-[10px] font-medium text-red-700">
            {excludedCount} excluded
          </span>
        ) : null}
        <span className="ml-auto shrink-0 whitespace-nowrap text-[10px] text-muted-foreground">
          Updated {lastUpdatedStr}
        </span>
      </div>

      <div className="scrollbar-none flex gap-1.5 overflow-x-auto border-b border-border/80 px-4 py-2 md:px-5">
        {positions.map((position) => (
          <button
            key={position}
            onClick={() => setPositionFilter(position)}
            className={`focus-ring shrink-0 whitespace-nowrap rounded-full px-3 py-1 text-xs transition-colors ${
              positionFilter === position
                ? "border border-primary/20 bg-primary/10 font-medium text-primary"
                : "border border-border bg-white text-muted-foreground hover:text-primary"
            }`}
            type="button"
          >
            {position}
          </button>
        ))}
        <button
          onClick={() => setConfirmedOnly((value) => !value)}
          className={`focus-ring shrink-0 whitespace-nowrap rounded-full px-3 py-1 text-xs transition-colors ${
            confirmedOnly
              ? "border border-primary/20 bg-primary/10 font-medium text-primary"
              : "border border-border bg-white text-muted-foreground hover:text-primary"
          }`}
          type="button"
        >
          ✓ Confirmed only
        </button>
      </div>

      <div className="hidden items-center gap-2 border-b border-border/80 bg-muted/40 px-4 py-2 text-xs font-medium text-muted-foreground md:flex md:px-5">
        <span className="min-w-0 flex-1">Player</span>
        <span className="w-12 shrink-0 text-right">Proj</span>
        <span className="w-12 shrink-0 text-right">Salary</span>
        <span className="w-20 shrink-0" />
      </div>

      <div className="flex-1 md:min-h-0 md:overflow-y-auto">
        {filtered.map((player) => (
          <PlayerRow
            key={player.mlbam_id}
            player={player}
            site={site}
            projection={projectionFor(player, site, overriddenPlayers)}
            salary={salaryFor(player, site, salaryOverrides)}
            positions={salaryOverrides[String(player.mlbam_id)]?.positions ?? player.position}
            locked={Boolean(lockedPlayers[String(player.mlbam_id)])}
            excluded={Boolean(excludedPlayers[String(player.mlbam_id)])}
            exposure={exposureOverrides[String(player.mlbam_id)] ?? 1}
            onLock={() => onLockToggle(String(player.mlbam_id))}
            onExclude={() => onExcludeToggle(String(player.mlbam_id))}
            onProjectionEdit={(projection) => onProjectionOverride(String(player.mlbam_id), projection)}
            onExposureChange={(exposure) => onExposureChange(String(player.mlbam_id), exposure)}
          />
        ))}
      </div>

      <div className="sticky bottom-0 shrink-0 bg-gradient-to-t from-white via-white to-transparent px-4 pb-4 pt-2 md:static md:bg-none md:bg-transparent md:px-4 md:pb-4 md:pt-2">
        {salaryWarning ? (
          <p className="mb-2 rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
            {salaryWarning}
          </p>
        ) : null}
        <button
          onClick={onOptimize}
          disabled={isOptimizing || !players.length}
          className="focus-ring flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3 text-sm font-semibold text-primary-foreground shadow-lg shadow-teal-900/15 transition-transform hover:-translate-y-0.5 active:scale-[0.98] disabled:translate-y-0 disabled:opacity-60"
          type="button"
        >
          {isOptimizing ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              {optimizingMessage}
            </>
          ) : (
            <>
              <Zap className="h-4 w-4" />
              Optimize {numLineups} lineups · {site.toUpperCase()}
            </>
          )}
        </button>
      </div>
    </section>
  );
}

interface PlayerRowProps {
  player: Player;
  site: Site;
  projection: number;
  salary: number;
  positions: string[];
  locked: boolean;
  excluded: boolean;
  exposure: number;
  onLock: () => void;
  onExclude: () => void;
  onProjectionEdit: (projection: number) => void;
  onExposureChange: (exposure: number) => void;
}

function PlayerRow({
  player,
  projection,
  salary,
  positions,
  locked,
  excluded,
  exposure,
  onLock,
  onExclude,
  onProjectionEdit,
  onExposureChange,
}: PlayerRowProps) {
  const [editing, setEditing] = useState(false);
  const [editVal, setEditVal] = useState(projection.toFixed(1));
  const isDnp = player.lineup_status === "dnp";
  const inactive = isDnp || excluded;

  const statusBadge = {
    confirmed: <span className="rounded-md bg-green-50 px-1.5 py-0.5 text-[9px] font-medium text-green-700">✓</span>,
    expected: <span className="rounded-md bg-yellow-50 px-1.5 py-0.5 text-[9px] font-medium text-yellow-700">~</span>,
    unconfirmed: null,
    dnp: <span className="rounded-md bg-red-50 px-1.5 py-0.5 text-[9px] font-medium text-red-700">DNP</span>,
  }[player.lineup_status];

  function saveProjection() {
    setEditing(false);
    const value = Number.parseFloat(editVal);
    if (Number.isFinite(value)) onProjectionEdit(value);
  }

  return (
    <div
      className={`flex items-center gap-2 border-b border-border/70 px-4 py-2.5 transition-colors last:border-0 hover:bg-muted/30 md:px-5 md:py-2 ${
        inactive ? "opacity-40" : ""
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className={`min-w-0 truncate text-sm font-medium md:text-[13px] ${isDnp ? "line-through" : ""}`}>
            {player.name}
          </span>
          {statusBadge}
          {locked ? <span className="ml-1 rounded-md bg-green-50 px-1.5 py-0.5 text-[10px] font-medium text-green-800">Lock</span> : null}
          {excluded ? <span className="ml-1 rounded-md bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700">Excluded</span> : null}
        </div>
        <div className="mt-0.5 truncate text-[11px] text-muted-foreground md:text-[10px]">
          {positions.join("/")} · {player.team}
          {player.opposing_pitcher ? ` · vs ${player.opposing_pitcher} (${player.opposing_pitcher_hand ?? "?"})` : ""}
          {player.batting_order ? ` · Bat ${player.batting_order}` : ""}
        </div>
      </div>

      <div className="mr-2 shrink-0 text-right md:mr-0 md:w-12">
        {editing ? (
          <input
            autoFocus
            className="focus-ring w-14 rounded-md border border-border bg-white px-1 py-0.5 text-right text-sm font-medium shadow-sm"
            value={editVal}
            onChange={(event) => setEditVal(event.target.value)}
            onBlur={saveProjection}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
            }}
          />
        ) : (
          <button
            onClick={() => {
              if (!isDnp) {
                setEditVal(projection.toFixed(1));
                setEditing(true);
              }
            }}
            className="focus-ring rounded-md px-1 text-sm font-semibold tabular-nums transition-colors hover:text-primary"
            type="button"
          >
            {isDnp ? "-" : projection.toFixed(1)}
          </button>
        )}
        <div className="text-[11px] text-muted-foreground md:hidden">${(salary / 1000).toFixed(1)}k</div>
      </div>

      <div className="hidden w-12 shrink-0 text-right text-[11px] text-muted-foreground md:block">
        ${(salary / 1000).toFixed(1)}k
      </div>

      <input
        aria-label={`${player.name} max exposure`}
        className="hidden"
        max={100}
        min={0}
        onChange={(event) => onExposureChange(Math.max(0, Math.min(100, Number(event.target.value))) / 100)}
        step={5}
        type="number"
        value={Math.round(exposure * 100)}
      />

      <button
        onClick={() => {
          if (!isDnp && !excluded) onLock();
        }}
        disabled={isDnp || excluded}
        className={`focus-ring flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-30 ${
          locked ? "text-green-700" : "text-muted-foreground"
        }`}
        aria-label={locked ? "Unlock" : "Lock"}
        type="button"
      >
        {locked ? <Lock size={14} /> : <Unlock size={14} />}
      </button>

      <button
        onClick={() => {
          if (!isDnp) onExclude();
        }}
        disabled={isDnp}
        className={`focus-ring flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-30 ${
          excluded ? "text-red-700" : "text-muted-foreground"
        }`}
        aria-label={excluded ? "Restore" : "Exclude"}
        type="button"
      >
        <Ban size={14} />
      </button>
    </div>
  );
}

export function salaryFor(
  player: Player,
  site: Site,
  salaryOverrides: Record<string, { salary?: number }> = {},
) {
  const override = salaryOverrides[String(player.mlbam_id)]?.salary;
  if (override !== undefined) return override;
  return site === "dk" ? player.salary_dk : player.salary_fd;
}

export function projectionFor(player: Player, site: Site, overriddenPlayers: Record<string, number>) {
  const override = overriddenPlayers[String(player.mlbam_id)];
  if (override !== undefined) return override;
  return site === "dk" ? player.projected_dk : player.projected_fd;
}
