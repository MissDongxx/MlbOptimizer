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

1. Run `npm run content:next` and select only the returned task.
2. Verify the task does not overlap an existing primary keyword or search intent.
3. Research the topic from the source policy in `site.config.json`.
4. Create one article JSON from `article.example.json`.
5. Map each section to real source IDs.
6. Run `npm run content:validate -- <slug>`.
7. If validation passes, set the article and task to `approved`, use the
   configured automated reviewer, and set publication/update dates.
8. If evidence is insufficient, mark the task `blocked` and record the reason.
9. Re-run validation after approval. Never publish or weaken a failed gate.
10. Run frontend typecheck and production build.
11. Commit only the task list and generated article, then push `dev`.

## Publication mode

Manual browser approval is temporarily disabled. Publishing uses the existing
static deployment workflow: a validated approved article is committed to `dev`,
which triggers the normal production build and deployment. If the repository is
already dirty before the run, stop without committing or pushing.
