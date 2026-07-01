import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MLB Optimizer — Free DFS Lineup Builder | LineupLab",
  description:
    "Free MLB DFS lineup optimizer for DraftKings and FanDuel. Auto-generates split-adjusted projections with confirmed starting lineups.",
  keywords:
    "mlb optimizer, mlb dfs optimizer, draftkings mlb optimizer, fanduel mlb optimizer, free mlb lineup optimizer",
  openGraph: {
    title: "MLB DFS Lineup Optimizer — Free | LineupLab",
    description:
      "Optimize MLB DFS lineups with split-adjusted projections and live lineup data.",
    url: "https://lineuplab.io",
    type: "website",
  },
  alternates: {
    canonical: "https://lineuplab.io",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
