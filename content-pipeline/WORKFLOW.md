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
4. Create a short task card, then an intent-first outline before drafting.
5. Research the topic from the source policy in `site.config.json`. Build a claim
   ledger for numeric, time-sensitive, product, policy, and other checkable facts.
6. Create one text-only article JSON from `article.example.json`; do not create,
   search for, download, or modify article images.
7. Put the primary keyword naturally in the title, opening 100 words, at least
   one section heading, and the conclusion. Cover 3-5 supporting keywords without
   stuffing. Include a limitations section, original example, FAQ, internal links,
   CTA, and an explicit conclusion or next-steps section.
8. Map each section and each verified claim to real source IDs. Add access dates.
9. Run the intent, depth, fact-check, and post-edit humanization audit; record the
   result in `editorialAudit`, then recheck facts, links, keywords, and metadata.
10. Run `npm run content:validate -- <slug>` while the article is in draft/review.
11. Run `npm run content:validate:sources -- <slug>` to verify that every cited
    URL is reachable. Fix, replace, soften, or remove unsupported claims.
12. If validation passes, set the article and task to `approved`, use the
   configured automated reviewer, and set publication/update dates.
13. If evidence is insufficient, mark the task `blocked` and record the reason.
14. Re-run article, source, and all-content validation after approval. Never
    publish or weaken a failed gate.
15. Run frontend typecheck and production build, then run
    `npm run content:verify-rendered -- <slug>` against the static output.
16. Commit only the task list and generated article, then push `dev`.

Articles without `seoAuditVersion: 2` remain legacy-compatible. New articles
must use version 2 and pass keyword placement, supporting keyword, conclusion,
claim-ledger, differentiation, and editorial-audit checks.

## Publication mode

Manual browser approval is temporarily disabled. Publishing uses the existing
static deployment workflow: a validated approved article is committed to `dev`,
which triggers the normal production build and deployment. If the repository is
already dirty before the run, stop without committing or pushing.
