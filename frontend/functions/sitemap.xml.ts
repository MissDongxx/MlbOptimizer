const DEFAULT_API_ORIGIN = "http://104-168-30-212.sslip.io";
const SITE_URL = "https://diamscore.com";

interface PagesFunctionContext {
  env?: { DIAMSCORE_API_ORIGIN?: string };
}

interface Article {
  slug: string;
  updatedAt: string;
}

export async function onRequest(context: PagesFunctionContext) {
  const apiOrigin = context.env?.DIAMSCORE_API_ORIGIN ?? DEFAULT_API_ORIGIN;
  let articles: Article[] = [];
  try {
    const response = await fetch(new URL("/api/content/articles", apiOrigin), {
      headers: { Accept: "application/json" },
    });
    if (response.ok) {
      const payload = (await response.json()) as { articles?: Article[] };
      articles = payload.articles || [];
    }
  } catch {
    // Preserve core sitemap entries when the content API is temporarily unavailable.
  }

  const core = [
    { path: "/", changefreq: "daily", priority: "1.0" },
    { path: "/mlb-dfs-optimizer", changefreq: "weekly", priority: "0.8" },
    { path: "/mlb-lineup-optimizer", changefreq: "weekly", priority: "0.8" },
    { path: "/draftkings-mlb-optimizer", changefreq: "weekly", priority: "0.8" },
    { path: "/fanduel-mlb-optimizer", changefreq: "weekly", priority: "0.8" },
    { path: "/blog", changefreq: "weekly", priority: "0.7" },
  ];
  const urls = [
    ...core.map(
      (entry) => `<url><loc>${SITE_URL}${entry.path}</loc><changefreq>${entry.changefreq}</changefreq><priority>${entry.priority}</priority></url>`,
    ),
    ...articles.map(
      (article) =>
        `<url><loc>${SITE_URL}/blog/${escapeXml(article.slug)}</loc><lastmod>${escapeXml(article.updatedAt)}</lastmod><changefreq>monthly</changefreq><priority>0.65</priority></url>`,
    ),
  ];
  const xml = `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls.join("")}</urlset>`;
  return new Response(xml, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=30",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function escapeXml(value: unknown) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}
