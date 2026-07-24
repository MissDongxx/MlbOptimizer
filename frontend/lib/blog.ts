import fs from "node:fs";
import path from "node:path";

export interface BlogSource {
  id: string;
  title: string;
  publisher: string;
  url: string;
  accessedAt: string;
  type: "primary" | "secondary";
}

export interface BlogArticle {
  schemaVersion: number;
  status: "draft" | "review" | "approved";
  slug: string;
  category: string;
  primaryKeyword: string;
  intent: string;
  title: string;
  description: string;
  excerpt: string;
  author: string;
  reviewer: string;
  publishedAt: string | null;
  updatedAt: string;
  keyTakeaways: string[];
  sections: Array<{
    heading: string;
    paragraphs: string[];
    sourceIds: string[];
  }>;
  faq: Array<{ question: string; answer: string }>;
  sources: BlogSource[];
  internalLinks: Array<{ label: string; href: string }>;
  cta: { label: string; href: string };
}

function contentDirectory() {
  const candidates = [
    path.join(process.cwd(), "content", "blog"),
    path.join(process.cwd(), "frontend", "content", "blog"),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? candidates[0];
}

function readArticles(): BlogArticle[] {
  const directory = contentDirectory();
  if (!fs.existsSync(directory)) return [];

  return fs
    .readdirSync(directory)
    .filter((file) => file.endsWith(".json"))
    .map((file) => JSON.parse(fs.readFileSync(path.join(directory, file), "utf8")) as BlogArticle);
}

export function getAllBlogArticles(options: { includeUnapproved?: boolean } = {}) {
  return readArticles()
    .filter((article) => options.includeUnapproved || article.status === "approved")
    .sort((a, b) => (b.publishedAt || b.updatedAt).localeCompare(a.publishedAt || a.updatedAt));
}

export function getBlogArticle(slug: string, options: { includeUnapproved?: boolean } = {}) {
  return getAllBlogArticles(options).find((article) => article.slug === slug);
}

export function getBlogCategories() {
  const categories = new Map<string, number>();
  for (const article of getAllBlogArticles()) {
    categories.set(article.category, (categories.get(article.category) || 0) + 1);
  }
  return [...categories.entries()].map(([slug, count]) => ({ slug, count }));
}
