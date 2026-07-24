import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getAllBlogArticles, getBlogArticle } from "@/lib/blog";
import { absoluteUrl, brandName, defaultOgImage, siteName, siteUrl } from "@/lib/seo";

interface BlogArticlePageProps {
  params: Promise<{ slug: string }>;
}

export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  const visible =
    process.env.NODE_ENV === "production"
      ? getAllBlogArticles()
      : getAllBlogArticles({ includeUnapproved: true });
  const params = visible.map((article) => ({ slug: article.slug }));
  return params.length > 0 ? params : [{ slug: "__no-published-articles__" }];
}

export async function generateMetadata({ params }: BlogArticlePageProps): Promise<Metadata> {
  const { slug } = await params;
  const includeUnapproved = process.env.NODE_ENV !== "production";
  const article = getBlogArticle(slug, { includeUnapproved });
  if (!article) return {};
  const canonical = absoluteUrl(`/blog/${article.slug}`);

  return {
    title: article.title,
    description: article.description,
    keywords: [article.primaryKeyword],
    alternates: { canonical },
    openGraph: {
      title: article.title,
      description: article.description,
      url: canonical,
      siteName,
      type: "article",
      publishedTime: article.publishedAt || undefined,
      modifiedTime: article.updatedAt,
      images: [defaultOgImage],
    },
    twitter: {
      card: "summary_large_image",
      title: article.title,
      description: article.description,
      images: [defaultOgImage],
    },
    robots:
      article.status === "approved"
        ? { index: true, follow: true }
        : { index: false, follow: false, noarchive: true },
  };
}

export default async function BlogArticlePage({ params }: BlogArticlePageProps) {
  const { slug } = await params;
  const includeUnapproved = process.env.NODE_ENV !== "production";
  const article = getBlogArticle(slug, { includeUnapproved });
  if (!article) notFound();
  const canonical = absoluteUrl(`/blog/${article.slug}`);
  const sourceById = new Map(article.sources.map((source) => [source.id, source]));
  const jsonLd = [
    {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: article.title,
      description: article.description,
      mainEntityOfPage: canonical,
      image: absoluteUrl(defaultOgImage),
      datePublished: article.publishedAt,
      dateModified: article.updatedAt,
      author: { "@type": "Organization", name: article.author, url: siteUrl },
      reviewedBy: { "@type": "Organization", name: article.reviewer },
      publisher: { "@type": "Organization", name: brandName, url: siteUrl },
    },
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: siteUrl },
        { "@type": "ListItem", position: 2, name: "Blog", item: absoluteUrl("/blog") },
        { "@type": "ListItem", position: 3, name: article.title, item: canonical },
      ],
    },
    {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: article.faq.map((item) => ({
        "@type": "Question",
        name: item.question,
        acceptedAnswer: { "@type": "Answer", text: item.answer },
      })),
    },
  ];

  return (
    <main className="min-h-screen text-accent-foreground">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <header className="border-b border-border bg-white/90 px-6 py-4 backdrop-blur md:px-8">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
          <Link className="text-sm font-semibold" href="/blog">← DiamScore Blog</Link>
          <Link className="rounded-full bg-primary px-4 py-2 text-xs font-semibold text-white" href="/#optimizer">
            Open optimizer
          </Link>
        </div>
      </header>

      <article className="mx-auto max-w-4xl px-6 py-12 md:px-8 md:py-16">
        <nav className="text-xs text-muted-foreground" aria-label="Breadcrumb">
          <Link href="/">Home</Link><span className="mx-2">/</span>
          <Link href="/blog">Blog</Link><span className="mx-2">/</span>
          <span>{article.primaryKeyword}</span>
        </nav>
        <p className="mt-8 text-xs font-semibold uppercase tracking-[0.18em] text-primary">{article.category}</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight md:text-6xl">{article.title}</h1>
        <p className="mt-6 text-lg leading-8 text-muted-foreground">{article.excerpt}</p>
        <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
          <span>By {article.author}</span>
          <span>Reviewed by {article.reviewer}</span>
          <span>Updated {article.updatedAt}</span>
        </div>

        <section className="mt-10 rounded-2xl border border-teal-200 bg-teal-50/70 p-6">
          <h2 className="text-lg font-semibold">Key takeaways</h2>
          <ul className="mt-3 space-y-2 text-sm leading-7 text-slate-700">
            {article.keyTakeaways.map((item) => <li key={item}>• {item}</li>)}
          </ul>
        </section>

        <div className="mt-12 space-y-12">
          {article.sections.map((section) => (
            <section key={section.heading}>
              <h2 className="text-2xl font-semibold tracking-tight">{section.heading}</h2>
              <div className="mt-4 space-y-4 text-base leading-8 text-slate-700">
                {section.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                {section.sourceIds.map((id) => {
                  const source = sourceById.get(id);
                  return source ? (
                    <a className="underline hover:text-primary" href={source.url} key={id} rel="noopener noreferrer" target="_blank">
                      {source.publisher}
                    </a>
                  ) : null;
                })}
              </div>
            </section>
          ))}
        </div>

        <section className="mt-14 border-t border-border pt-10">
          <h2 className="text-2xl font-semibold">Frequently asked questions</h2>
          <div className="mt-5 space-y-4">
            {article.faq.map((item) => (
              <details className="rounded-2xl border border-border bg-white p-5" key={item.question}>
                <summary className="cursor-pointer font-semibold">{item.question}</summary>
                <p className="mt-3 text-sm leading-7 text-muted-foreground">{item.answer}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="mt-14 rounded-3xl bg-slate-950 p-8 text-white">
          <h2 className="text-2xl font-semibold">Apply the process to today&apos;s slate</h2>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-300">
            Use the guide as a decision framework, then verify current lineups, projections, weather,
            injuries, and contest rules before building.
          </p>
          <Link className="mt-5 inline-flex rounded-xl bg-teal-500 px-5 py-3 text-sm font-semibold text-slate-950" href={article.cta.href}>
            {article.cta.label}
          </Link>
        </section>

        <section className="mt-12">
          <h2 className="text-lg font-semibold">Sources</h2>
          <ol className="mt-4 space-y-3 text-sm leading-6 text-muted-foreground">
            {article.sources.map((source) => (
              <li key={source.id}>
                <a className="font-medium text-primary underline" href={source.url} rel="noopener noreferrer" target="_blank">
                  {source.title}
                </a>{" "}
                — {source.publisher}, accessed {source.accessedAt}
              </li>
            ))}
          </ol>
        </section>
      </article>
    </main>
  );
}
