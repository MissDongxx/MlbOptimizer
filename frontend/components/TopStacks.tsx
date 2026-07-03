"use client";

import { useEffect, useState } from "react";
import { fetchTodaysPlayers } from "@/lib/api";
import type { Player } from "@/lib/types";

interface StackSummary {
  team: string;
  opponent: string;
  pitcher: string;
  pitcher_hand: string;
  player_count: number;
  avg_proj: number;
  avg_salary: number;
  top_players: string[];
}

export function TopStacks() {
  const [stacks, setStacks] = useState<StackSummary[]>([]);

  useEffect(() => {
    fetchTodaysPlayers()
      .then((data) => {
        const teams: Record<string, Player[]> = {};

        data.players
          .filter((player) => !player.position.includes("P") && player.lineup_status !== "dnp")
          .forEach((player) => {
            teams[player.team] ??= [];
            teams[player.team].push(player);
          });

        const summaries = Object.entries(teams)
          .filter(([, players]) => players.length >= 3)
          .map(([team, players]) => {
            const sorted = [...players].sort((a, b) => b.projected_dk - a.projected_dk);
            const top4 = sorted.slice(0, 4);

            return {
              team,
              opponent: players[0]?.opponent ?? "",
              pitcher: players[0]?.opposing_pitcher ?? "TBD",
              pitcher_hand: players[0]?.opposing_pitcher_hand ?? "?",
              player_count: top4.length,
              avg_proj: top4.reduce((sum, player) => sum + player.projected_dk, 0) / top4.length,
              avg_salary: Math.round(top4.reduce((sum, player) => sum + player.salary_dk, 0) / top4.length),
              top_players: top4.map((player) => getLastName(player.name)),
            };
          })
          .sort((a, b) => b.avg_proj - a.avg_proj)
          .slice(0, 3);

        setStacks(summaries);
      })
      .catch(() => {});
  }, []);

  if (stacks.length === 0) return null;

  const today = new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" });

  return (
    <section id="stacks" className="relative z-10 scroll-mt-24 border-b border-border/70 px-6 py-14 md:px-8">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6 flex flex-col justify-between gap-3 md:flex-row md:items-end">
          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-primary">Stack board</div>
            <h2 className="text-2xl font-semibold tracking-tight">Today&apos;s top MLB DFS stacks — {today}</h2>
          </div>
          <p className="max-w-xl text-sm leading-6 text-muted-foreground">
            Teams with the strongest DFS value based on split-adjusted projections and confirmed batting orders.
          </p>
        </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {stacks.map((stack) => (
          <div key={stack.team} className="rounded-2xl border border-border bg-white p-5 shadow-sm transition-transform hover:-translate-y-0.5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-sm font-semibold">
                {stack.team} {stack.player_count}-stack
              </span>
              <span className="text-right text-xs text-muted-foreground">
                vs {stack.pitcher} ({stack.pitcher_hand})
              </span>
            </div>
            <div className="mb-1 text-2xl font-medium tabular-nums">
              {stack.avg_proj.toFixed(1)}
              <span className="ml-1 text-sm font-normal text-muted-foreground">avg proj pts</span>
            </div>
            <div className="mb-3 text-xs text-muted-foreground">avg salary ${(stack.avg_salary / 1000).toFixed(1)}k</div>
            <div className="text-xs text-muted-foreground">{stack.top_players.join(" · ")}</div>
          </div>
        ))}
      </div>
      </div>
    </section>
  );
}

function getLastName(name: string): string {
  const suffixes = new Set(["Jr.", "Sr.", "II", "III", "IV"]);
  const parts = name.split(" ").filter(Boolean);
  const filtered = parts.filter((part) => !suffixes.has(part));
  return filtered[filtered.length - 1] ?? parts[parts.length - 1] ?? name;
}
