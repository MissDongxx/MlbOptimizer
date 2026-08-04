# Reusable Content Production Workflow

This directory is the portable layer of the content system. Copy it to another
website and replace `site.config.json` plus `tasks.json`; keep the workflow and
quality gates unchanged unless the site's risk level requires stricter rules.

## State model

`queued → researching → drafted → approved`

`blocked` is used when authoritative evidence, product context, or a human
decision is missing.

Automated jobs may approve and publish exactly one article per run only after
all quality gates pass. The automated reviewer name must be
`DiamScore Automated Quality Gate`.

## Per-run contract

1. Import or update `tasks.json` from the supplied keyword table. For strategy
   exports with a `Page` column, create one task per Page: choose the highest-
   volume keyword as primary, keep the next 3-5 as supporting keywords, and
   turn seed keywords into required angles. Preserve one search intent per task.
   Apply the site's allowed-topic and blocked-term filters before adding tasks.
2. Run `npm run content:next` and select only the returned task.
3. Compare the task with existing primary keywords, titles, headings, and search
   intents. Record the distinct reader question in `contentDifferentiation`.
4. Create a short task card with `contentFormat`, `formatReason`, `funnelStage`,
   `conversionGoal`, `requiredModules`, `visualRequirement`, and
   `variantDimensions`, then build a format-specific intent-first outline.
5. Research the topic from the source policy in `site.config.json`. Build a claim
   ledger for numeric, time-sensitive, product, policy, and other checkable facts.
6. Create one text-only article JSON from `article.example.json`; strict articles
   must also declare `uniqueValue` and the selected format metadata. Do not create,
   search for, download, or modify article images.
7. Route format by intent: informational queries use `deep_explanation`, procedural
   queries use `how_to`, explicit comparisons use `comparison`, commercial selection
   uses `structured_recommendation`, reviews require first-hand evidence, and
   tools/templates use `tool_landing_page`. Format-specific proof is conditional:
   how-to pages need prerequisites, ordered steps, expected outcomes, and
   troubleshooting; comparison pages need consistent criteria and a fit verdict;
   tool/template pages need use cases, examples, and distinct variant dimensions.
8. Put the primary keyword naturally in the title, opening 100 words, at least
   one section heading, and the conclusion. Cover 3-5 supporting keywords without
   stuffing. Include a limitations section, original example, relevant FAQ,
   internal links, CTA, and an explicit conclusion or next-steps section.
9. Map each section and each verified claim to real source IDs. Add access dates.
10. Run the intent, depth, format-fit, fact-check, and post-edit humanization audit; record the
   result in `editorialAudit`, then recheck facts, links, keywords, and metadata.
11. Run `npm run content:validate -- <slug>` while the article is in draft/review.
12. Run `npm run content:validate:sources -- <slug>` to verify that every cited
    URL is reachable. Fix, replace, soften, or remove unsupported claims.
13. If validation passes, set the article and task to `approved`, use the
   configured automated reviewer, and set publication/update dates.
14. If evidence is insufficient, mark the task `blocked` and record the reason.
15. Re-run article, source, and all-content validation after approval. Never
    publish or weaken a failed gate.
16. Run frontend typecheck and production build, then run
    `npm run content:verify-rendered -- <slug>` against the static output.
17. Commit only the task list and generated article, then push `dev`.

Articles without `seoAuditVersion: 2` remain legacy-compatible. New articles
must use version 2 and pass keyword placement, supporting keyword, conclusion,
format-fit, unique-value, claim-ledger, differentiation, and editorial-audit checks.

Community observations such as declining “best listicles,” fixed word counts, or
universal conversion rankings are hypotheses for SERP and analytics testing, not
hard Google requirements.

## Publication mode

Manual browser approval is temporarily disabled. Publishing uses the existing
static deployment workflow: a validated approved article is committed to `dev`,
which triggers the normal production build and deployment. If the repository is
already dirty before the run, stop without committing or pushing.
