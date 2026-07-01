"use client";

import { Copy, Download } from "lucide-react";
import { useState } from "react";
import { downloadLineupsCsv } from "@/lib/csv";
import type { Lineup } from "@/lib/types";

interface LineupGridProps {
  lineups: Lineup[];
  warnings: string[];
  solveTimeMs?: number;
}

export function LineupGrid({ lineups, warnings, solveTimeMs }: LineupGridProps) {
  const [active, setActive] = useState(0);

  if (!lineups.length) {
    return (
      <section className="flex min-h-[420px] items-center justify-center rounded-md border border-line bg-white p-8 text-center shadow-panel">
        <div>
          <h2 className="text-lg font-semibold">Lineups will appear here</h2>
          <p className="mt-2 text-sm text-slate-500">
            Tune settings, lock or exclude players, then run the optimizer.
          </p>
        </div>
      </section>
    );
  }

  const lineup = lineups[Math.min(active, lineups.length - 1)];

  async function copyLineup() {
    const text = lineup.players
      .map((player) => `${player.position_slot}: ${player.name} (${player.team}) ${player.projected_points}`)
      .join("\n");
    await navigator.clipboard.writeText(text);
  }

  return (
    <section className="rounded-md border border-line bg-white shadow-panel">
      <div className="border-b border-line p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Optimized Lineups</h2>
            <p className="text-xs text-slate-500">
              {lineups.length} lineups solved{solveTimeMs !== undefined ? ` in ${solveTimeMs}ms` : ""}
            </p>
          </div>
          <div className="flex gap-2">
            <button className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm" onClick={copyLineup}>
              <Copy size={15} />
              Copy
            </button>
            <button className="inline-flex items-center gap-2 rounded-md bg-ink px-3 py-2 text-sm font-medium text-white" onClick={() => downloadLineupsCsv(lineups)}>
              <Download size={15} />
              CSV
            </button>
          </div>
        </div>

        <div className="mt-3 flex gap-2 overflow-x-auto">
          {lineups.map((item, index) => (
            <button
              key={item.lineup_number}
              className={`rounded-md border px-3 py-1.5 text-sm ${active === index ? "border-ink bg-ink text-white" : "border-line"}`}
              onClick={() => setActive(index)}
            >
              Lineup {item.lineup_number}
            </button>
          ))}
        </div>
      </div>

      <div className="p-4">
        <div className="mb-4 grid grid-cols-2 gap-3">
          <div className="rounded-md bg-field p-3">
            <div className="text-xs uppercase text-slate-500">Projection</div>
            <div className="text-2xl font-semibold">{lineup.projected_points.toFixed(2)}</div>
          </div>
          <div className="rounded-md bg-field p-3">
            <div className="text-xs uppercase text-slate-500">Salary</div>
            <div className="text-2xl font-semibold">${lineup.total_salary.toLocaleString()}</div>
          </div>
        </div>

        <div className="overflow-hidden rounded-md border border-line">
          <table className="w-full text-sm">
            <thead className="bg-field text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-3">Slot</th>
                <th className="px-3 py-3">Player</th>
                <th className="px-3 py-3">Team</th>
                <th className="px-3 py-3 text-right">Proj</th>
                <th className="px-3 py-3 text-right">$</th>
              </tr>
            </thead>
            <tbody>
              {lineup.players.map((player) => (
                <tr key={`${player.position_slot}-${player.mlbam_id}`} className="border-t border-line">
                  <td className="px-3 py-3 font-semibold">{player.position_slot}</td>
                  <td className="px-3 py-3">{player.name}</td>
                  <td className="px-3 py-3">{player.team}</td>
                  <td className="px-3 py-3 text-right">{player.projected_points.toFixed(2)}</td>
                  <td className="px-3 py-3 text-right">${player.salary.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {warnings.length ? (
          <div className="mt-4 rounded-md border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">
            {warnings.join(" ")}
          </div>
        ) : null}
      </div>
    </section>
  );
}
