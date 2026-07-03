"use client";

import {
  Activity,
  ChartBar,
  ChevronDown,
  Download,
  List,
  Mail,
  Radio,
  Settings,
  ShieldCheck,
  Sparkles,
  Trophy,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { LineupGrid } from "@/components/LineupGrid";
import { PlayerPool, projectionFor, salaryFor } from "@/components/PlayerPool";
import { SettingsPanel } from "@/components/SettingsPanel";
import { TopStacks } from "@/components/TopStacks";
import { fetchTodaysPlayers, runOptimizer, sendContactMessage } from "@/lib/api";
import type { OptimizeResponse, OptimizerSettings, PlayerPoolResponse, Site } from "@/lib/types";

interface CsvOverrideRow {
  name: string;
  team: string;
  playerId?: number;
  projection?: number;
  salary?: number;
  positions?: string[];
  externalId?: string;
  nameId?: string;
}

interface SalaryOverride {
  salary?: number;
  positions?: string[];
  externalId?: string;
  nameId?: string;
}

interface CsvMatchResult {
  matched: number;
  total: number;
  unmatched: string[];
}

type ActiveTab = "pool" | "lineups" | "settings";

const structuredData = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "WebSite",
      "@id": "https://diamscore.com/#website",
      name: "diamscore.com",
      url: "https://diamscore.com",
      publisher: {
        "@id": "https://diamscore.com/#organization",
      },
      potentialAction: {
        "@type": "SearchAction",
        target: "https://diamscore.com/?q={search_term_string}",
        "query-input": "required name=search_term_string",
      },
    },
    {
      "@type": "Organization",
      "@id": "https://diamscore.com/#organization",
      name: "DiamScore",
      url: "https://diamscore.com",
      email: "support@DiamScore.com",
      logo: {
        "@type": "ImageObject",
        url: "https://diamscore.com/diamscore-hero-analytics.png",
      },
    },
    {
      "@type": ["WebApplication", "SoftwareApplication"],
      "@id": "https://diamscore.com/#mlb-optimizer",
      name: "DiamScore MLB Optimizer",
      url: "https://diamscore.com",
      applicationCategory: "SportsApplication",
      operatingSystem: "Web",
      image: "https://diamscore.com/diamscore-hero-analytics.png",
      offers: {
        "@type": "Offer",
        price: "0",
        priceCurrency: "USD",
      },
      description:
        "Free MLB optimizer for DraftKings and FanDuel lineups with split-adjusted projections, live starting lineup data, stack controls, and CSV export.",
      featureList: [
        "Split-adjusted fantasy projections",
        "Live confirmed starting lineups",
        "DraftKings and FanDuel support",
        "Stacking rules and exposure control",
        "CSV export for bulk lineup entry",
      ],
    },
    {
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "MLB Optimizer",
          item: "https://diamscore.com",
        },
      ],
    },
    {
      "@type": "ImageObject",
      contentUrl: "https://diamscore.com/diamscore-hero-analytics.png",
      name: "DiamScore MLB optimizer dashboard",
      description:
        "DiamScore MLB optimizer dashboard showing DFS lineup projections, stack controls, salary rules, and slate analytics.",
    },
    {
      "@type": "FAQPage",
      mainEntity: [
        {
          "@type": "Question",
          name: "How does an MLB DFS lineup optimizer work?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "An MLB DFS lineup optimizer uses projections and contest rules to find high-scoring lineups within salary cap, roster, stack, lock, and fade constraints.",
          },
        },
        {
          "@type": "Question",
          name: "What is stacking in MLB DFS?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Stacking means selecting multiple batters from the same team to capture correlated runs, RBI, and plate appearance upside.",
          },
        },
        {
          "@type": "Question",
          name: "Does DiamScore support DraftKings and FanDuel?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Yes. DiamScore supports DraftKings and FanDuel MLB lineup optimization with site-specific scoring, salary settings, and CSV export.",
          },
        },
      ],
    },
  ],
};

const seoResourceLinks = [
  {
    href: "/mlb-dfs-optimizer",
    title: "MLB DFS Optimizer",
    body: "A guide for daily fantasy baseball players who want slate context, projections, stacks, and lineup rules in one MLB DFS optimizer workflow.",
  },
  {
    href: "/mlb-lineup-optimizer",
    title: "MLB Lineup Optimizer",
    body: "Learn how DiamScore turns player pools, locks, fades, salary limits, and team stacks into optimized MLB lineups for DFS contests.",
  },
  {
    href: "/draftkings-mlb-optimizer",
    title: "DraftKings MLB Optimizer",
    body: "Use DraftKings-specific salary cap logic, two-pitcher roster construction, DK scoring, projections, and CSV export.",
  },
  {
    href: "/fanduel-mlb-optimizer",
    title: "FanDuel MLB Optimizer",
    body: "Build FanDuel MLB lineups with FD scoring, one-pitcher roster logic, stack settings, live lineup status, and projection review.",
  },
];

const valueProps = [
  {
    icon: ChartBar,
    title: "Split-aware edge",
    desc: "Recent form weighted against pitcher handedness",
  },
  {
    icon: Radio,
    title: "Lineup signal",
    desc: "Confirmed batting orders, DNP filters, and starter context",
  },
  {
    icon: Trophy,
    title: "Contest-ready builds",
    desc: "Stack controls, lock/fade, and DK/FD CSV export",
  },
];

const howItWorks = [
  {
    step: "01",
    title: "Ingest slate context",
    body: "DiamScore pulls today's starting lineups, probable pitchers, batting order, and recent performance signals so the player pool starts from the same information sharp DFS players check manually.",
  },
  {
    step: "02",
    title: "Solve for ceiling and rules",
    body: "The optimizer searches for the highest-projected build under the DraftKings or FanDuel cap while respecting your stacks, locks, fades, salary floor, and contest-site roster rules.",
  },
  {
    step: "03",
    title: "Review and export",
    body: "Compare generated lineups, check salary and stack exposure, then export a CSV for bulk upload. The workflow is built for fast slate iteration without account friction.",
  },
];

const scoringRows = [
  ["Single", "+3 pts", "+3 pts"],
  ["Double", "+5 pts", "+6 pts"],
  ["Triple", "+8 pts", "+9 pts"],
  ["Home run", "+10 pts", "+12 pts"],
  ["RBI", "+2 pts", "+3.5 pts"],
  ["Run scored", "+2 pts", "+3.2 pts"],
  ["Walk", "+2 pts", "+3 pts"],
  ["Hit by pitch", "+2 pts", "+3 pts"],
  ["Stolen base", "+5 pts", "+6 pts"],
  ["Pitcher win", "+4 pts", "+6 pts"],
  ["Earned run allowed", "-2 pts", "-3 pts"],
  ["Strikeout (pitcher)", "+2 pts", "+3 pts"],
  ["Inning pitched", "+2.25 pts", "+3 pts"],
  ["Complete game", "+2.5 pts", "-"],
  ["No-hitter", "+5 pts", "-"],
];

const faqItems = [
  {
    q: "How does an MLB DFS lineup optimizer work?",
    a: "An optimizer uses linear programming to find the highest-projected lineup within the salary cap constraints of DraftKings or FanDuel. You provide, or we auto-generate, projected fantasy points for each player, and the algorithm returns the optimal combination for the roster slots and salary cap.",
  },
  {
    q: "What is stacking in MLB DFS?",
    a: "Stacking means selecting multiple batters from the same team's lineup. In baseball, runs are contagious: when a team scores, multiple batters in the same inning accumulate runs and RBIs together. A typical MLB stack is 4-5 batters from a team favored to score, facing a weak pitcher.",
  },
  {
    q: "What are split-adjusted projections?",
    a: "Split-adjusted projections account for how a batter performs specifically against left-handed or right-handed pitchers. A batter might average 12 DK points overall, but only 8 points vs left-handed pitchers. If tonight's opposing starter is left-handed, using the split average gives a more accurate projection than the overall average.",
  },
  {
    q: "How does batting order affect DFS value?",
    a: "Batters at the top of the order, especially positions 1-4, get more plate appearances per game than batters at the bottom. More plate appearances directly means more opportunities to score runs, earn RBIs, and rack up hits. DiamScore applies a multiplier to projections based on confirmed batting order position.",
  },
  {
    q: "What is the difference between DraftKings and FanDuel MLB?",
    a: "The main differences are scoring weights and roster construction. FanDuel awards more points for extra-base hits, but has only one pitcher slot. DraftKings uses two pitcher slots and awards 2.25 points per inning pitched. Salary caps also differ: $50,000 on DK, $35,000 on FanDuel.",
  },
  {
    q: "Is DiamScore free to use?",
    a: "Yes. You can generate up to 20 optimized lineups per day for free, with no account required. The free tier includes split-adjusted projections, live lineup status, stacking controls, lock/exclude, and CSV export for both DraftKings and FanDuel.",
  },
];

const footerLinks = [
  { href: "#optimizer", label: "MLB optimizer" },
  { href: "#stacks", label: "Today's top stacks" },
  { href: "/mlb-dfs-optimizer", label: "MLB DFS optimizer" },
  { href: "/mlb-lineup-optimizer", label: "MLB lineup optimizer" },
  { href: "/draftkings-mlb-optimizer", label: "DraftKings MLB" },
  { href: "/fanduel-mlb-optimizer", label: "FanDuel MLB" },
  { href: "#process", label: "How it works" },
  { href: "#scoring", label: "Scoring rules" },
  { href: "#faq", label: "FAQ" },
  { href: "#contact", label: "Contact" },
];

const navLinks = [
  { href: "#optimizer", label: "Optimizer" },
  { href: "#stacks", label: "Stacks" },
  { href: "#process", label: "How it works" },
  { href: "#scoring", label: "Scoring" },
  { href: "#faq", label: "FAQ" },
];

const heroStats = [
  { label: "Max entries", value: "20" },
  { label: "Sites", value: "DK/FD" },
  { label: "Workflow", value: "CSV" },
];

const loadingMessages = [
  "Calculating split matchups...",
  "Applying stacking rules...",
  "Solving lineup constraints...",
  "Almost there...",
];

const dataStatusLabel = {
  live: "Live data",
  cached: "Cached data",
  partial: "Partial data",
  mock: "Mock data",
  error: "Data issue",
};

export default function Home() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("pool");
  const [site, setSite] = useState<Site>("dk");
  const [numLineups, setNumLineups] = useState(5);
  const [settings, setSettings] = useState<OptimizerSettings>({
    stack_team: null,
    stack_count: 4,
    pitcher_vs_batter_same_team: "allow",
    min_salary_used: 49500,
    unique_lineups: true,
  });
  const [data, setData] = useState<PlayerPoolResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingPlayers, setLoadingPlayers] = useState(true);
  const [optimizing, setOptimizing] = useState(false);
  const [messageIndex, setMessageIndex] = useState(0);
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [overriddenPlayers, setOverriddenPlayers] = useState<Record<string, number>>({});
  const [salaryOverrides, setSalaryOverrides] = useState<Record<string, SalaryOverride>>({});
  const [exposureOverrides, setExposureOverrides] = useState<Record<string, number>>({});
  const [csvMatchResult, setCsvMatchResult] = useState<CsvMatchResult | null>(null);
  const [lockedPlayers, setLockedPlayers] = useState<Record<string, boolean>>({});
  const [excludedPlayers, setExcludedPlayers] = useState<Record<string, boolean>>({});
  const [contactEmail, setContactEmail] = useState("");
  const [contactMessage, setContactMessage] = useState("");
  const [contactCompany, setContactCompany] = useState("");
  const [contactStatus, setContactStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [sendingContact, setSendingContact] = useState(false);

  useEffect(() => {
    loadPlayers();
  }, []);

  useEffect(() => {
    if (!optimizing) return;
    const timer = window.setInterval(() => {
      setMessageIndex((current) => (current + 1) % loadingMessages.length);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [optimizing]);

  const players = data?.players ?? [];
  const teams = useMemo(() => Array.from(new Set(players.map((player) => player.team))).sort(), [players]);
  const lockedCount = Object.values(lockedPlayers).filter(Boolean).length;
  const excludedCount = Object.values(excludedPlayers).filter(Boolean).length;
  const csvMatchRate = csvMatchResult?.total ? csvMatchResult.matched / csvMatchResult.total : null;
  const salaryMissingCount = players.filter(
    (player) =>
      player.lineup_status !== "dnp" &&
      !excludedPlayers[String(player.mlbam_id)] &&
      (salaryOverrides[String(player.mlbam_id)]?.salary ?? salaryFor(player, site)) <= 0,
  ).length;
  const dataWarnings = (data?.warnings ?? [])
    .filter((warning) => process.env.NODE_ENV === "development" || !warning.toLowerCase().includes("mock data"))
    .map((warning) => (warning.toLowerCase().includes("mock data") ? "Mock data active in development." : warning));

  async function loadPlayers() {
    setLoadingPlayers(true);
    setError(null);
    try {
      setData(await fetchTodaysPlayers());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load players");
    } finally {
      setLoadingPlayers(false);
    }
  }

  async function handleContactSubmit() {
    setSendingContact(true);
    setContactStatus(null);
    try {
      const response = await sendContactMessage({
        email: contactEmail,
        message: contactMessage,
        company: contactCompany,
      });
      setContactStatus({ type: "success", message: response.message });
      setContactEmail("");
      setContactMessage("");
      setContactCompany("");
    } catch (err) {
      setContactStatus({
        type: "error",
        message: err instanceof Error ? err.message : "Could not send your message. Please try again later.",
      });
    } finally {
      setSendingContact(false);
    }
  }

  function changeSite(nextSite: Site) {
    setSite(nextSite);
    setSettings((current) => ({
      ...current,
      min_salary_used: nextSite === "dk" ? 49500 : 34500,
    }));
  }

  function changeSiteFromHeader(nextSite: Site) {
    changeSite(nextSite);
    window.requestAnimationFrame(() => {
      document.getElementById("optimizer")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function handleCsvOverrides(rows: CsvOverrideRow[]) {
    const nextProjections: Record<string, number> = {};
    const nextSalaries: Record<string, SalaryOverride> = {};
    const unmatched: string[] = [];
    let matched = 0;
    for (const row of rows) {
      const match = players.find(
        (player) =>
          (row.playerId ? player.mlbam_id === row.playerId : normalize(player.name) === normalize(row.name)) &&
          (!row.team || player.team.toLowerCase() === row.team.toLowerCase()),
      );
      if (match) {
        matched += 1;
        const id = String(match.mlbam_id);
        if (row.projection !== undefined) nextProjections[id] = row.projection;
        if (row.salary !== undefined || row.positions?.length || row.externalId || row.nameId) {
          nextSalaries[id] = {
            salary: row.salary,
            positions: row.positions,
            externalId: row.externalId,
            nameId: row.nameId,
          };
        }
      } else {
        unmatched.push(row.name);
      }
    }
    setCsvMatchResult({ matched, total: rows.length, unmatched });
    setOverriddenPlayers((prev) => ({ ...prev, ...nextProjections }));
    setSalaryOverrides((prev) => ({ ...prev, ...nextSalaries }));
  }

  async function optimize() {
    if (csvMatchRate !== null && csvMatchRate < 0.8) {
      setError(
        `CSV match rate is ${(csvMatchRate * 100).toFixed(0)}%. Upload a slate CSV with at least 80% matched players before optimizing.`,
      );
      return;
    }

    const eligiblePlayers = players.filter(
      (player) => player.lineup_status !== "dnp" && !excludedPlayers[String(player.mlbam_id)],
    );
    const salaryReadyPlayers = eligiblePlayers.filter(
      (player) => (salaryOverrides[String(player.mlbam_id)]?.salary ?? salaryFor(player, site)) > 0,
    );
    if (!salaryReadyPlayers.length || (salaryReadyPlayers.length < eligiblePlayers.length && !csvMatchResult)) {
      setError("Salary data is missing. Upload a DraftKings/FanDuel salary CSV before optimizing.");
      return;
    }

    setOptimizing(true);
    setError(null);
    try {
      const response = await runOptimizer({
        site,
        num_lineups: numLineups,
        settings,
        players: players.map((player) => {
          const id = String(player.mlbam_id);
          const salaryOverride = salaryOverrides[id];
          return {
            mlbam_id: player.mlbam_id,
            name: player.name,
            team: player.team,
            opponent: player.opponent,
            position: salaryOverride?.positions ?? player.position,
            salary: salaryOverride?.salary ?? salaryFor(player, site),
            projected_points: projectionFor(player, site, overriddenPlayers),
            lock: Boolean(lockedPlayers[id]),
            exclude:
              Boolean(excludedPlayers[id]) ||
              player.lineup_status === "dnp" ||
              (salaryOverride?.salary ?? salaryFor(player, site)) <= 0,
            max_exposure: exposureOverrides[id] ?? 1,
            lineup_status: player.lineup_status,
            external_id: salaryOverride?.externalId,
            name_id: salaryOverride?.nameId,
          };
        }),
      });
      setResult(response);
      setActiveTab("lineups");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Optimization failed";
      const constraintSummary =
        lockedCount || excludedCount ? ` Active constraints: ${lockedCount} locked, ${excludedCount} excluded.` : "";
      setError(`${detail}${constraintSummary}`);
    } finally {
      setOptimizing(false);
    }
  }

  const poolPanel = (
    <PlayerPool
      players={players}
      site={site}
      numLineups={numLineups}
      overriddenPlayers={overriddenPlayers}
      salaryOverrides={salaryOverrides}
      exposureOverrides={exposureOverrides}
      lockedPlayers={lockedPlayers}
      excludedPlayers={excludedPlayers}
      isOptimizing={optimizing}
      optimizingMessage={loadingMessages[messageIndex]}
      onOptimize={optimize}
      onProjectionOverride={(playerId, projection) =>
        setOverriddenPlayers((prev) => ({ ...prev, [playerId]: projection }))
      }
      onExposureChange={(playerId, exposure) =>
        setExposureOverrides((prev) => ({ ...prev, [playerId]: exposure }))
      }
      onLockToggle={(playerId) => setLockedPlayers((prev) => ({ ...prev, [playerId]: !prev[playerId] }))}
      onExcludeToggle={(playerId) => {
        setExcludedPlayers((prev) => ({ ...prev, [playerId]: !prev[playerId] }));
        setLockedPlayers((prev) => ({ ...prev, [playerId]: false }));
      }}
      salaryWarning={
        salaryMissingCount
          ? `${salaryMissingCount} players missing ${site.toUpperCase()} salary; upload CSV or they will be excluded.`
          : undefined
      }
      lastUpdated={data?.last_updated}
    />
  );

  const settingsPanel = (
    <SettingsPanel
      site={site}
      onSiteChange={changeSite}
      numLineups={numLineups}
      onNumLineupsChange={(value) => setNumLineups(Math.max(1, Math.min(20, value || 1)))}
      settings={settings}
      onSettingsChange={setSettings}
      teams={teams}
      csvMatchResult={csvMatchResult}
      onCsvOverrides={handleCsvOverrides}
    />
  );

  const lineupsPanel = (
    <LineupGrid
      lineups={result?.lineups ?? []}
      warnings={result?.warnings ?? []}
      solveTimeMs={result?.solve_time_ms}
      site={site}
    />
  );

  return (
    <div className="relative mx-auto min-h-screen max-w-2xl overflow-hidden bg-background md:max-w-none">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
      />
      <div className="magic-grid pointer-events-none absolute inset-x-0 top-0 h-[520px]" />

      <header className="sticky top-0 z-30 flex shrink-0 items-center justify-between border-b border-border/80 bg-white/85 px-4 py-3 backdrop-blur-xl md:min-h-16 md:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-primary/20 bg-primary text-sm font-semibold text-primary-foreground shadow-lg shadow-teal-900/10">
            DS
          </div>
          <div className="min-w-0">
            <span className="block text-sm font-semibold tracking-tight text-accent-foreground md:text-base">DiamScore</span>
            <span className="hidden text-xs text-muted-foreground md:block">MLB DFS lineup intelligence</span>
          </div>
        </div>
        <nav className="hidden items-center gap-1 rounded-full border border-border bg-white/80 p-1 shadow-sm md:flex" aria-label="Page sections">
          {navLinks.map(({ href, label }) => (
            <a
              key={href}
              className="focus-ring rounded-full px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-primary"
              href={href}
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="hidden items-center gap-2 text-xs text-muted-foreground lg:flex">
          <span className="inline-flex items-center gap-1 rounded-full border border-border bg-white px-3 py-1.5 shadow-sm">
            <ShieldCheck size={14} className="text-primary" />
            No account required
          </span>
          <div
            className="flex items-center gap-1 rounded-full border border-border bg-white p-1 shadow-sm"
            title="DK/FD selects the contest site. It changes salary cap, projections, optimizer rules, and CSV export format."
          >
            {(["dk", "fd"] as const).map((option) => (
              <button
                key={option}
                onClick={() => changeSiteFromHeader(option)}
                className={`focus-ring rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                  site === option ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-primary"
                }`}
                type="button"
              >
                {option.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <div className="flex gap-1.5 md:hidden">
          {(["dk", "fd"] as const).map((option) => (
            <button
              key={option}
              onClick={() => changeSiteFromHeader(option)}
              title="Select DraftKings or FanDuel contest settings"
              className={`focus-ring rounded-full px-3 py-1 text-xs transition-colors ${
                site === option
                  ? "bg-primary text-primary-foreground"
                  : "border border-border bg-white text-muted-foreground"
              }`}
              type="button"
            >
              {option.toUpperCase()}
            </button>
          ))}
        </div>
      </header>

      <nav
        className="sticky top-[65px] z-20 flex gap-2 overflow-x-auto border-b border-border/80 bg-white/85 px-4 py-2 backdrop-blur-xl md:hidden"
        aria-label="Mobile page sections"
      >
        {navLinks.map(({ href, label }) => (
          <a
            key={href}
            className="focus-ring shrink-0 rounded-full border border-border bg-white px-3 py-1.5 text-xs font-medium text-muted-foreground shadow-sm transition-colors hover:text-primary"
            href={href}
          >
            {label}
          </a>
        ))}
      </nav>

      <section id="home" className="relative z-10 overflow-hidden border-b border-border/70 px-6 py-12 md:px-8 md:py-16">
        <img
          src="/diamscore-hero-analytics.png"
          alt="DiamScore MLB optimizer dashboard with DFS lineup projections, stack controls, and slate analytics"
          className="pointer-events-none absolute inset-0 h-full w-full object-cover object-center opacity-45"
        />
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,rgba(255,255,255,0.96)_0%,rgba(255,255,255,0.88)_44%,rgba(255,255,255,0.58)_100%)]" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-36 bg-gradient-to-t from-background to-transparent" />
        <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-[minmax(0,1fr)_420px] lg:items-end">
          <div className="relative">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-white/80 px-3 py-1 text-xs font-medium text-primary shadow-sm backdrop-blur">
              <Sparkles size={14} />
              Built for MLB DFS slate decisions
            </div>
            <h1 className="max-w-4xl text-4xl font-semibold tracking-tight text-accent-foreground md:text-6xl">
              Free MLB DFS Lineup Optimizer
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-muted-foreground md:text-lg">
              Build DraftKings and FanDuel lineups with split-adjusted projections, live starting lineup data, and stack-aware
              controls tuned for serious DFS players.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a
                href="#optimizer"
                className="focus-ring inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-primary px-5 text-sm font-medium text-primary-foreground shadow-lg shadow-teal-900/15 transition-transform hover:-translate-y-0.5"
              >
                <Activity size={16} />
                Launch optimizer
              </a>
              <a
                href="#scoring"
                className="focus-ring inline-flex h-11 items-center justify-center px-2 text-sm font-medium text-primary underline-offset-4 transition-colors hover:text-accent-foreground hover:underline"
              >
                Compare scoring
              </a>
            </div>
          </div>

          <div className="magic-card rounded-2xl p-4 md:p-5">
            <div className="relative">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold">Slate readiness</div>
                  <div className="text-xs text-muted-foreground">Projection workflow snapshot</div>
                </div>
                <div className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">Live</div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {heroStats.map((stat) => (
                  <div key={stat.label} className="rounded-xl border border-border bg-white/80 p-3">
                    <div className="text-lg font-semibold tabular-nums">{stat.value}</div>
                    <div className="mt-1 text-[11px] text-muted-foreground">{stat.label}</div>
                  </div>
                ))}
              </div>
              <div className="mt-4 space-y-2">
                {valueProps.map(({ icon: Icon, title, desc }) => (
                  <div key={title} className="flex items-start gap-3 rounded-xl border border-border bg-white/70 p-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Icon size={16} />
                    </div>
                    <div>
                      <div className="text-sm font-medium">{title}</div>
                      <div className="mt-0.5 text-xs leading-5 text-muted-foreground">{desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section
        id="optimizer"
        className="relative z-10 mx-auto flex h-[calc(100dvh-3.5rem)] min-h-[660px] w-full max-w-7xl scroll-mt-24 flex-col px-3 py-4 md:h-[calc(100vh-4rem)] md:px-6 md:py-6"
      >
        {error ? (
          <div className="mb-3 shrink-0 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700 shadow-sm">{error}</div>
        ) : null}
        {data ? (
          <div
            className={`mb-3 shrink-0 rounded-xl border px-4 py-2 text-xs shadow-sm ${
              data.data_status === "live"
                ? "border-green-200 bg-green-50 text-green-800"
                : "border-yellow-200 bg-yellow-50 text-yellow-800"
            }`}
          >
            {dataStatusLabel[data.data_status]} · DFS projections are estimates for research only and do not guarantee
            contest results.
            {dataWarnings.length ? ` ${dataWarnings.join(" ")}` : ""}
          </div>
        ) : null}
        {data?.message ? (
          <div className="mb-3 shrink-0 rounded-xl border border-yellow-200 bg-yellow-50 px-4 py-2 text-xs text-yellow-800 shadow-sm">
            {data.message}
          </div>
        ) : null}

        {loadingPlayers ? (
          <main className="glass-panel grid flex-1 grid-cols-1 overflow-hidden rounded-2xl border border-border md:grid-cols-[18rem_minmax(0,1fr)_26.25rem]">
            <div className="hidden border-r border-border/80 p-4 md:block">
              <div className="mb-4 h-4 w-28 rounded bg-muted" />
              <div className="space-y-3">
                {Array.from({ length: 6 }).map((_, index) => (
                  <div key={index} className="h-12 rounded-xl bg-muted/70" />
                ))}
              </div>
            </div>
            <div className="min-w-0 p-4 md:p-5">
              <div className="mb-4 flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <Activity className="h-4 w-4 animate-pulse text-primary" />
                Loading slate data...
              </div>
              <div className="mb-4 h-10 rounded-xl bg-muted/80" />
              <div className="space-y-2">
                {Array.from({ length: 10 }).map((_, index) => (
                  <div key={index} className="h-12 rounded-xl border border-border bg-white/70" />
                ))}
              </div>
            </div>
            <div className="hidden border-l border-border/80 p-4 md:block">
              <div className="mb-4 h-4 w-36 rounded bg-muted" />
              <div className="space-y-3">
                {Array.from({ length: 8 }).map((_, index) => (
                  <div key={index} className="h-10 rounded-xl bg-muted/70" />
                ))}
              </div>
            </div>
          </main>
        ) : (
          <>
            <main className="glass-panel flex-1 overflow-y-auto rounded-2xl border border-border md:hidden">
              {activeTab === "pool" ? poolPanel : null}
              {activeTab === "lineups" ? lineupsPanel : null}
              {activeTab === "settings" ? settingsPanel : null}
            </main>

            <main className="glass-panel hidden min-h-0 flex-1 overflow-hidden rounded-2xl border border-border md:flex">
              <aside className="w-72 shrink-0 overflow-y-auto border-r border-border/80">{settingsPanel}</aside>
              <div className="flex min-w-0 flex-1 flex-col overflow-hidden">{poolPanel}</div>
              <aside className="w-[420px] shrink-0 overflow-y-auto border-l border-border/80">{lineupsPanel}</aside>
            </main>
          </>
        )}

        <nav className="mt-3 flex shrink-0 rounded-2xl border border-border bg-white p-1 shadow-sm md:hidden">
          {[
            { key: "pool", label: "Pool", icon: Users },
            { key: "lineups", label: "Lineups", icon: List },
            { key: "settings", label: "Settings", icon: Settings },
          ].map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key as ActiveTab)}
              className={`focus-ring flex flex-1 flex-col items-center gap-0.5 rounded-xl py-2 text-[10px] transition-colors ${
                activeTab === key ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground"
              }`}
              type="button"
            >
              <Icon size={18} />
              {label}
            </button>
          ))}
        </nav>
      </section>

      <TopStacks />

      <section id="mlb-optimizer-guide" className="relative z-10 scroll-mt-24 border-b border-border/70 px-6 py-14 md:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(320px,1fr)] lg:items-start">
            <div>
              <div className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-primary">MLB Optimizer Guide</div>
              <h2 className="text-2xl font-semibold tracking-tight">A practical MLB optimizer for DFS lineup decisions</h2>
              <p className="mt-4 text-sm leading-7 text-muted-foreground">
                DiamScore is built around the main MLB optimizer workflow: start with today&apos;s slate, review player
                projections, account for confirmed lineups, choose DraftKings or FanDuel rules, and generate lineups that
                respect salary, stacks, locks, and fades. The goal is to help daily fantasy baseball players move from
                research to contest-ready builds without losing sight of why each lineup was created.
              </p>
              <p className="mt-4 text-sm leading-7 text-muted-foreground">
                The optimizer is especially useful when you need to compare MLB DFS optimizer outputs against your own
                player takes. You can upload salary data, adjust projections, exclude inactive players, control team stack
                size, and export a CSV once the lineup set looks ready. That makes DiamScore useful as both a free MLB
                lineup optimizer and a slate review surface for late-breaking baseball news.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {seoResourceLinks.map(({ href, title, body }) => (
                <a
                  key={href}
                  className="focus-ring rounded-2xl border border-border bg-white p-5 shadow-sm transition-transform hover:-translate-y-0.5 hover:border-primary/30"
                  href={href}
                >
                  <h3 className="text-base font-semibold">{title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
                </a>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="process" className="relative z-10 scroll-mt-24 border-b border-border/70 px-6 py-14 md:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="mb-8 flex flex-col justify-between gap-3 md:flex-row md:items-end">
            <div>
              <div className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-primary">Process</div>
              <h2 className="text-2xl font-semibold tracking-tight">How DiamScore works</h2>
            </div>
            <p className="max-w-xl text-sm leading-6 text-muted-foreground">
              A tight workflow for players who need to move from slate context to contest-ready lineups quickly.
            </p>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {howItWorks.map(({ step, title, body }) => (
            <div key={step} className="rounded-2xl border border-border bg-white p-5 shadow-sm">
              <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-sm font-semibold tabular-nums text-primary">
                {step}
              </div>
              <h3 className="mb-2 text-base font-semibold">{title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
            </div>
          ))}
          </div>
        </div>
      </section>

      <section id="scoring" className="relative z-10 scroll-mt-24 border-b border-border/70 px-6 py-14 md:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="mb-6">
            <div className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-primary">Scoring</div>
            <h2 className="text-2xl font-semibold tracking-tight">DraftKings vs FanDuel MLB scoring rules</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              DiamScore uses the scoring below to calculate projected fantasy points for every player.
            </p>
          </div>
        <div className="overflow-x-auto rounded-2xl border border-border bg-white shadow-sm">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/60">
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Event</th>
                <th className="px-4 py-3 text-right font-medium">DraftKings</th>
                <th className="px-4 py-3 text-right font-medium">FanDuel</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {scoringRows.map(([event, dk, fd]) => (
                <tr key={event} className="hover:bg-muted/30">
                  <td className="px-4 py-3 text-muted-foreground">{event}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{dk}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{fd}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </div>
      </section>

      <section id="faq" className="relative z-10 scroll-mt-24 border-b border-border/70 px-6 py-14 md:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="mb-6">
            <div className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-primary">FAQ</div>
            <h2 className="text-2xl font-semibold tracking-tight">Frequently asked questions</h2>
          </div>
        <div className="max-w-3xl divide-y divide-border rounded-2xl border border-border bg-white px-5 shadow-sm">
          {faqItems.map(({ q, a }) => (
            <details key={q} className="group py-4">
              <summary className="flex cursor-pointer list-none items-center justify-between">
                <span className="pr-4 text-sm font-medium">{q}</span>
                <ChevronDown
                  size={16}
                  className="shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                />
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{a}</p>
            </details>
          ))}
        </div>
        </div>
      </section>

      <footer id="contact" className="relative z-10 scroll-mt-24 border-t border-border bg-white/70 px-6 py-8 backdrop-blur md:px-8">
        <div className="mx-auto grid max-w-7xl gap-8 md:grid-cols-[1fr_180px_minmax(280px,420px)]">
          <div>
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-[11px] text-primary-foreground">
                DS
              </span>
              DiamScore
            </div>
            <p className="max-w-xs text-xs text-muted-foreground">
              Free MLB DFS lineup optimizer for DraftKings and FanDuel. Projections updated daily from MLB Stats API.
            </p>
            <a className="mt-3 inline-flex items-center gap-2 text-xs font-medium text-primary" href="mailto:support@DiamScore.com">
              <Mail size={14} />
              support@DiamScore.com
            </a>
          </div>
          <nav className="flex flex-col gap-1" aria-label="Site links">
            {footerLinks.map(({ href, label }) => (
              <a key={href} href={href} className="text-xs text-muted-foreground transition-colors hover:text-primary">
                {label}
              </a>
            ))}
          </nav>
          <div
            className="rounded-2xl border border-border bg-white p-4 shadow-sm"
          >
            <div className="text-sm font-semibold">Get slate updates</div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Leave your email and we will collect feedback, feature requests, and early access interest.
            </p>
            <div className="mt-3 grid gap-2">
              <label className="sr-only" htmlFor="contact-email">Email</label>
              <input
                autoComplete="email"
                className="focus-ring h-10 rounded-xl border border-border bg-white px-3 text-sm shadow-sm"
                id="contact-email"
                maxLength={254}
                name="email"
                onChange={(event) => setContactEmail(event.target.value)}
                placeholder="you@example.com"
                required
                type="email"
                value={contactEmail}
              />
              <label className="sr-only" htmlFor="contact-message">Message</label>
              <textarea
                className="focus-ring min-h-20 resize-none rounded-xl border border-border bg-white px-3 py-2 text-sm shadow-sm"
                id="contact-message"
                maxLength={2000}
                name="message"
                onChange={(event) => setContactMessage(event.target.value)}
                placeholder="Tell us what you want DiamScore to add next"
                value={contactMessage}
              />
              <div className="hidden" aria-hidden="true">
                <label htmlFor="contact-company">Company</label>
                <input
                  autoComplete="off"
                  id="contact-company"
                  name="company"
                  onChange={(event) => setContactCompany(event.target.value)}
                  tabIndex={-1}
                  value={contactCompany}
                />
              </div>
              <button
                className="focus-ring flex h-10 w-full items-center justify-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-lg shadow-teal-900/10 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={sendingContact || !contactEmail}
                onClick={handleContactSubmit}
                type="button"
              >
                {sendingContact ? "Sending..." : "Send to support"}
              </button>
              {contactStatus ? (
                <div
                  className={`rounded-xl border px-3 py-2 text-xs ${
                    contactStatus.type === "success"
                      ? "border-green-200 bg-green-50 text-green-800"
                      : "border-red-200 bg-red-50 text-red-700"
                  }`}
                  role="status"
                >
                  {contactStatus.message}
                </div>
              ) : null}
            </div>
            <div className="mt-3 space-y-1 text-xs text-muted-foreground">
              <div>Projections updated daily</div>
              <div>Data from MLB Stats API</div>
              <div>Free forever for 20 lineups</div>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}
