import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  absoluteUrl,
  brandName,
  defaultOgImage,
  seoPages,
  siteName,
  siteUrl,
} from "@/lib/seo";

interface KeywordPageProps {
  params: Promise<{ slug: string }>;
}

export function generateStaticParams() {
  return seoPages.map((page) => ({ slug: page.slug }));
}

export async function generateMetadata({ params }: KeywordPageProps): Promise<Metadata> {
  const { slug } = await params;
  const page = seoPages.find((item) => item.slug === slug);
  if (!page) return {};

  const canonical = absoluteUrl(`/${page.slug}`);
  return {
    title: page.title,
    description: page.description,
    keywords: [page.keyword, "mlb optimizer", "mlb dfs optimizer", "mlb lineup optimizer", "daily fantasy baseball optimizer"],
    alternates: {
      canonical,
    },
    openGraph: {
      title: page.title,
      description: page.description,
      url: canonical,
      siteName,
      type: "article",
      images: [
        {
          url: defaultOgImage,
          width: 1600,
          height: 1000,
          alt: `${brandName} ${page.keyword} dashboard for MLB DFS lineups`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: page.title,
      description: page.description,
      images: [defaultOgImage],
    },
    robots: {
      index: true,
      follow: true,
    },
  };
}

export default async function KeywordPage({ params }: KeywordPageProps) {
  const { slug } = await params;
  const page = seoPages.find((item) => item.slug === slug);
  if (!page) notFound();

  const canonical = absoluteUrl(`/${page.slug}`);
  const jsonLd = [
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "Home",
          item: siteUrl,
        },
        {
          "@type": "ListItem",
          position: 2,
          name: page.h1,
          item: canonical,
        },
      ],
    },
    {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: page.h1,
      description: page.description,
      image: absoluteUrl(defaultOgImage),
      mainEntityOfPage: canonical,
      author: {
        "@type": "Organization",
        name: brandName,
        url: siteUrl,
      },
      publisher: {
        "@type": "Organization",
        name: brandName,
        url: siteUrl,
      },
    },
    {
      "@context": "https://schema.org",
      "@type": "ImageObject",
      contentUrl: absoluteUrl(defaultOgImage),
      name: `${brandName} ${page.keyword} interface`,
      description: `${brandName} dashboard for ${page.keyword}, MLB DFS projections, salary rules, and stack-aware lineup building.`,
    },
  ];

  return (
    <main className="min-h-screen bg-background text-accent-foreground">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <header className="border-b border-border bg-white/90 px-6 py-4 backdrop-blur md:px-8">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
          <Link className="flex items-center gap-2 text-sm font-semibold" href="/">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-[11px] text-primary-foreground">
              DS
            </span>
            DiamScore
          </Link>
          <Link
            className="focus-ring rounded-full border border-border bg-white px-4 py-2 text-xs font-medium text-muted-foreground shadow-sm hover:text-primary"
            href="/#optimizer"
          >
            Open optimizer
          </Link>
        </div>
      </header>

      <article className="mx-auto max-w-5xl px-6 py-12 md:px-8 md:py-16">
        <nav className="mb-6 text-xs text-muted-foreground" aria-label="Breadcrumb">
          <Link className="hover:text-primary" href="/">
            Home
          </Link>
          <span className="mx-2">/</span>
          <span>{page.keyword}</span>
        </nav>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
          <div>
            <p className="mb-3 text-xs font-medium uppercase tracking-[0.18em] text-primary">{page.keyword}</p>
            <h1 className="max-w-3xl text-4xl font-semibold tracking-tight md:text-5xl">{page.h1}</h1>
            <p className="mt-5 max-w-3xl text-base leading-8 text-muted-foreground">{page.intro}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                className="focus-ring inline-flex h-11 items-center justify-center rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground shadow-lg shadow-teal-900/15"
                href="/#optimizer"
              >
                {page.cta}
              </Link>
              <Link
                className="focus-ring inline-flex h-11 items-center justify-center px-2 text-sm font-medium text-primary underline-offset-4 hover:underline"
                href="/#scoring"
              >
                Compare scoring rules
              </Link>
            </div>
          </div>

          <aside className="rounded-2xl border border-border bg-white p-5 shadow-sm">
            <img
              alt={`${brandName} ${page.keyword} dashboard showing MLB DFS projections and lineup controls`}
              className="aspect-[4/3] w-full rounded-xl object-cover"
              src={defaultOgImage}
            />
            <h2 className="mt-5 text-base font-semibold">What this page covers</h2>
            <ul className="mt-3 space-y-2 text-sm leading-6 text-muted-foreground">
              <li>Keyword focus: {page.keyword}</li>
              <li>DraftKings and FanDuel lineup logic</li>
              <li>Stacks, projections, salary rules, and CSV export</li>
            </ul>
          </aside>
        </div>

        <div className="mt-14 grid gap-5">
          {page.sections.map((section) => (
            <section key={section.heading} className="rounded-2xl border border-border bg-white p-6 shadow-sm">
              <h2 className="text-xl font-semibold tracking-tight">{section.heading}</h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">{section.body}</p>
            </section>
          ))}
        </div>

        <section className="mt-14 rounded-2xl border border-border bg-white p-6 shadow-sm">
          <h2 className="text-xl font-semibold tracking-tight">How to Use DiamScore for This Keyword Intent</h2>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <div>
              <h3 className="text-sm font-semibold">Check the slate</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Start with the current MLB player pool, lineup status, probable pitchers, salary data, and projection context.
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold">Set lineup rules</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Choose DraftKings or FanDuel, adjust stack settings, lock favorite plays, fade risky players, and set salary limits.
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold">Generate and review</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Run the optimizer, compare lineups, review warnings, and export builds when the slate is ready for entry.
              </p>
            </div>
          </div>
        </section>
      </article>
    </main>
  );
}
