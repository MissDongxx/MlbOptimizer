import assert from "node:assert/strict";
import test from "node:test";

import { validateArticle } from "./content-pipeline.mjs";

function makeArticle() {
  const filler = Array.from(
    { length: 210 },
    () => "Readers compare evidence, context, assumptions, and practical steps before applying the recommendation.",
  ).join(" ");

  return {
    schemaVersion: 1,
    seoAuditVersion: 2,
    status: "review",
    slug: "example-seo-workflow",
    category: "content-strategy",
    primaryKeyword: "example seo workflow",
    supportingKeywords: ["search intent", "source verification", "content audit"],
    intent: "informational",
    contentDifferentiation:
      "This page focuses on a repeatable publishing workflow rather than a general introduction to search optimization.",
    title: "Example SEO Workflow: A Practical Publishing Guide",
    description:
      "Use an evidence-led SEO workflow to align search intent, source verification, content auditing, and publication checks in one repeatable process.",
    excerpt:
      "This example SEO workflow connects search intent, source verification, and a content audit before publication.",
    author: "Editorial Team",
    reviewer: "Pending editorial review",
    publishedAt: null,
    updatedAt: "2026-08-04",
    keyTakeaways: [
      "Begin with one reader question.",
      "Map checkable claims to sources.",
      "Recheck changed passages before publication.",
    ],
    sections: [
      {
        heading: "Example SEO workflow from intent to evidence",
        paragraphs: [`Start with the reader's search intent and define a practical outcome. ${filler}`],
        sourceIds: ["source-1"],
      },
      {
        heading: "Run source verification",
        paragraphs: ["Use source verification for objective and time-sensitive claims."],
        sourceIds: ["source-1"],
      },
      {
        heading: "Limitations and content audit",
        paragraphs: [
          "A content audit still needs editorial judgment about depth, clarity, and uncertainty. Predictions are estimates, not guaranteed outcomes. Readers should verify late lineup, injury, weather, and contest-rule changes.",
        ],
        sourceIds: ["source-2"],
      },
      {
        heading: "Conclusion and next steps",
        paragraphs: ["Apply the example SEO workflow, document the result, and recheck every changed element."],
        sourceIds: ["source-1", "source-2"],
      },
    ],
    faq: [
      { question: "What starts the workflow?", answer: "A single primary keyword and search intent." },
      { question: "Why verify sources?", answer: "Verification reduces unsupported or outdated claims." },
      { question: "When is the audit complete?", answer: "After changed facts and SEO elements are rechecked." },
    ],
    claimLedger: [
      {
        claim: "The workflow maps objective claims to sources.",
        type: "factual",
        action: "verified",
        sourceIds: ["source-1"],
        checkedAt: "2026-08-04",
      },
    ],
    editorialAudit: {
      searchIntent: "pass",
      contentDepth: "pass",
      factCheck: "pass",
      humanization: "pass",
      auditedAt: "2026-08-04",
      notes: "Intent, evidence, depth, natural language, links, and metadata were reviewed after the final edit.",
    },
    sources: [
      {
        id: "source-1",
        title: "Primary source",
        publisher: "DiamScore",
        url: "https://diamscore.com/",
        accessedAt: "2026-08-04",
        type: "primary",
      },
      {
        id: "source-2",
        title: "Secondary source",
        publisher: "FanGraphs",
        url: "https://fangraphs.com/",
        accessedAt: "2026-08-04",
        type: "secondary",
      },
    ],
    internalLinks: [
      { label: "Main product", href: "/" },
      { label: "Related guide", href: "/blog/related-guide" },
    ],
    cta: { label: "Open the product", href: "/" },
  };
}

test("strict version 2 article passes all deterministic gates", () => {
  const article = makeArticle();
  const result = validateArticle(article, [article]);
  assert.equal(result.passed, true, result.errors.join("\n"));
});

test("approved primary keyword variants satisfy placement checks", () => {
  const article = makeArticle();
  article.primaryKeywordVariants = ["practical seo workflow"];
  article.title = "Practical SEO Workflow: Evidence Before Publishing";
  article.excerpt = "A practical SEO workflow connects search intent, source verification, and a content audit before publication.";
  article.sections[0].heading = "Practical SEO workflow from intent to evidence";
  article.sections.at(-1).paragraphs = [
    "Apply the practical SEO workflow, document the result, and recheck every changed element.",
  ];
  const result = validateArticle(article, [article]);
  assert.equal(result.passed, true, result.errors.join("\n"));
});

test("strict article requires the primary keyword in the opening window", () => {
  const article = makeArticle();
  article.excerpt = "A focused publishing process connects readers, evidence, and editorial review.";
  article.keyTakeaways = ["Define the audience.", "Check the evidence.", "Review the result."];
  article.sections[0].paragraphs = [Array.from({ length: 120 }, () => "Useful context supports the reader.").join(" ")];
  const result = validateArticle(article, [article]);
  assert(result.errors.some((error) => error.includes("opening 100 words")));
});

test("blocked topics are hard failures", () => {
  const article = makeArticle();
  article.sections[1].paragraphs.push("This unrelated section discusses NBA content.");
  const result = validateArticle(article, [article]);
  assert(result.errors.some((error) => error.includes("blocked-topic match: NBA")));
});

test("numeric claims must be represented in the claim ledger", () => {
  const article = makeArticle();
  article.sections[1].paragraphs.push("The process increased the result by 42 percent.");
  const result = validateArticle(article, [article]);
  assert(result.errors.some((error) => error.includes("numeric claim 42")));
});
