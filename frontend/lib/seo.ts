import type { MetadataRoute } from "next";

export const siteUrl = "https://diamscore.com";
export const siteName = "diamscore.com";
export const brandName = "DiamScore";
export const defaultOgImage = "/diamscore-hero-analytics.png";

export const homeSeo = {
  title: "MLB Optimizer for DFS Lineups | diamscore.com",
  description:
    "Free MLB optimizer for DraftKings and FanDuel lineups. Build DFS stacks with live MLB data, split-adjusted projections, CSV export, and no account required.",
  keywords: [
    "mlb optimizer",
    "mlb dfs optimizer",
    "mlb lineup optimizer",
    "free mlb optimizer",
    "free mlb lineup optimizer",
    "draftkings mlb optimizer",
    "fanduel mlb optimizer",
    "baseball dfs optimizer",
    "daily fantasy baseball optimizer",
  ],
};

export const seoPages = [
  {
    slug: "mlb-dfs-optimizer",
    keyword: "mlb dfs optimizer",
    title: "MLB DFS Optimizer for Daily Fantasy | diamscore.com",
    description:
      "Use a free MLB DFS optimizer with live lineups, stack controls, salary rules, and split-adjusted projections for DraftKings and FanDuel contests today.",
    h1: "MLB DFS Optimizer for Daily Fantasy Baseball",
    intro:
      "DiamScore is an MLB DFS optimizer built for the daily fantasy baseball workflow: evaluate the slate, compare projections, manage stacks, and export lineups without forcing a long setup process. The page focuses on the broad MLB DFS optimizer intent for players who want one tool that can handle DraftKings and FanDuel builds.",
    sections: [
      {
        heading: "Why DFS Players Need More Than Raw Projections",
        body: "A useful MLB DFS optimizer should connect projections to the way baseball scoring actually compounds. Batting order, pitcher handedness, park context, and team stacks all change the value of a player. DiamScore keeps those signals near the lineup builder so users can understand why a projection matters before they lock, fade, or raise exposure.",
      },
      {
        heading: "Stack-Aware Lineup Building",
        body: "Baseball DFS rewards correlation. Instead of treating every hitter as an isolated pick, the optimizer supports team stacks and salary constraints so a lineup can pursue realistic ceiling outcomes. Users can review top stacks, compare roster salary, and generate multiple DFS lineups for the same slate.",
      },
      {
        heading: "DraftKings and FanDuel Workflow",
        body: "DraftKings and FanDuel use different roster rules, salary caps, and scoring weights. DiamScore lets users switch contest site settings, upload salary CSV data, and export lineups in a contest-ready format. That makes the MLB DFS optimizer useful for research, iteration, and bulk lineup preparation.",
      },
    ],
    cta: "Open the free MLB DFS optimizer",
  },
  {
    slug: "mlb-lineup-optimizer",
    keyword: "mlb lineup optimizer",
    title: "MLB Lineup Optimizer for DFS Builds | diamscore.com",
    description:
      "Build MLB lineups with a free optimizer for DFS contests. Compare salary, stacks, batting order, projections, lineup rules, CSV export, and slate news.",
    h1: "MLB Lineup Optimizer for DFS Builds",
    intro:
      "The DiamScore MLB lineup optimizer helps turn player projections into playable DFS lineups. It is designed for users who want fast slate review, clear roster constraints, and a practical way to compare multiple optimized builds before submitting entries.",
    sections: [
      {
        heading: "From Player Pool to Optimized Lineup",
        body: "A strong MLB lineup optimizer starts with a clean player pool. DiamScore highlights projected points, salary, team, opponent, batting order, and lineup status so users can remove inactive players and focus on realistic options. Locks and excludes make it easy to keep personal takes inside the build.",
      },
      {
        heading: "Control Salary, Exposure, and Correlation",
        body: "Lineup optimization is not only about the highest projection. Users often need salary floor rules, unique lineup generation, exposure control, and stack settings. DiamScore keeps those controls visible so each MLB lineup can match a contest strategy instead of becoming a black-box answer.",
      },
      {
        heading: "Review Before You Export",
        body: "After solving, users can compare generated lineups, salary usage, stack construction, and warnings. The goal is to make the MLB lineup optimizer useful as a decision layer, not just a button that returns one lineup with no context.",
      },
    ],
    cta: "Build MLB DFS lineups",
  },
  {
    slug: "draftkings-mlb-optimizer",
    keyword: "draftkings mlb optimizer",
    title: "DraftKings MLB Optimizer for DFS | diamscore.com",
    description:
      "Use a DraftKings MLB optimizer with DK salary rules, two-pitcher roster logic, stack controls, projections, CSV export, and lineup review tools today.",
    h1: "DraftKings MLB Optimizer for DFS Lineups",
    intro:
      "DiamScore includes a DraftKings MLB optimizer mode for players who need DK salary logic, roster slots, projections, and CSV export in the same workflow. The page targets DraftKings-specific MLB optimizer searches while keeping the advice focused on practical lineup construction.",
    sections: [
      {
        heading: "DraftKings MLB Rules Change the Build",
        body: "DraftKings MLB contests use a $50,000 salary cap and two pitcher slots, which makes pitcher value and hitter stack salary especially important. DiamScore adjusts optimizer settings for DK so lineups are generated against the right roster structure and scoring environment.",
      },
      {
        heading: "Balance Pitching Floor With Hitter Ceiling",
        body: "A DraftKings MLB optimizer needs to handle the tradeoff between expensive pitchers and high-upside stacks. DiamScore exposes salary, projection, opponent, and stack context so users can decide whether to spend at pitcher, stack expensive offenses, or build a more balanced lineup.",
      },
      {
        heading: "CSV Export for DraftKings Entries",
        body: "Users can upload salary CSV data, match players, optimize lineups, and export contest-ready builds. That keeps the DraftKings MLB optimizer aligned with the practical workflow of preparing entries rather than only producing projections.",
      },
    ],
    cta: "Optimize DraftKings MLB lineups",
  },
  {
    slug: "fanduel-mlb-optimizer",
    keyword: "fanduel mlb optimizer",
    title: "FanDuel MLB Optimizer for DFS | diamscore.com",
    description:
      "Create FanDuel MLB lineups with FD scoring, salary cap logic, stack settings, live lineup status, projections, CSV export, and lineup review tools today.",
    h1: "FanDuel MLB Optimizer for DFS Lineups",
    intro:
      "DiamScore supports a FanDuel MLB optimizer workflow for users who want FD scoring, salary rules, lineup status, and stack controls in a fast browser-based tool. It focuses on turning MLB DFS research into lineups that respect FanDuel roster construction.",
    sections: [
      {
        heading: "FanDuel Scoring Rewards Power and Run Production",
        body: "FanDuel MLB scoring places strong value on extra-base hits, runs, RBI, and pitcher results. DiamScore keeps scoring context close to the optimizer so users can compare why certain bats or stacks project well for FD contests.",
      },
      {
        heading: "Single-Pitcher Builds Need Different Salary Choices",
        body: "Because FanDuel uses one pitcher slot, lineup construction often shifts more salary into hitters. The FanDuel MLB optimizer mode applies FD salary cap logic and helps users review whether stacks, locks, and fades still leave enough room for a competitive pitcher.",
      },
      {
        heading: "Fast FanDuel Lineup Iteration",
        body: "Users can switch to FD mode, upload salary data, optimize up to 20 lineups, and export builds for entry review. DiamScore is built to make FanDuel MLB optimizer decisions easier to repeat as news and confirmed lineups change.",
      },
    ],
    cta: "Optimize FanDuel MLB lineups",
  },
];

export function absoluteUrl(path = "/") {
  return new URL(path, siteUrl).toString();
}

export function sitemapEntries(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    {
      url: siteUrl,
      lastModified: now,
      changeFrequency: "daily",
      priority: 1,
    },
    ...seoPages.map((page) => ({
      url: absoluteUrl(`/${page.slug}`),
      lastModified: now,
      changeFrequency: "weekly" as const,
      priority: 0.8,
    })),
  ];
}
