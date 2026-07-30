"use client";

import { Zap } from "lucide-react";
import { useState } from "react";
import { downloadLineupsCsv, lineupDetailsToCSV } from "@/lib/csv";
import type { Lineup, Site } from "@/lib/types";

interface LineupGridProps {
  lineups: Lineup[];
  warnings: string[];
  solveTimeMs?: number;
  site: Site;
}

export function LineupGrid({ lineups, warnings, solveTimeMs, site }: LineupGridProps) {
  const [active, setActive] = useState(0);

  if (!lineups.length) {
    return (
      <section className="flex h-64 flex-col items-center justify-center bg-white/70 px-8 text-center md:h-full">
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-muted text-primary">
          <Zap className="h-6 w-6" />
        </div>
        <p className="text-sm font-semibold">No lineups yet</p>
        <p className="mt-1 max-w-48 text-xs leading-5 text-muted-foreground">Tune the player pool, then run an optimized build.</p>
      </section>
    );
  }

  const lineup = lineups[Math.min(active, lineups.length - 1)];

  async function copyLineup() {
    const text = lineup.players
      .map((player) => `${player.position_slot}: ${player.name} (${player.team}) ${player.projected_points.toFixed(1)}`)
      .join("\n");
    await navigator.clipboard.writeText(text);
  }

  function downloadSingleLineup() {
    const csv = lineupDetailsToCSV(lineup);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${site}-lineup-${lineup.lineup_number}-details.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="flex min-h-full flex-col bg-white/70">
      <div className="flex items-center justify-between border-b border-border/80 px-4 py-3 md:px-5">
        <div>
          <span className="text-sm font-semibold">{lineups.length} lineups generated</span>
          {solveTimeMs !== undefined ? (
            <span className="ml-2 text-[11px] text-muted-foreground">{solveTimeMs}ms</span>
          ) : null}
        </div>
        <button
          className="focus-ring rounded-lg border border-primary/20 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/15"
          onClick={() => downloadLineupsCsv(lineups, site)}
          type="button"
        >
          Export all CSV
        </button>
      </div>

      <div className="scrollbar-none flex shrink-0 overflow-x-auto border-b border-border/80 bg-muted/30 px-1">
        {lineups.map((item, index) => (
          <button
            key={item.lineup_number}
            onClick={() => setActive(index)}
            className={`focus-ring my-1 shrink-0 whitespace-nowrap rounded-lg px-4 py-2 text-xs transition-colors ${
              active === index
                ? "bg-white font-medium text-primary shadow-sm"
                : "text-muted-foreground hover:text-primary"
            }`}
            type="button"
          >
            #{index + 1}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between border-b border-border/80 bg-muted/40 px-4 py-3 md:px-5">
        <span className="text-xs text-muted-foreground">
          ${lineup.total_salary.toLocaleString()} / ${site === "dk" ? "50,000" : "35,000"}
        </span>
        <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary">
          Proj {lineup.projected_points.toFixed(1)} pts
        </span>
      </div>

      <div className="divide-y divide-border/70">
        {lineup.players.map((player) => {
          const teamCount = lineup.players.filter((item) => item.team === player.team).length;
          const isStack = teamCount >= 3;
          return (
            <div key={`${player.position_slot}-${player.mlbam_id}`} className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-muted/30 md:px-5 md:py-2">
              <span className="w-7 shrink-0 rounded-md bg-muted px-1.5 py-1 text-center text-[10px] font-medium text-muted-foreground">
                {player.position_slot}
              </span>
              <span className={`h-7 w-0.5 shrink-0 rounded-full ${isStack ? "bg-primary" : "bg-transparent"}`} />
              <span className="flex-1 truncate text-sm">{player.name}</span>
              <span className="text-xs text-muted-foreground">${(player.salary / 1000).toFixed(1)}k</span>
              <span className="w-10 text-right text-sm font-medium tabular-nums text-primary">
                {player.projected_points.toFixed(1)}
              </span>
            </div>
          );
        })}
      </div>

      {warnings.length ? (
        <div className="mx-4 mt-3 rounded-xl border border-yellow-200 bg-yellow-50 p-3 text-xs text-yellow-800">
          {warnings.join(" ")}
        </div>
      ) : null}

      <div className="mt-auto flex gap-2 border-t border-border/80 px-4 py-3 md:px-5">
        <button
          onClick={copyLineup}
          className="focus-ring flex-1 rounded-xl border border-border bg-white py-2 text-sm font-medium shadow-sm transition-colors hover:bg-muted/50"
          type="button"
        >
          Copy
        </button>
        <button
          onClick={downloadSingleLineup}
          className="focus-ring flex-1 rounded-xl border border-primary/20 bg-primary/10 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary/20"
          type="button"
        >
          Download CSV
        </button>
      </div>
    </section>
  );
}
