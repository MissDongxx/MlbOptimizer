import type { Metadata } from "next";
import Link from "next/link";
import { getAllBlogArticles, getBlogCategories } from "@/lib/blog";
import { absoluteUrl, brandName, siteName } from "@/lib/seo";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "MLB DFS Strategy & Baseball Analytics Blog | DiamScore",
  description:
    "Practical MLB DFS strategy, lineup-building tutorials, baseball projection methods, weather analysis, injuries, and fantasy baseball guides from DiamScore.",
  alternates: { canonical: absoluteUrl("/blog") },
  openGraph: {
    title: "MLB DFS Strategy & Baseball Analytics Blog | DiamScore",
    description:
      "Evidence-backed MLB DFS strategy, lineup-building, projections, weather, injury, and fantasy baseball guides.",
    url: absoluteUrl("/blog"),
    siteName,
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "MLB DFS Strategy & Baseball Analytics Blog | DiamScore",
    description:
      "Evidence-backed MLB DFS strategy, lineup-building, projections, weather, injury, and fantasy baseball guides.",
  },
};

function label(value: string) {
  return value
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export default function BlogIndexPage() {
  const articles = getAllBlogArticles();
  const pendingArticles =
    process.env.NODE_ENV === "production"
      ? []
      : getAllBlogArticles({ includeUnapproved: true }).filter(
          (article) => article.status !== "approved",
        );
  const categories = getBlogCategories();

  return (
    <main className="min-h-screen text-accent-foreground">
      <header className="border-b border-border bg-white/90 px-6 py-4 backdrop-blur md:px-8">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <Link className="flex items-center gap-2 text-sm font-semibold" href="/">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-[11px] text-primary-foreground">
              DS
            </span>
            {brandName}
          </Link>
          <Link
            className="focus-ring rounded-full border border-border bg-white px-4 py-2 text-xs font-medium text-muted-foreground shadow-sm hover:text-primary"
            href="/#optimizer"
          >
            Open optimizer
          </Link>
        </div>
      </header>

      <section className="border-b border-border bg-white/70 px-6 py-14 md:px-8 md:py-20">
        <div className="mx-auto max-w-6xl">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">DiamScore Research</p>
          <h1 className="mt-4 max-w-4xl text-4xl font-semibold tracking-tight md:text-6xl">
            MLB DFS strategy grounded in data, rules, and real workflows
          </h1>
          <p className="mt-6 max-w-3xl text-base leading-8 text-muted-foreground">
            Learn how lineup optimization, projections, stacks, weather, injuries, and fantasy scoring
            work. Every published guide passes source, intent, and editorial review.
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-12 md:px-8">
        {pendingArticles.length > 0 && (
          <section className="mb-12 rounded-3xl border border-amber-300 bg-amber-50/80 p-6 shadow-sm md:p-8">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-700">
                  Local editorial preview
                </p>
                <h2 className="mt-2 text-2xl font-semibold tracking-tight">
                  Pending approval ({pendingArticles.length})
                </h2>
                <p className="mt-2 max-w-2xl text-sm leading-7 text-amber-900/70">
                  These drafts are visible only in local development. They remain excluded from the
                  production Blog and Sitemap until a named reviewer approves them.
                </p>
              </div>
              <span className="rounded-full border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-700">
                Not published
              </span>
            </div>

            <div className="mt-6 grid gap-4">
              {pendingArticles.map((article) => (
                <article className="rounded-2xl border border-amber-200 bg-white p-5" key={article.slug}>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded-full bg-amber-100 px-2.5 py-1 font-semibold uppercase text-amber-800">
                      {article.status}
                    </span>
                    <span className="text-muted-foreground">{label(article.category)}</span>
                    <span className="text-muted-foreground">Updated {article.updatedAt}</span>
                  </div>
                  <h3 className="mt-3 text-xl font-semibold tracking-tight">
                    <Link className="hover:text-primary" href={`/blog/${article.slug}`}>
                      {article.title}
                    </Link>
                  </h3>
                  <p className="mt-2 text-sm leading-7 text-muted-foreground">{article.excerpt}</p>
                  <div className="mt-4 flex flex-wrap gap-4 text-xs">
                    <span className="text-muted-foreground">
                      Reviewer: {article.reviewer}
                    </span>
                    <Link className="font-semibold text-amber-800 underline" href={`/blog/${article.slug}`}>
                      Open review preview →
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {categories.length > 0 && (
          <div className="mb-10 flex flex-wrap gap-2">
            {categories.map((category) => (
              <span
                className="rounded-full border border-border bg-white px-3 py-1.5 text-xs text-muted-foreground"
                key={category.slug}
              >
                {label(category.slug)} · {category.count}
              </span>
            ))}
          </div>
        )}

        {articles.length === 0 ? (
          <div className="rounded-3xl border border-border bg-white p-8 shadow-sm">
            <h2 className="text-xl font-semibold">Editorial review is in progress</h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-muted-foreground">
              The content system is active, but no article is public until it passes evidence checks,
              SEO validation, and named human approval.
            </p>
          </div>
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            {articles.map((article) => (
              <article className="rounded-3xl border border-border bg-white p-6 shadow-sm" key={article.slug}>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
                  {label(article.category)}
                </p>
                <h2 className="mt-3 text-2xl font-semibold tracking-tight">
                  <Link className="hover:text-primary" href={`/blog/${article.slug}`}>
                    {article.title}
                  </Link>
                </h2>
                <p className="mt-3 text-sm leading-7 text-muted-foreground">{article.excerpt}</p>
                <div className="mt-5 flex items-center justify-between gap-4 text-xs text-muted-foreground">
                  <span>Updated {article.updatedAt}</span>
                  <Link className="font-semibold text-primary" href={`/blog/${article.slug}`}>
                    Read guide →
                  </Link>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
