"use client";

import { Upload } from "lucide-react";
import Papa from "papaparse";
import type { OptimizerSettings, Site } from "@/lib/types";

interface SettingsPanelProps {
  site: Site;
  onSiteChange: (site: Site) => void;
  numLineups: number;
  onNumLineupsChange: (value: number) => void;
  settings: OptimizerSettings;
  onSettingsChange: (settings: OptimizerSettings) => void;
  teams: string[];
  onCsvOverrides: (rows: Array<{ name: string; team: string; projection: number }>) => void;
}

export function SettingsPanel({
  site,
  onSiteChange,
  numLineups,
  onNumLineupsChange,
  settings,
  onSettingsChange,
  teams,
  onCsvOverrides,
}: SettingsPanelProps) {
  function updateSettings(patch: Partial<OptimizerSettings>) {
    onSettingsChange({ ...settings, ...patch });
  }

  function handleCsv(file: File | undefined) {
    if (!file) return;
    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: true,
      complete: (result) => {
        const rows = result.data
          .map((row) => ({
            name: row.Name || row.name || row.Player || "",
            team: row.Team || row.team || row.TeamAbbrev || "",
            projection: Number(row.Projection || row.projection || row.AvgPointsPerGame || 0),
          }))
          .filter((row) => row.name && Number.isFinite(row.projection) && row.projection > 0);
        onCsvOverrides(rows);
      },
    });
  }

  return (
    <section className="rounded-md border border-line bg-white p-4 shadow-panel">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Optimizer Settings</h2>
          <p className="text-xs text-slate-500">DraftKings and FanDuel classic MLB</p>
        </div>
        <div className="grid grid-cols-2 rounded-md border border-line bg-field p-1 text-sm">
          {(["dk", "fd"] as const).map((option) => (
            <button
              key={option}
              type="button"
              className={`rounded px-3 py-1.5 font-medium ${
                site === option ? "bg-ink text-white" : "text-slate-600"
              }`}
              onClick={() => onSiteChange(option)}
            >
              {option === "dk" ? "DK" : "FD"}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-sm">
          <span className="font-medium">Lineups</span>
          <input
            className="rounded-md border border-line px-3 py-2"
            type="number"
            min={1}
            max={20}
            value={numLineups}
            onChange={(event) => onNumLineupsChange(Number(event.target.value))}
          />
        </label>

        <label className="grid gap-1 text-sm">
          <span className="font-medium">Stack Team</span>
          <select
            className="rounded-md border border-line px-3 py-2"
            value={settings.stack_team ?? ""}
            onChange={(event) => updateSettings({ stack_team: event.target.value || null })}
          >
            <option value="">No forced stack</option>
            {teams.map((team) => (
              <option key={team} value={team}>
                {team}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1 text-sm">
          <span className="font-medium">Stack Count: {settings.stack_count}</span>
          <input
            type="range"
            min={2}
            max={6}
            value={settings.stack_count}
            onChange={(event) => updateSettings({ stack_count: Number(event.target.value) })}
          />
        </label>

        <label className="grid gap-1 text-sm">
          <span className="font-medium">Min Salary Used</span>
          <input
            className="rounded-md border border-line px-3 py-2"
            type="number"
            min={0}
            value={settings.min_salary_used}
            onChange={(event) => updateSettings({ min_salary_used: Number(event.target.value) })}
          />
        </label>
      </div>

      <label className="mt-4 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={settings.pitcher_vs_batter_same_team === "avoid"}
          onChange={(event) =>
            updateSettings({
              pitcher_vs_batter_same_team: event.target.checked ? "avoid" : "allow",
            })
          }
        />
        Avoid pitcher facing same-team batters
      </label>

      <label className="mt-4 flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-line bg-field px-3 py-3 text-sm font-medium text-slate-700">
        <Upload size={16} />
        Upload custom projections CSV
        <input className="hidden" type="file" accept=".csv" onChange={(e) => handleCsv(e.target.files?.[0])} />
      </label>
    </section>
  );
}
