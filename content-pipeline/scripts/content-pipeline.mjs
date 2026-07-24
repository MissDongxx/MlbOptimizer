import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const pipelineDir = path.join(root, "content-pipeline");
const config = readJson(path.join(pipelineDir, "site.config.json"));
const gates = readJson(path.join(pipelineDir, "quality-gates.json"));
const queue = readJson(path.join(pipelineDir, "tasks.json"));
const contentDir = path.join(root, config.site.contentDirectory);

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function articleFiles() {
  if (!fs.existsSync(contentDir)) return [];
  return fs
    .readdirSync(contentDir)
    .filter((file) => file.endsWith(".json"))
    .map((file) => path.join(contentDir, file));
}

function words(value) {
  return String(value || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

function bodyText(article) {
  return [
    article.excerpt,
    ...(article.keyTakeaways || []),
    ...(article.sections || []).flatMap((section) => [
      section.heading,
      ...(section.paragraphs || []),
    ]),
    ...(article.faq || []).flatMap((item) => [item.question, item.answer]),
  ].join(" ");
}

function hostname(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function validateArticle(article, allArticles = []) {
  const errors = [];
  const warnings = [];
  const seo = gates.seo;
  const sourceIds = new Set((article.sources || []).map((source) => source.id));
  const text = bodyText(article);
  const textWords = words(text);
  const keyword = String(article.primaryKeyword || "").toLowerCase();
  const occurrences = keyword
    ? (text.toLowerCase().match(new RegExp(keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || []).length
    : 0;
  const keywordDensity = textWords.length ? occurrences / textWords.length : 0;

  for (const field of [
    "schemaVersion",
    "status",
    "slug",
    "category",
    "primaryKeyword",
    "intent",
    "title",
    "description",
    "excerpt",
    "author",
    "reviewer",
    "updatedAt",
  ]) {
    if (article[field] === undefined || article[field] === null || article[field] === "") {
      errors.push(`Missing required field: ${field}`);
    }
  }

  if (!["draft", "review", "approved"].includes(article.status)) {
    errors.push("status must be draft, review, or approved");
  }
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(article.slug || "")) {
    errors.push("slug must use lowercase kebab-case");
  }
  if ((article.title || "").length < seo.titleMinCharacters) {
    warnings.push(`title is shorter than ${seo.titleMinCharacters} characters`);
  }
  if ((article.title || "").length > seo.titleMaxCharacters) {
    errors.push(`title exceeds ${seo.titleMaxCharacters} characters`);
  }
  if ((article.description || "").length < seo.descriptionMinCharacters) {
    warnings.push(`description is shorter than ${seo.descriptionMinCharacters} characters`);
  }
  if ((article.description || "").length > seo.descriptionMaxCharacters) {
    errors.push(`description exceeds ${seo.descriptionMaxCharacters} characters`);
  }
  if (textWords.length < seo.minimumBodyWords) {
    errors.push(`body has ${textWords.length} words; minimum is ${seo.minimumBodyWords}`);
  }
  if (keywordDensity > seo.maximumPrimaryKeywordDensity) {
    errors.push(`primary keyword density ${keywordDensity.toFixed(3)} exceeds ${seo.maximumPrimaryKeywordDensity}`);
  }
  if ((article.sections || []).length < seo.minimumSections) {
    errors.push(`requires at least ${seo.minimumSections} sections`);
  }
  if ((article.faq || []).length < seo.minimumFaqItems) {
    errors.push(`requires at least ${seo.minimumFaqItems} FAQ items`);
  }
  if ((article.internalLinks || []).length < seo.minimumInternalLinks) {
    errors.push(`requires at least ${seo.minimumInternalLinks} internal links`);
  }
  if ((article.sources || []).length < config.sources.minimum) {
    errors.push(`requires at least ${config.sources.minimum} sources`);
  }
  if ((article.sources || []).filter((source) => source.type === "primary").length < config.sources.minimumPrimary) {
    errors.push(`requires at least ${config.sources.minimumPrimary} primary source`);
  }
  for (const source of article.sources || []) {
    if (!source.id || !source.title || !source.publisher || !source.url) {
      errors.push("every source requires id, title, publisher, and url");
    }
    if (gates.evidence.requireAccessDate && !source.accessedAt) {
      errors.push(`source ${source.id || "(unknown)"} is missing accessedAt`);
    }
    const domain = hostname(source.url);
    if (!domain) errors.push(`source ${source.id || "(unknown)"} has an invalid URL`);
    if (
      source.type === "primary" &&
      !config.sources.primaryDomains.some((allowed) => domain === allowed || domain.endsWith(`.${allowed}`))
    ) {
      warnings.push(`primary source ${source.id} uses an unlisted primary domain: ${domain}`);
    }
  }
  if (gates.evidence.requireClaimSourceMapping) {
    for (const section of article.sections || []) {
      if (!Array.isArray(section.sourceIds) || section.sourceIds.length === 0) {
        errors.push(`section "${section.heading || "(untitled)"}" has no sourceIds`);
      } else {
        for (const id of section.sourceIds) {
          if (!sourceIds.has(id)) errors.push(`section "${section.heading}" references unknown source ${id}`);
        }
      }
    }
  }
  if (
    gates.evidence.requireLimitationsSection &&
    !(article.sections || []).some((section) => /limit|caveat|verify|uncertainty/i.test(section.heading || ""))
  ) {
    errors.push("requires a limitations, caveats, uncertainty, or verification section");
  }
  for (const blocked of config.editorial.blockedTopics) {
    if (new RegExp(`\\b${blocked.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(text)) {
      warnings.push(`review blocked-topic match: ${blocked}`);
    }
  }
  const duplicate = allArticles.find(
    (candidate) =>
      candidate.slug !== article.slug &&
      String(candidate.primaryKeyword || "").toLowerCase() === keyword,
  );
  if (duplicate) errors.push(`duplicate primary keyword with ${duplicate.slug}`);
  if (article.status === "approved") {
    if (!article.publishedAt) errors.push("approved article requires publishedAt");
    if (
      gates.publishing.requireNamedReviewer &&
      (!article.reviewer || /pending/i.test(article.reviewer))
    ) {
      errors.push("approved article requires a named reviewer");
    }
  }

  return {
    slug: article.slug,
    status: article.status,
    words: textWords.length,
    keywordDensity: Number(keywordDensity.toFixed(4)),
    errors,
    warnings,
    passed: errors.length === 0,
  };
}

function loadArticles() {
  return articleFiles().map((file) => ({ file, article: readJson(file) }));
}

function printResult(result) {
  const marker = result.passed ? "PASS" : "FAIL";
  console.log(`${marker} ${result.slug} (${result.words} words, status=${result.status})`);
  for (const error of result.errors) console.log(`  ERROR: ${error}`);
  for (const warning of result.warnings) console.log(`  WARN: ${warning}`);
}

const command = process.argv[2] || "status";
const loaded = loadArticles();
const articles = loaded.map(({ article }) => article);

if (command === "status") {
  const taskCounts = Object.fromEntries(
    ["queued", "researching", "drafted", "review", "approved", "blocked"].map((status) => [
      status,
      queue.tasks.filter((task) => task.status === status).length,
    ]),
  );
  const articleCounts = Object.fromEntries(
    ["draft", "review", "approved"].map((status) => [
      status,
      articles.filter((article) => article.status === status).length,
    ]),
  );
  console.log(JSON.stringify({ tasks: taskCounts, articles: articleCounts }, null, 2));
} else if (command === "next") {
  const next = [...queue.tasks]
    .filter((task) => task.status === "queued")
    .sort((a, b) => a.priority - b.priority)[0];
  if (!next) {
    console.log("No queued content tasks.");
    process.exit(2);
  }
  console.log(JSON.stringify(next, null, 2));
} else if (command === "validate") {
  const slug = process.argv[3];
  if (!slug) throw new Error("Usage: npm run content:validate -- <slug>");
  const match = loaded.find(({ article }) => article.slug === slug);
  if (!match) throw new Error(`Article not found: ${slug}`);
  const result = validateArticle(match.article, articles);
  printResult(result);
  process.exit(result.passed ? 0 : 1);
} else if (command === "validate-all") {
  const results = articles.map((article) => validateArticle(article, articles));
  for (const result of results) printResult(result);
  process.exit(results.every((result) => result.passed) ? 0 : 1);
} else {
  throw new Error(`Unknown command: ${command}`);
}
