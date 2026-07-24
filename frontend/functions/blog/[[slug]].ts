const DEFAULT_API_ORIGIN = "http://104-168-30-212.sslip.io";
const SITE_URL = "https://diamscore.com";

interface PagesFunctionContext {
  request: Request;
  env?: { DIAMSCORE_API_ORIGIN?: string };
  params?: { slug?: string | string[] };
}

interface Article {
  slug: string;
  category: string;
  primaryKeyword: string;
  title: string;
  description: string;
  excerpt: string;
  author: string;
  reviewer: string;
  publishedAt: string;
  updatedAt: string;
  keyTakeaways: string[];
  sections: Array<{ heading: string; paragraphs: string[]; sourceIds: string[] }>;
  faq: Array<{ question: string; answer: string }>;
  sources: Array<{
    id: string;
    title: string;
    publisher: string;
    url: string;
    accessedAt: string;
  }>;
  cta: { label: string; href: string };
}

export async function onRequest(context: PagesFunctionContext) {
  if (context.request.method !== "GET" && context.request.method !== "HEAD") {
    return new Response("Method not allowed", { status: 405 });
  }

  const slugParam = context.params?.slug;
  const slug = Array.isArray(slugParam) ? slugParam.join("/") : slugParam || "";
  const apiOrigin = context.env?.DIAMSCORE_API_ORIGIN ?? DEFAULT_API_ORIGIN;
  const endpoint = slug
    ? `/api/content/articles/${encodeURIComponent(slug)}`
    : "/api/content/articles";

  try {
    const response = await fetch(new URL(endpoint, apiOrigin), {
      headers: { Accept: "application/json" },
    });
    if (response.status === 404) return html(notFoundPage(), 404);
    if (!response.ok) return html(serviceUnavailablePage(), 503);
    const payload = (await response.json()) as { article?: Article; articles?: Article[] };
    return html(slug ? articlePage(payload.article) : indexPage(payload.articles || []), 200);
  } catch {
    return html(serviceUnavailablePage(), 503);
  }
}

function html(body: string, status: number) {
  return new Response(body, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": status === 200 ? "public, max-age=0, s-maxage=30" : "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "strict-origin-when-cross-origin",
    },
  });
}

function shell(options: {
  title: string;
  description: string;
  canonical: string;
  body: string;
  jsonLd?: unknown[];
  robots?: string;
}) {
  const jsonLd = (options.jsonLd || [])
    .map(
      (value) =>
        `<script type="application/ld+json">${JSON.stringify(value).replace(/</g, "\\u003c")}</script>`,
    )
    .join("");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>${escapeHtml(options.title)}</title>
  <meta name="description" content="${escapeAttr(options.description)}">
  <meta name="robots" content="${escapeAttr(options.robots || "index,follow")}">
  <link rel="canonical" href="${escapeAttr(options.canonical)}">
  <meta property="og:title" content="${escapeAttr(options.title)}">
  <meta property="og:description" content="${escapeAttr(options.description)}">
  <meta property="og:url" content="${escapeAttr(options.canonical)}">
  <meta property="og:site_name" content="diamscore.com">
  <meta property="og:type" content="article">
  <meta name="twitter:card" content="summary_large_image">
  ${jsonLd}
  <style>${styles}</style>
</head>
<body>
  <header><nav><a class="brand" href="/">DS <span>DiamScore</span></a><a href="/blog">Blog</a><a class="button small" href="/#optimizer">Open optimizer</a></nav></header>
  ${options.body}
</body>
</html>`;
}

function indexPage(articles: Article[]) {
  const cards = articles.length
    ? articles
        .map(
          (article) => `<article class="card">
  <p class="eyebrow">${escapeHtml(label(article.category))}</p>
  <h2><a href="/blog/${escapeAttr(article.slug)}">${escapeHtml(article.title)}</a></h2>
  <p>${escapeHtml(article.excerpt)}</p>
  <div class="meta"><span>Updated ${escapeHtml(article.updatedAt)}</span><a href="/blog/${escapeAttr(article.slug)}">Read guide →</a></div>
</article>`,
        )
        .join("")
    : `<section class="card"><h2>Editorial review is in progress</h2><p>No approved articles are currently published.</p></section>`;
  return shell({
    title: "MLB DFS Strategy & Baseball Analytics Blog | DiamScore",
    description:
      "Practical MLB DFS strategy, lineup-building tutorials, baseball projection methods, weather analysis, injuries, and fantasy baseball guides.",
    canonical: `${SITE_URL}/blog`,
    body: `<main>
  <section class="hero"><p class="eyebrow">DiamScore Research</p><h1>MLB DFS strategy grounded in data, rules, and real workflows</h1><p>Evidence-backed guides for lineup optimization, projections, stacks, weather, injuries, and fantasy scoring.</p></section>
  <section class="grid">${cards}</section>
</main>`,
  });
}

function articlePage(article?: Article) {
  if (!article) return notFoundPage();
  const sourceMap = new Map(article.sources.map((source) => [source.id, source]));
  const sections = article.sections
    .map((section) => {
      const citations = section.sourceIds
        .map((id) => sourceMap.get(id))
        .filter(Boolean)
        .map(
          (source) =>
            `<a href="${escapeAttr(source!.url)}" rel="noopener noreferrer" target="_blank">${escapeHtml(source!.publisher)}</a>`,
        )
        .join(" · ");
      return `<section class="article-section"><h2>${escapeHtml(section.heading)}</h2>${section.paragraphs
        .map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`)
        .join("")}<div class="citations">${citations}</div></section>`;
    })
    .join("");
  const faq = article.faq
    .map(
      (item) =>
        `<details><summary>${escapeHtml(item.question)}</summary><p>${escapeHtml(item.answer)}</p></details>`,
    )
    .join("");
  const sources = article.sources
    .map(
      (source) =>
        `<li><a href="${escapeAttr(source.url)}" rel="noopener noreferrer" target="_blank">${escapeHtml(source.title)}</a> — ${escapeHtml(source.publisher)}, accessed ${escapeHtml(source.accessedAt)}</li>`,
    )
    .join("");
  const canonical = `${SITE_URL}/blog/${article.slug}`;
  return shell({
    title: article.title,
    description: article.description,
    canonical,
    jsonLd: [
      {
        "@context": "https://schema.org",
        "@type": "Article",
        headline: article.title,
        description: article.description,
        mainEntityOfPage: canonical,
        datePublished: article.publishedAt,
        dateModified: article.updatedAt,
        author: { "@type": "Organization", name: article.author },
        reviewedBy: { "@type": "Organization", name: article.reviewer },
        publisher: { "@type": "Organization", name: "DiamScore", url: SITE_URL },
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
    ],
    body: `<main class="article">
  <p class="breadcrumb"><a href="/">Home</a> / <a href="/blog">Blog</a> / ${escapeHtml(article.primaryKeyword)}</p>
  <p class="eyebrow">${escapeHtml(label(article.category))}</p>
  <h1>${escapeHtml(article.title)}</h1>
  <p class="lead">${escapeHtml(article.excerpt)}</p>
  <p class="byline">By ${escapeHtml(article.author)} · Reviewed by ${escapeHtml(article.reviewer)} · Updated ${escapeHtml(article.updatedAt)}</p>
  <section class="takeaways"><h2>Key takeaways</h2><ul>${article.keyTakeaways.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>
  ${sections}
  <section><h2>Frequently asked questions</h2>${faq}</section>
  <section class="cta"><h2>Apply the process to today’s slate</h2><p>Verify current lineups, projections, weather, injuries, and contest rules before building.</p><a class="button" href="${escapeAttr(article.cta.href)}">${escapeHtml(article.cta.label)}</a></section>
  <section><h2>Sources</h2><ol class="sources">${sources}</ol></section>
</main>`,
  });
}

function notFoundPage() {
  return shell({
    title: "Article not found | DiamScore",
    description: "The requested DiamScore article could not be found.",
    canonical: `${SITE_URL}/blog`,
    robots: "noindex,follow",
    body: `<main class="hero"><h1>Article not found</h1><p>The article may not be published yet.</p><a class="button" href="/blog">Return to the Blog</a></main>`,
  });
}

function serviceUnavailablePage() {
  return shell({
    title: "Blog temporarily unavailable | DiamScore",
    description: "The DiamScore Blog is temporarily unavailable.",
    canonical: `${SITE_URL}/blog`,
    robots: "noindex,follow",
    body: `<main class="hero"><h1>Blog temporarily unavailable</h1><p>Please try again shortly.</p></main>`,
  });
}

function escapeHtml(value: unknown) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(value: unknown) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function label(value: string) {
  return value
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

const styles = `
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#0f172a;background:#f8fafc}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#fff,#f8fafc)}
a{color:inherit}header{position:sticky;top:0;background:rgba(255,255,255,.94);border-bottom:1px solid #e2e8f0;backdrop-filter:blur(12px)}
nav{max-width:1120px;margin:auto;padding:14px 24px;display:flex;align-items:center;gap:24px}
.brand{margin-right:auto;text-decoration:none;font-weight:800;color:#0f766e}.brand span{color:#0f172a;margin-left:8px}
main{max-width:1120px;margin:auto;padding:56px 24px}.hero{padding-top:72px;padding-bottom:72px}
h1{font-size:clamp(2.5rem,6vw,4rem);line-height:1.05;letter-spacing:-.04em;max-width:900px;margin:12px 0 24px}
h2{font-size:1.5rem;letter-spacing:-.02em}p,li{line-height:1.75;color:#475569}
.eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:.75rem;font-weight:800;color:#0f766e}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}
.card,.takeaways,details{background:#fff;border:1px solid #e2e8f0;border-radius:20px;padding:24px;box-shadow:0 12px 32px rgba(15,23,42,.05)}
.card h2 a{text-decoration:none}.meta{display:flex;justify-content:space-between;gap:20px;font-size:.8rem;color:#64748b}
.meta a,.citations a,.sources a{color:#0f766e;font-weight:700}
.article{max-width:850px}.breadcrumb,.byline{font-size:.8rem}.lead{font-size:1.2rem}.article-section{margin:52px 0}
.article-section p{font-size:1.04rem}.citations{font-size:.78rem;margin-top:12px}
.takeaways{margin:36px 0;background:#ecfdf5;border-color:#99f6e4}.takeaways li{margin:8px 0}
details{margin:12px 0}summary{font-weight:700;cursor:pointer}.cta{background:#0f172a;color:#fff;border-radius:24px;padding:32px;margin:52px 0}.cta p{color:#cbd5e1}
.button{display:inline-block;background:#0f766e;color:#fff;text-decoration:none;font-weight:700;padding:12px 18px;border-radius:12px}.button.small{padding:8px 14px}
.sources{padding-left:20px}.sources li{margin:10px 0;font-size:.9rem}
`;
