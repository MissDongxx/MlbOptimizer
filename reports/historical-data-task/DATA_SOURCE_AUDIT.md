# Historical MLB DFS Data Source Audit

Audit date: 2026-07-29  
Selected platform/ruleset: DraftKings MLB Classic  
Required unit: one exact DraftKings DraftGroup/Game Set with its original pre-lock salary/position pool and independent postgame MLB statistics.

## Final decision

**FAIL: no qualifying public source was found for 30 historical DraftKings MLB Classic slates.**

The missing component is not MLB game statistics. Public MLB sources can support historical schedules, game IDs, game logs, box scores, and strictly prior-date projections. The missing component is a legally accessible, no-login, no-paywall archive that simultaneously proves all of the following for at least 30 historical dates:

1. the exact DraftKings DraftGroup or equivalent provider Game Set;
2. the complete original salary and position pool for that Game Set;
3. the games contained in that Game Set, including Main versus all-day distinctions;
4. historical pre-lock availability or publication semantics for the salary/Game Set artifact.

No source was accepted by inference. A daily salary table, a later file modification time, a current API response, or a contest-results page is not evidence that a historical field was available before lock for a particular DraftGroup.

## Candidate assessment

| Candidate | Date coverage | DK salary/position | Exact historical Game Set | Historical pre-lock semantics | Postgame stats | Access/licence | Stability | Decision |
|---|---|---:|---:|---:|---:|---|---|---|
| DraftKings official rules JSON and MLB Classic help | Current rules and policy | No historical pools | Defines rules, not archive | Not applicable | No | Public official page/API | Stable enough for versioned rules capture | **Use for scoring rules only** |
| DraftKings lobby/DraftGroup/draftables endpoints | Current/upcoming slates | Yes for a current DraftGroup | Yes while the DraftGroup is live | Capture time can prove future snapshots, not past snapshots | No | Publicly reachable, but unofficial documentation states the API is transient and not intended as a public contract | Volatile | **Reject for retrospective 30-slate build; suitable only for future forward capture** |
| DraftKings salary CSV export from contest draft page | Exact salary/position and Game Info | Yes | Yes when tied to the contest/DraftGroup | Export metadata or contemporaneous capture can prove pre-lock use | No | Requires account/contest workflow; user prohibited login/cookies/browser state | Platform-controlled | **Reject under current access constraints** |
| RotoGuru daily MLB DFS history | Broad historical calendar dates | Appears to include DK Classic salary/position and fantasy points | No verifiable DraftGroup/Main/all-day identity was found | No trustworthy pre-lock publication timestamp was found; server/file modification time is insufficient | May include DFS points | Public page, redistribution/licence semantics not verified; endpoint was also unstable during audit | Low | **Reject as `real`** |
| SportsDataIO MLB DFS feeds | Historical operator slates, games, players, salaries and timing | Yes | Yes, including operator slate/game IDs | Product documentation exposes operator publication/update semantics | Yes or calculable | Paid/commercial API | High | **Technically viable but disallowed because payment is required** |
| RotoGrinders/FantasyLabs ResultsDB/Contests Dashboard | Historical contest/results coverage including MLB | Contest/result-oriented | Some contest identity | No open, no-login raw historical salary/Game Set export with pre-lock timestamp was established | Yes/derived | Commercial/premium product; raw redistribution rights unclear | Medium | **Reject under current access constraints** |
| MLB Stats API / Baseball Savant / official-stat providers | Deep historical schedules and statistics | No platform salary/position | MLB games only, not DFS Game Sets | Game/stat timestamps can support cutoff and actuals | Yes | Public MLB endpoints or commercial official providers depending source | High for MLB facts | **Use for projections/actuals only; cannot close platform-data gap** |
| Public GitHub/Kaggle/scattered research repositories | Sporadic seasons/files | Some isolated CSVs | Usually absent | Usually absent; many files are transformed or lack original capture metadata | Sometimes | Licence varies; provenance usually incomplete | Low | **Reject for 30 qualified slates** |
| Generic DraftKings scraper services | Current production responses | Current salary and DraftGroup | Current only | Scrape time supports forward collection only | No | Often commercial; no historical archive guarantee | Medium | **Reject for retrospective task** |

## Risks explicitly checked

- **Projection backfill:** third-party historical `projection` fields were not accepted. The delivered builder computes a fixed rolling projection only from rows whose `game_date` is strictly earlier than the slate lock date.
- **File time confusion:** local mtime is not an accepted timestamp basis. Accepted bases are source payload time, HTTP Last-Modified when semantically valid, archive capture, platform export metadata, or repository commit evidence.
- **Main versus all-day:** calendar date alone is rejected. A real build requires a provider slate ID plus exact game IDs.
- **Doubleheaders/postponements/cancellations:** games are identified by MLB game IDs, not only teams/date. The Game Set must bind each player to a declared game. Operational handling still requires source-level final-state evidence.
- **Identity mapping:** platform ID is retained, MLBAM ID is mapped by normalized name plus team or an explicit override, and unmatched/ambiguous cases fail with a report. No silent drop is allowed.
- **Pitcher scoring:** innings are represented as outs recorded. DraftKings pitching bonuses are applied per game, with complete game, complete-game shutout, and no-hitter bonuses cumulative according to the captured rules version.
- **Historical rules:** the builder fixes a named DraftKings MLB Classic rules version. A production archive must capture/version the rule artifact by date if rule changes are discovered.
- **Redistribution:** raw artifacts are only bundle-eligible when redistribution rights are marked verified. Public-access-only or unknown-rights data may be locally referenced for an authorized run but must not be redistributed in the delivery ZIP.

## Source URLs reviewed

- DraftKings MLB Classic rules: `https://www.draftkings.com/help/rules/2`
- DraftKings rules JSON: `https://api.draftkings.com/rules-and-scoring/RulesAndScoring.json`
- Unofficial DraftKings API documentation: `https://github.com/SeanDrum/Draft-Kings-API-Documentation`
- DraftKings support, historical contest-results CSV workflow: `https://support.draftkings.com/dk/en-us/how-do-i-download-a-csv-to-see-gamecenter-standings-for-a-contest?id=kb_article_view&sysparm_article=KB0010448`
- SportsDataIO MLB workflow guide: `https://sportsdata.io/developers/workflow-guide/mlb`
- Baseball Savant CSV documentation: `https://baseballsavant.mlb.com/csv-docs`
- RotoGrinders/FantasyLabs Contests Dashboard: `https://rotogrinders.com/pages/fantasylabs-contests-dashboard-now-live-on-rotogrinders-3751657`

## What would change the decision

The task becomes executable without weakening any gate only when one of these evidence packages is legally available:

- 30 original DraftKings MLB Classic salary exports tied to exact DraftGroup/Game Set metadata, with contemporaneous capture/export evidence; or
- a licensed historical feed that supplies operator slate ID, game IDs, salaries, positions, and publication/update timestamps.

The delivered code is prepared to ingest such evidence, but the presence of code does not count as completion of the 30-slate requirement.
