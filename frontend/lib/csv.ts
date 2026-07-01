import type { Lineup } from "./types";

export function downloadLineupsCsv(lineups: Lineup[]) {
  const headers = ["Lineup", "Slot", "Name", "Team", "Salary", "Projection"];
  const rows = lineups.flatMap((lineup) =>
    lineup.players.map((player) => [
      lineup.lineup_number,
      player.position_slot,
      player.name,
      player.team,
      player.salary,
      player.projected_points.toFixed(2),
    ]),
  );
  const csv = [headers, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(","))
    .join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "lineuplab-lineups.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}
