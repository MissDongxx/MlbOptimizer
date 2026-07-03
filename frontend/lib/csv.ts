import type { Lineup, LineupPlayer, Site } from "./types";

const DK_COLUMNS = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"];
const FD_COLUMNS = ["P", "C/1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"];

export function lineupToCSV(lineup: Lineup, site: Site): string {
  const slots = site === "dk" ? DK_COLUMNS : FD_COLUMNS;
  const row = slots.map((slot, index) => playerCell(findPlayerForSlot(lineup.players, slots, slot, index)));
  return [slots, row].map(csvRow).join("\n");
}

export function lineupDetailsToCSV(lineup: Lineup): string {
  const rows = lineup.players.map((player) => [
    player.position_slot,
    player.name,
    player.team,
    player.salary,
    player.projected_points.toFixed(1),
  ]);
  return [["Slot", "Player", "Team", "Salary", "Projection"], ...rows].map(csvRow).join("\n");
}

export function downloadLineupsCsv(lineups: Lineup[], site: Site) {
  const slots = site === "dk" ? DK_COLUMNS : FD_COLUMNS;
  const rows = lineups.map((lineup) =>
    slots.map((slot, index) => playerCell(findPlayerForSlot(lineup.players, slots, slot, index))),
  );
  const csv = [slots, ...rows].map(csvRow).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = site === "dk" ? "draftkings-lineups.csv" : "fanduel-lineups.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function findPlayerForSlot(players: LineupPlayer[], slots: string[], slot: string, index: number) {
  const occurrence = slots.slice(0, index + 1).filter((item) => item === slot).length - 1;
  const direct = players.filter((player) => player.position_slot === slot)[occurrence];
  if (direct) return direct;
  if (slot === "UTIL") {
    return players.find((player) => !slots.slice(0, -1).includes(player.position_slot));
  }
  return undefined;
}

function playerCell(player: LineupPlayer | undefined) {
  return player?.name_id || player?.external_id || (player ? `${player.name} (${player.mlbam_id})` : "");
}

function csvRow(row: Array<string | number>) {
  return row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(",");
}
