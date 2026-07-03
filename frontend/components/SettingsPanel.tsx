"use client";

import { Upload } from "lucide-react";
import Papa from "papaparse";
import type { OptimizerSettings, Site } from "@/lib/types";

interface CsvMatchResult {
  matched: number;
  total: number;
  unmatched: string[];
}

interface SettingsPanelProps {
  site: Site;
  onSiteChange: (site: Site) => void;
  numLineups: number;
  onNumLineupsChange: (value: number) => void;
  settings: OptimizerSettings;
  onSettingsChange: (settings: OptimizerSettings) => void;
  teams: string[];
  csvMatchResult?: CsvMatchResult | null;
  onCsvOverrides: (
    rows: Array<{
      name: string;
      team: string;
      playerId?: number;
      projection?: number;
      salary?: number;
      positions?: string[];
      externalId?: string;
      nameId?: string;
    }>,
  ) => void;
}

export function SettingsPanel({
  site,
  onSiteChange,
  numLineups,
  onNumLineupsChange,
  settings,
  onSettingsChange,
  teams,
  csvMatchResult,
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
          .map((row) => {
            const nameId = row["Name + ID"] || row["Name+ID"] || "";
            const parsed = parseNameAndId(nameId || row.Name || row.name || row.Player || "");
            const rawId = row.ID || row.PlayerID || row["Player ID"] || parsed.playerId || "";
            const playerId = Number(rawId);
            const projection = Number(row.Projection || row.projection || row.AvgPointsPerGame || 0);
            const salary = Number(row.Salary || row.salary || 0);
            return {
              name: parsed.name,
              team: row.Team || row.team || row.TeamAbbrev || "",
              playerId: Number.isFinite(playerId) && playerId > 0 ? playerId : undefined,
              projection: Number.isFinite(projection) && projection > 0 ? projection : undefined,
              salary: Number.isFinite(salary) && salary > 0 ? salary : undefined,
              positions: parsePositions(row.Position || row.RosterPosition || row["Roster Position"] || ""),
              externalId: rawId ? String(rawId) : undefined,
              nameId: nameId || undefined,
            };
          })
          .filter((row) => row.name && (row.projection || row.salary || row.positions?.length));
        onCsvOverrides(rows);
      },
    });
  }

  return (
    <section className="bg-white/70 md:min-h-full">
      <div className="hidden border-b border-border/80 px-4 py-4 md:block">
        <div className="text-sm font-semibold tracking-tight">Build controls</div>
        <div className="mt-0.5 text-xs text-muted-foreground">Slate, salary, stacks, and uploads</div>
      </div>
      <div className="hidden border-b border-border/80 px-4 py-3 md:block">
        <div className="mb-2 text-xs text-muted-foreground">Contest site</div>
        <div className="flex gap-1 rounded-xl border border-border bg-muted/70 p-1">
          {(["dk", "fd"] as const).map((option) => (
            <button
              key={option}
              onClick={() => onSiteChange(option)}
              className={`focus-ring flex-1 rounded-lg py-1.5 text-sm transition-colors ${
                site === option
                  ? "bg-white font-medium text-primary shadow-sm"
                  : "text-muted-foreground hover:text-primary"
              }`}
              type="button"
            >
              {option === "dk" ? "DraftKings" : "FanDuel"}
            </button>
          ))}
        </div>
      </div>
      <div className="divide-y divide-border/80">
        <div className="flex items-center justify-between px-4 py-3">
          <div>
            <div className="text-sm font-medium">Lineups</div>
            <div className="text-xs text-muted-foreground">Max 20 free lineups</div>
          </div>
          <input
            className="focus-ring h-9 w-16 rounded-lg border border-border bg-white px-2 text-right text-sm shadow-sm"
            max={20}
            min={1}
            onChange={(event) => onNumLineupsChange(Math.max(1, Math.min(20, Number(event.target.value) || 1)))}
            type="number"
            value={numLineups}
          />
        </div>

        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <div>
            <div className="text-sm font-medium">Stack team</div>
            <div className="text-xs text-muted-foreground">Force batters from one team</div>
          </div>
          <select
            className="focus-ring h-9 rounded-lg border border-border bg-white px-2 text-sm shadow-sm"
            onChange={(event) => updateSettings({ stack_team: event.target.value || null })}
            value={settings.stack_team ?? ""}
          >
            <option value="">No stack</option>
            {teams.map((team) => (
              <option key={team} value={team}>
                {team}
              </option>
            ))}
          </select>
        </div>

        <div className="px-4 py-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-medium">Stack count</div>
            <span className="text-sm font-medium">{settings.stack_count}</span>
          </div>
          <input
            className="w-full accent-primary"
            max={6}
            min={2}
            onChange={(event) => updateSettings({ stack_count: Number(event.target.value) })}
            step={1}
            type="range"
            value={settings.stack_count}
          />
          <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
            <span>2</span>
            <span>3</span>
            <span>4</span>
            <span>5</span>
            <span>6</span>
          </div>
        </div>

        <div className="flex items-center justify-between px-4 py-3">
          <div>
            <div className="text-sm font-medium">Min salary used</div>
            <div className="text-xs text-muted-foreground">Cap: {site === "dk" ? "$50,000" : "$35,000"}</div>
          </div>
          <input
            className="focus-ring h-9 w-24 rounded-lg border border-border bg-white px-2 text-right text-sm shadow-sm"
            max={site === "dk" ? 50000 : 35000}
            min={site === "dk" ? 45000 : 30000}
            onChange={(event) => updateSettings({ min_salary_used: Number(event.target.value) })}
            step={100}
            type="number"
            value={settings.min_salary_used}
          />
        </div>

        <div className="flex items-center justify-between px-4 py-3">
          <div>
            <div className="text-sm font-medium">Avoid pitcher vs own batters</div>
            <div className="text-xs text-muted-foreground">Recommended for GPP</div>
          </div>
          <button
            aria-checked={settings.pitcher_vs_batter_same_team === "avoid"}
            className={`focus-ring relative h-6 w-10 rounded-full transition-colors ${
              settings.pitcher_vs_batter_same_team === "avoid" ? "bg-primary" : "bg-muted"
            }`}
            onClick={() =>
              updateSettings({
                pitcher_vs_batter_same_team:
                  settings.pitcher_vs_batter_same_team === "avoid" ? "allow" : "avoid",
              })
            }
            role="switch"
            type="button"
          >
            <span
              className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${
                settings.pitcher_vs_batter_same_team === "avoid" ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        <div className="px-4 py-3">
          <div className="mb-1 text-sm font-medium">Custom projections</div>
          <div className="mb-3 text-xs text-muted-foreground">
            Upload Name, Team, Projection columns or a DK export CSV.
          </div>
          <label className="focus-ring flex w-full cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-white py-2.5 text-sm text-muted-foreground shadow-sm transition-colors hover:bg-muted/50">
            <Upload className="h-4 w-4" />
            Upload CSV
            <input className="sr-only" type="file" accept=".csv" onChange={(event) => handleCsv(event.target.files?.[0])} />
          </label>
          {csvMatchResult ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Matched {csvMatchResult.matched}/{csvMatchResult.total} players
              {csvMatchResult.unmatched.length ? ` · Not found: ${csvMatchResult.unmatched.slice(0, 5).join(", ")}` : ""}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function parseNameAndId(value: string) {
  const match = value.match(/^(.*?)\s*\((\d+)\)\s*$/);
  if (!match) return { name: value.trim(), playerId: undefined };
  return { name: match[1].trim(), playerId: Number(match[2]) };
}

function parsePositions(value: string) {
  if (!value) return undefined;
  const positions = value
    .split(/[\/,]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((position) => (["LF", "CF", "RF"].includes(position) ? "OF" : position));
  return positions.length ? Array.from(new Set(positions)) : undefined;
}
