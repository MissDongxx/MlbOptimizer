"use client";

import { Activity, RotateCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { LineupGrid } from "@/components/LineupGrid";
import { PlayerPool, projectionFor, salaryFor } from "@/components/PlayerPool";
import { SettingsPanel } from "@/components/SettingsPanel";
import { fetchTodaysPlayers, runOptimizer } from "@/lib/api";
import type { OptimizeResponse, OptimizerSettings, Player, PlayerPoolResponse, Site } from "@/lib/types";

const structuredData = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "LineupLab MLB Optimizer",
  applicationCategory: "SportsApplication",
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "USD",
  },
  description: "Free MLB DFS lineup optimizer for DraftKings and FanDuel",
};

const loadingMessages = [
  "Calculating split matchups...",
  "Applying stacking rules...",
  "Solving lineup constraints...",
  "Almost there...",
];

export default function Home() {
  const [site, setSite] = useState<Site>("dk");
  const [numLineups, setNumLineups] = useState(5);
  const [settings, setSettings] = useState<OptimizerSettings>({
    stack_team: null,
    stack_count: 4,
    pitcher_vs_batter_same_team: "avoid",
    min_salary_used: 49500,
    unique_lineups: true,
  });
  const [data, setData] = useState<PlayerPoolResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingPlayers, setLoadingPlayers] = useState(true);
  const [optimizing, setOptimizing] = useState(false);
  const [messageIndex, setMessageIndex] = useState(0);
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [overriddenPlayers, setOverriddenPlayers] = useState<Record<string, number>>({});
  const [lockedPlayers, setLockedPlayers] = useState<Record<string, boolean>>({});
  const [excludedPlayers, setExcludedPlayers] = useState<Record<string, boolean>>({});

  useEffect(() => {
    loadPlayers();
  }, []);

  useEffect(() => {
    if (!optimizing) return;
    const timer = window.setInterval(() => {
      setMessageIndex((current) => (current + 1) % loadingMessages.length);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [optimizing]);

  const players = data?.players ?? [];
  const teams = useMemo(() => Array.from(new Set(players.map((player) => player.team))).sort(), [players]);

  async function loadPlayers() {
    setLoadingPlayers(true);
    setError(null);
    try {
      setData(await fetchTodaysPlayers());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load players");
    } finally {
      setLoadingPlayers(false);
    }
  }

  function handleCsvOverrides(rows: Array<{ name: string; team: string; projection: number }>) {
    const next: Record<string, number> = {};
    for (const row of rows) {
      const match = players.find(
        (player) =>
          normalize(player.name) === normalize(row.name) &&
          (!row.team || player.team.toLowerCase() === row.team.toLowerCase()),
      );
      if (match) {
        next[String(match.mlbam_id)] = row.projection;
      }
    }
    setOverriddenPlayers((prev) => ({ ...prev, ...next }));
  }

  async function optimize() {
    setOptimizing(true);
    setError(null);
    try {
      const response = await runOptimizer({
        site,
        num_lineups: numLineups,
        settings,
        players: players.map((player) => ({
          mlbam_id: player.mlbam_id,
          name: player.name,
          team: player.team,
          position: player.position,
          salary: salaryFor(player, site),
          projected_points: projectionFor(player, site, overriddenPlayers),
          lock: Boolean(lockedPlayers[String(player.mlbam_id)]),
          exclude: Boolean(excludedPlayers[String(player.mlbam_id)]),
          max_exposure: 1,
        })),
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Optimization failed");
    } finally {
      setOptimizing(false);
    }
  }

  return (
    <main className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
      />

      <header className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="mb-1 inline-flex items-center gap-2 rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-slate-600">
            <Activity size={14} className="text-accent" />
            LineupLab
          </div>
          <h1 className="text-3xl font-bold tracking-normal sm:text-4xl">Free MLB DFS Lineup Optimizer</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600 sm:text-base">
            Build DraftKings and FanDuel lineups with cached split-adjusted projections,
            batting order weighting, and live lineup status.
          </p>
        </div>
        <button
          className="inline-flex items-center gap-2 rounded-md border border-line bg-white px-4 py-2 text-sm font-medium shadow-sm"
          onClick={loadPlayers}
          disabled={loadingPlayers}
        >
          <RotateCw size={16} className={loadingPlayers ? "animate-spin" : ""} />
          Refresh
        </button>
      </header>

      {error ? (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(520px,1.05fr)]">
        <div className="grid gap-5">
          <SettingsPanel
            site={site}
            onSiteChange={(nextSite) => {
              setSite(nextSite);
              setSettings((current) => ({
                ...current,
                min_salary_used: nextSite === "dk" ? 49500 : 34500,
              }));
            }}
            numLineups={numLineups}
            onNumLineupsChange={(value) => setNumLineups(Math.max(1, Math.min(20, value || 1)))}
            settings={settings}
            onSettingsChange={setSettings}
            teams={teams}
            onCsvOverrides={handleCsvOverrides}
          />

          {loadingPlayers ? (
            <SkeletonTable />
          ) : (
            <PlayerPool
              players={players}
              site={site}
              overriddenPlayers={overriddenPlayers}
              lockedPlayers={lockedPlayers}
              excludedPlayers={excludedPlayers}
              onProjectionOverride={(playerId, projection) =>
                setOverriddenPlayers((prev) => ({ ...prev, [playerId]: projection }))
              }
              onLockToggle={(playerId) =>
                setLockedPlayers((prev) => ({ ...prev, [playerId]: !prev[playerId] }))
              }
              onExcludeToggle={(playerId) =>
                setExcludedPlayers((prev) => ({ ...prev, [playerId]: !prev[playerId] }))
              }
              lastUpdated={data?.last_updated}
            />
          )}

          <button
            className="rounded-md bg-accent px-5 py-3 text-base font-semibold text-white shadow-panel disabled:cursor-not-allowed disabled:bg-slate-400"
            disabled={optimizing || loadingPlayers || !players.length}
            onClick={optimize}
          >
            {optimizing ? `${loadingMessages[messageIndex]} ~2 seconds` : `Optimize ${numLineups} Lineups`}
          </button>
        </div>

        <LineupGrid
          lineups={result?.lineups ?? []}
          warnings={result?.warnings ?? []}
          solveTimeMs={result?.solve_time_ms}
        />
      </div>
    </main>
  );
}

function SkeletonTable() {
  return (
    <section className="rounded-md border border-line bg-white p-4 shadow-panel">
      <div className="mb-4 h-6 w-40 rounded bg-slate-200" />
      <div className="grid gap-2">
        {Array.from({ length: 10 }).map((_, index) => (
          <div key={index} className="h-11 rounded bg-slate-100" />
        ))}
      </div>
    </section>
  );
}

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}
