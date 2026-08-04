import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

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

function normalize(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[’']/g, "'")
    .replace(/[^a-z0-9'\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function includesPhrase(value, phrase) {
  const normalizedPhrase = normalize(phrase);
  return normalizedPhrase.length > 0 && normalize(value).includes(normalizedPhrase);
}

function keywordForms(article) {
  return [article.primaryKeyword, ...(article.primaryKeywordVariants || [])].filter(Boolean);
}

function includesKeywordForm(value, article) {
  return keywordForms(article).some((form) => includesPhrase(value, form));
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

function openingText(article, wordCount) {
  return words([
    article.excerpt,
    ...(article.keyTakeaways || []),
    ...(article.sections?.[0]?.paragraphs || []),
  ].join(" ")).slice(0, wordCount).join(" ");
}

function hostname(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function keywordTokens(value) {
  const stop = new Set(["a", "an", "and", "for", "how", "in", "of", "the", "to", "with"]);
  return new Set(words(normalize(value)).filter((token) => token.length > 1 && !stop.has(token)));
}

function tokenSimilarity(left, right) {
  const a = keywordTokens(left);
  const b = keywordTokens(right);
  if (a.size === 0 || b.size === 0) return 0;
  const intersection = [...a].filter((token) => b.has(token)).length;
  const union = new Set([...a, ...b]).size;
  return intersection / union;
}

function isStrictArticle(article) {
  return Number(article.seoAuditVersion || 1) >= Number(gates.seo.currentAuditVersion || 2);
}

function numericTokens(value) {
  return String(value || "").match(/\b\d+(?:\.\d+)?%?\b/g) || [];
}

function validateClaimLedger(article, sourceIds, errors) {
  const ledger = article.claimLedger || [];
  if (!Array.isArray(ledger) || ledger.length === 0) {
    errors.push("strict SEO articles require a non-empty claimLedger");
    return;
  }

  const allowedTypes = new Set(["factual", "numeric", "time-sensitive", "fictional"]);
  const allowedActions = new Set(["verified", "softened", "removed", "fictional"]);
  for (const entry of ledger) {
    if (!entry.claim || !allowedTypes.has(entry.type) || !allowedActions.has(entry.action)) {
      errors.push("every claimLedger entry requires claim, valid type, and valid action");
      continue;
    }
    if (entry.type === "fictional" || entry.action === "fictional") {
      if (entry.type !== "fictional" || entry.action !== "fictional") {
        errors.push(`fictional claim "${entry.claim}" must use type=fictional and action=fictional`);
      }
      continue;
    }
    if (!entry.checkedAt) errors.push(`claim "${entry.claim}" is missing checkedAt`);
    if (entry.action === "removed") continue;
    if (!Array.isArray(entry.sourceIds) || entry.sourceIds.length === 0) {
      errors.push(`claim "${entry.claim}" requires sourceIds`);
    } else {
      for (const id of entry.sourceIds) {
        if (!sourceIds.has(id)) errors.push(`claim "${entry.claim}" references unknown source ${id}`);
      }
    }
  }

  const ledgerNumbers = new Set(ledger.flatMap((entry) => numericTokens(entry.claim)));
  for (const section of article.sections || []) {
    for (const paragraph of section.paragraphs || []) {
      const numbers = numericTokens(paragraph);
      if (numbers.length === 0 || /fictional|illustrative|invented/i.test(paragraph)) continue;
      for (const number of numbers) {
        if (!ledgerNumbers.has(number)) {
          errors.push(`numeric claim ${number} in section "${section.heading}" is missing from claimLedger`);
        }
      }
    }
  }
}

function validateEditorialAudit(article, errors) {
  const audit = article.editorialAudit;
  if (!audit || typeof audit !== "object") {
    errors.push("strict SEO articles require editorialAudit");
    return;
  }
  for (const field of ["searchIntent", "contentDepth", "factCheck", "humanization"]) {
    if (audit[field] !== "pass") errors.push(`editorialAudit.${field} must be pass`);
  }
  if (!audit.auditedAt) errors.push("editorialAudit.auditedAt is required");
  if (!audit.notes || String(audit.notes).trim().length < 20) {
    errors.push("editorialAudit.notes must record the substantive review");
  }
}

export function validateArticle(article, allArticles = []) {
  const errors = [];
  const warnings = [];
  const seo = gates.seo;
  const strict = isStrictArticle(article);
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
    errors.push(`title is shorter than ${seo.titleMinCharacters} characters`);
  }
  if ((article.title || "").length > seo.titleMaxCharacters) {
    errors.push(`title exceeds ${seo.titleMaxCharacters} characters`);
  }
  if ((article.description || "").length < seo.descriptionMinCharacters) {
    errors.push(`description is shorter than ${seo.descriptionMinCharacters} characters`);
  }
  if ((article.description || "").length > seo.descriptionMaxCharacters) {
    errors.push(`description exceeds ${seo.descriptionMaxCharacters} characters`);
  }
  if (seo.requirePrimaryKeywordInTitle && !includesKeywordForm(article.title, article)) {
    errors.push("title must include the primary keyword or an approved variant");
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

  if (strict) {
    if (
      article.primaryKeywordVariants !== undefined &&
      (!Array.isArray(article.primaryKeywordVariants) ||
        article.primaryKeywordVariants.some((variant) => !String(variant).trim()))
    ) {
      errors.push("primaryKeywordVariants must be an array of non-empty strings");
    }
    const supporting = article.supportingKeywords || [];
    if (!Array.isArray(supporting) || supporting.length < seo.minimumSupportingKeywords) {
      errors.push(`requires at least ${seo.minimumSupportingKeywords} supportingKeywords`);
    }
    if (supporting.length > seo.maximumSupportingKeywords) {
      errors.push(`supports at most ${seo.maximumSupportingKeywords} supportingKeywords`);
    }
    for (const supportingKeyword of supporting) {
      if (keywordForms(article).some((form) => normalize(form) === normalize(supportingKeyword))) {
        errors.push(`supporting keyword duplicates a primary keyword form: ${supportingKeyword}`);
      }
      if (!includesPhrase(text, supportingKeyword)) {
        errors.push(`supporting keyword is not covered naturally: ${supportingKeyword}`);
      }
    }
    if (
      seo.requirePrimaryKeywordInOpening &&
      !includesKeywordForm(openingText(article, seo.openingWordWindow), article)
    ) {
      errors.push(`primary keyword must appear within the opening ${seo.openingWordWindow} words`);
    }
    if (
      seo.requirePrimaryKeywordInSectionHeading &&
      !(article.sections || []).some((section) => includesKeywordForm(section.heading, article))
    ) {
      errors.push("at least one section heading must include the primary keyword");
    }
    const conclusion = (article.sections || []).at(-1);
    if (
      seo.requireConclusionSection &&
      !/conclusion|bottom line|final take|next steps|what to do next/i.test(conclusion?.heading || "")
    ) {
      errors.push("final section must be an explicit conclusion or next-steps section");
    }
    if (
      seo.requirePrimaryKeywordInConclusion &&
      !includesKeywordForm([conclusion?.heading, ...(conclusion?.paragraphs || [])].join(" "), article)
    ) {
      errors.push("conclusion must include the primary keyword");
    }
    if (
      seo.requireContentDifferentiation &&
      (!article.contentDifferentiation || String(article.contentDifferentiation).trim().length < 40)
    ) {
      errors.push("contentDifferentiation must explain how this intent differs from existing pages");
    }
    if (gates.evidence.requireClaimLedger) validateClaimLedger(article, sourceIds, errors);
    if (gates.evidence.requireEditorialAudit) validateEditorialAudit(article, errors);
    for (const disclosure of config.editorial.requiredDisclosures || []) {
      if (!includesPhrase(text, disclosure)) errors.push(`missing required disclosure: ${disclosure}`);
    }
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
      errors.push(`blocked-topic match: ${blocked}`);
    }
  }
  const duplicate = allArticles.find(
    (candidate) =>
      candidate.slug !== article.slug &&
      String(candidate.primaryKeyword || "").toLowerCase() === keyword,
  );
  if (duplicate) errors.push(`duplicate primary keyword with ${duplicate.slug}`);

  for (const candidate of allArticles) {
    if (candidate.slug === article.slug || candidate.intent !== article.intent) continue;
    const similarity = tokenSimilarity(article.primaryKeyword, candidate.primaryKeyword);
    if (similarity >= 0.6) {
      warnings.push(
        `possible search-intent overlap with ${candidate.slug} (keyword token similarity ${similarity.toFixed(2)})`,
      );
    }
  }

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
    auditVersion: Number(article.seoAuditVersion || 1),
    words: textWords.length,
    keywordDensity: Number(keywordDensity.toFixed(4)),
    errors,
    warnings,
    passed: errors.length === 0,
  };
}

async function checkSource(source) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), gates.evidence.sourceRequestTimeoutMs || 15000);
  try {
    const response = await fetch(source.url, {
      method: "GET",
      redirect: "follow",
      signal: controller.signal,
      headers: {
        "user-agent": "DiamScoreContentValidator/2.0 (+https://diamscore.com)",
        range: "bytes=0-1024",
      },
    });
    return {
      id: source.id,
      url: source.url,
      status: response.status,
      finalUrl: response.url,
      passed: response.status >= 200 && response.status < 400,
      error: null,
    };
  } catch (error) {
    return {
      id: source.id,
      url: source.url,
      status: null,
      finalUrl: null,
      passed: false,
      error: error instanceof Error ? error.message : String(error),
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function validateSources(article) {
  const results = [];
  const sources = article.sources || [];
  const concurrency = 4;
  for (let index = 0; index < sources.length; index += concurrency) {
    results.push(...(await Promise.all(sources.slice(index, index + concurrency).map(checkSource))));
  }
  return results;
}

function loadArticles() {
  return articleFiles().map((file) => ({ file, article: readJson(file) }));
}

function printResult(result) {
  const marker = result.passed ? "PASS" : "FAIL";
  console.log(
    `${marker} ${result.slug} (${result.words} words, status=${result.status}, seoAuditVersion=${result.auditVersion})`,
  );
  for (const error of result.errors) console.log(`  ERROR: ${error}`);
  for (const warning of result.warnings) console.log(`  WARN: ${warning}`);
}

function printSourceResult(result) {
  const marker = result.passed ? "PASS" : "FAIL";
  const detail = result.error || `HTTP ${result.status}${result.finalUrl && result.finalUrl !== result.url ? ` -> ${result.finalUrl}` : ""}`;
  console.log(`${marker} ${result.id}: ${detail}`);
}

function resolveRenderedHtml(slug, explicitRoot) {
  const roots = explicitRoot
    ? [path.resolve(root, explicitRoot)]
    : [path.join(root, "frontend", "out"), path.join(root, "out")];
  for (const outputRoot of roots) {
    const candidates = [
      path.join(outputRoot, "blog", slug, "index.html"),
      path.join(outputRoot, "blog", `${slug}.html`),
    ];
    for (const candidate of candidates) {
      if (fs.existsSync(candidate)) return candidate;
    }
  }
  return null;
}

function verifyRenderedArticle(article, explicitRoot) {
  const file = resolveRenderedHtml(article.slug, explicitRoot);
  const errors = [];
  if (!file) {
    return { passed: false, file: null, errors: ["rendered article HTML was not found"] };
  }
  const html = fs.readFileSync(file, "utf8");
  const h1Count = (html.match(/<h1\b/gi) || []).length;
  const canonical = `${config.site.url}${config.site.blogBasePath}/${article.slug}`;
  if (h1Count !== 1) errors.push(`expected exactly one H1; found ${h1Count}`);
  if (!html.includes(canonical)) errors.push(`canonical URL is missing: ${canonical}`);
  if (/noindex/i.test(html)) errors.push("approved rendered article contains noindex");
  for (const schemaType of ["Article", "BreadcrumbList", "FAQPage"]) {
    const direct = `"@type":"${schemaType}"`;
    const escaped = `&quot;@type&quot;:&quot;${schemaType}&quot;`;
    if (!html.includes(direct) && !html.includes(escaped)) {
      errors.push(`missing ${schemaType} structured data`);
    }
  }
  return { passed: errors.length === 0, file, errors };
}

export async function main(argv = process.argv.slice(2)) {
  const command = argv[0] || "status";
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
    return 0;
  }

  if (command === "next") {
    const next = [...queue.tasks]
      .filter((task) => task.status === "queued")
      .sort((a, b) => a.priority - b.priority)[0];
    if (!next) {
      console.log("No queued content tasks.");
      return 2;
    }
    console.log(JSON.stringify(next, null, 2));
    return 0;
  }

  if (["validate", "validate-sources", "verify-rendered"].includes(command)) {
    const slug = argv[1];
    if (!slug) throw new Error(`Usage: ${command} <slug>`);
    const match = loaded.find(({ article }) => article.slug === slug);
    if (!match) throw new Error(`Article not found: ${slug}`);
    const result = validateArticle(match.article, articles);
    printResult(result);
    if (!result.passed) return 1;

    if (command === "validate-sources") {
      const sourceResults = await validateSources(match.article);
      sourceResults.forEach(printSourceResult);
      return sourceResults.every((source) => source.passed) ? 0 : 1;
    }

    if (command === "verify-rendered") {
      const rendered = verifyRenderedArticle(match.article, argv[2]);
      console.log(`${rendered.passed ? "PASS" : "FAIL"} rendered SEO: ${rendered.file || "not found"}`);
      for (const error of rendered.errors) console.log(`  ERROR: ${error}`);
      return rendered.passed ? 0 : 1;
    }

    return 0;
  }

  if (command === "validate-all") {
    let failed = false;
    for (const { article } of loaded) {
      const result = validateArticle(article, articles);
      printResult(result);
      if (!result.passed) failed = true;
    }
    return failed ? 1 : 0;
  }

  throw new Error(`Unknown command: ${command}`);
}

const isDirectRun = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (isDirectRun) {
  const exitCode = await main();
  if (exitCode) process.exit(exitCode);
}
