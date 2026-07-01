"use client";

import { Ban, Lock, Pencil, Search, Unlock } from "lucide-react";
import { useMemo, useState } from "react";
import type { Player, Site } from "@/lib/types";

interface PlayerPoolProps {
  players: Player[];
  site: Site;
  overriddenPlayers: Record<string, number>;
  lockedPlayers: Record<string, boolean>;
  excludedPlayers: Record<string, boolean>;
  onProjectionOverride: (playerId: string, projection: number) => void;
  onLockToggle: (playerId: string) => void;
  onExcludeToggle: (playerId: string) => void;
  lastUpdated?: string;
}

const positions = ["All", "P", "C", "1B", "2B", "SS", "3B", "OF"];

export function PlayerPool({
  players,
  site,
  overriddenPlayers,
  lockedPlayers,
  excludedPlayers,
  onProjectionOverride,
  onLockToggle,
  onExcludeToggle,
  lastUpdated,
}: PlayerPoolProps) {
  const [search, setSearch] = useState("");
  const [position, setPosition] = useState("All");
  const [team, setTeam] = useState("All");
  const [confirmedOnly, setConfirmedOnly] = useState(false);
  const [sort, setSort] = useState("Projection");

  const teams = useMemo(() => Array.from(new Set(players.map((player) => player.team))).sort(), [players]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return players
      .filter((player) => !query || player.name.toLowerCase().includes(query))
      .filter((player) => position === "All" || player.position.includes(position))
      .filter((player) => team === "All" || player.team === team)
      .filter((player) => !confirmedOnly || player.lineup_status === "confirmed")
      .sort((a, b) => {
        const projA = projectionFor(a, site, overriddenPlayers);
        const projB = projectionFor(b, site, overriddenPlayers);
        if (sort === "Salary") return salaryFor(b, site) - salaryFor(a, site);
        if (sort === "Value") return projB / salaryFor(b, site) - projA / salaryFor(a, site);
        return projB - projA;
      });
  }, [players, search, position, team, confirmedOnly, sort, site, overriddenPlayers]);

  const confirmedCount = players.filter((player) => player.lineup_status === "confirmed").length;

  return (
    <section className="rounded-md border border-line bg-white shadow-panel">
      <div className="border-b border-line p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Player Pool</h2>
            <p className="text-xs text-slate-500">
              {confirmedCount} of {players.length} players have confirmed lineups
            </p>
          </div>
          <label className="relative">
            <Search className="absolute left-3 top-2.5 text-slate-400" size={16} />
            <input
              className="w-56 rounded-md border border-line py-2 pl-9 pr-3 text-sm"
              placeholder="Search players"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-4">
          <select className="rounded-md border border-line px-3 py-2 text-sm" value={position} onChange={(e) => setPosition(e.target.value)}>
            {positions.map((pos) => (
              <option key={pos}>{pos}</option>
            ))}
          </select>
          <select className="rounded-md border border-line px-3 py-2 text-sm" value={team} onChange={(e) => setTeam(e.target.value)}>
            <option>All</option>
            {teams.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <select className="rounded-md border border-line px-3 py-2 text-sm" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option>Projection</option>
            <option>Salary</option>
            <option>Value</option>
          </select>
          <label className="flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm">
            <input type="checkbox" checked={confirmedOnly} onChange={(e) => setConfirmedOnly(e.target.checked)} />
            Confirmed only
          </label>
        </div>
      </div>

      <div className="table-scroll max-h-[620px] overflow-auto">
        <table className="w-full min-w-[760px] border-collapse text-sm">
          <thead className="sticky top-0 bg-field text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-3 py-3">Pos</th>
              <th className="px-3 py-3">Team</th>
              <th className="px-3 py-3">Opp</th>
              <th className="px-3 py-3 text-right">Salary</th>
              <th className="px-3 py-3 text-right">Proj</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3 text-center">L/E</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((player) => {
              const id = String(player.mlbam_id);
              const overridden = overriddenPlayers[id] !== undefined;
              const excluded = excludedPlayers[id];
              return (
                <tr key={id} className={`border-t border-line ${excluded || player.lineup_status === "dnp" ? "bg-slate-100 text-slate-400" : ""}`}>
                  <td className="px-4 py-3">
                    <div className="font-medium">{player.name}</div>
                    <div className="text-xs text-slate-500">
                      {player.opposing_pitcher ?? "TBD"} {player.opposing_pitcher_hand ? `(${player.opposing_pitcher_hand})` : ""}
                    </div>
                  </td>
                  <td className="px-3 py-3">{player.position.join("/")}</td>
                  <td className="px-3 py-3">{player.team}</td>
                  <td className="px-3 py-3">{player.opponent}</td>
                  <td className="px-3 py-3 text-right">${salaryFor(player, site).toLocaleString()}</td>
                  <td className="px-3 py-3 text-right">
                    <label className="inline-flex items-center gap-1">
                      {overridden ? <Pencil size={13} className="text-gold" /> : null}
                      <input
                        className="w-20 rounded-md border border-line px-2 py-1 text-right"
                        type="number"
                        step="0.1"
                        value={projectionFor(player, site, overriddenPlayers)}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          if (Number.isFinite(value) && value >= 0) {
                            onProjectionOverride(id, value);
                          }
                        }}
                        onBlur={(event) => {
                          const value = Number(event.target.value);
                          if (Number.isFinite(value) && value >= 0) {
                            onProjectionOverride(id, value);
                          }
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") event.currentTarget.blur();
                        }}
                      />
                    </label>
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge status={player.lineup_status} />
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex justify-center gap-1">
                      <button className={`rounded-md border p-2 ${lockedPlayers[id] ? "bg-ink text-white" : "border-line"}`} onClick={() => onLockToggle(id)} title="Lock">
                        {lockedPlayers[id] ? <Lock size={15} /> : <Unlock size={15} />}
                      </button>
                      <button className={`rounded-md border p-2 ${excludedPlayers[id] ? "bg-red-600 text-white" : "border-line"}`} onClick={() => onExcludeToggle(id)} title="Exclude">
                        <Ban size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="border-t border-line px-4 py-3 text-xs text-slate-500">
        Last updated: {lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : "Waiting for data"}
      </div>
    </section>
  );
}

export function salaryFor(player: Player, site: Site) {
  return site === "dk" ? player.salary_dk : player.salary_fd;
}

export function projectionFor(player: Player, site: Site, overriddenPlayers: Record<string, number>) {
  const override = overriddenPlayers[String(player.mlbam_id)];
  if (override !== undefined) return override;
  return site === "dk" ? player.projected_dk : player.projected_fd;
}

function StatusBadge({ status }: { status: Player["lineup_status"] }) {
  const color = {
    confirmed: "bg-emerald-500",
    expected: "bg-yellow-500",
    unconfirmed: "bg-slate-400",
    dnp: "bg-red-500",
  }[status];
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line px-2 py-1 text-xs capitalize">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {status}
    </span>
  );
}
