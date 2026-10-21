# SignalScout

Finds B2B startups that need GTM-ops help now, from public hiring, funding and tech signals, and
says why for every account. Built as the prospecting engine of a RevOps consultancy: Tier-A
accounts go to a Clay table for people and emails, and into HubSpot through
[PipelineOS](https://github.com/SAARTH4555/pipelineos).

## Why it matters

A consultancy that sets up GTM systems sells best at one moment: when a startup is about to build
that function. That moment is public. The startup posts its first RevOps or Salesforce-admin role,
it has usually just raised, and its job posts name the CRM it runs. Most prospecting tools charge
for this data; SignalScout reads it from free, public sources, scores it with rules a RevOps lead
can read, and spends paid enrichment credits only on accounts worth a call.

## What it does

| Signal | Source | Read as |
|---|---|---|
| Open GTM-ops role (RevOps, Sales/Marketing/CS Ops, GTM engineer, CRM admin, sales leader) | Public job boards: Ashby, Greenhouse, Lever | Building the function now. The strongest signal: Tier A requires one. |
| Recent raise | SEC Form D filings (EDGAR) | New targets, more reps, pressure on the CRM. |
| CRM in use | Job descriptions first, website scripts second | Which experts to send; a possible migration. |

Each account gets a 0-100 score (fit + intent, with older signals worth less), a tier and the
reasons, and lands in `accounts.csv`, a Clay import (`tier_a.csv`) and PipelineOS's load format.

## Architecture

```
 seeds/ (YC directory, seed CSV) --> accounts.py (one account per domain)
                                          |
             +----------------------------+------------------------------+
             v                            v                              v
 jobs/ (find board, read jobs)    funding.py (Form D)            crm.py (site scan + GTM container)
             |  roles.py (GTM-ops roles, tools named in posts)          |
             +----------------------------+------------------------------+
                                          v
                score.py (fit + intent, decay, tiers, reasons; config/scoring.yaml)
                                          v
               export.py: accounts.csv | tier_a.csv -> Clay | pipelineos/ -> HubSpot
 every request: fetch/ (per-host pacing, disk cache, robots.txt, SEC identity) or a recording
```

Design decisions and their reasons are in [`docs/methodology.md`](docs/methodology.md); what
SignalScout does and does not collect is in [`docs/ethics.md`](docs/ethics.md).

## Quickstart

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
uv run signalscout run --offline         # recorded demo world, no network
uv run signalscout clay-spec             # validate the Clay table spec, print its budget
```

A live run needs a contact email for SEC's fair-access policy:

```bash
SIGNALSCOUT_CONTACT_EMAIL=you@example.com uv run signalscout run --limit 20
```

Then build the Clay tables from [`docs/clay-table.md`](docs/clay-table.md), and load Tier A into
HubSpot with PipelineOS: `pipelineos load data/out/pipelineos --spec portal/gtm-consultancy.yaml`.
The full live procedure is [`docs/runbook.md`](docs/runbook.md).

## Demo

`signalscout run --offline`:

```
YC directory: 3 of 10 companies kept
  [1/3] harborview.example           Tier B  score  51
  [2/3] ledgerline.example           Tier A  score  79
  [3/3] orbitstack.example           Tier B  score  47

Tier A 1, Tier B 2, Tier C 0
  wrote data/out/accounts.csv (3 rows)
  wrote data/out/tier_a.csv (1 rows)
  wrote data/out/pipelineos/companies.csv (1 rows)
  wrote data/out/pipelineos/contacts.csv (0 rows)

Ledgerline (ledgerline.example): Tier A, 79
  - 120 people, inside the 50-500 band
  - Runs Salesforce (high confidence: 2 job postings name Salesforce)
  - Hiring: Revenue Operations Manager (Revenue Operations, posted 13 days ago)
  - Raised $30.5M 62 days ago (SEC Form D; stage Series A/B (guess))
  - Hiring for GTM ops right after a raise
```

Read that as: the two Tier-B companies are hiring too, but their openings are older and neither
raised in the last year, so they stay below Tier A. Every company here is fictional, on the
reserved `.example` domain, so none of it can be mistaken for a real business.

## Results

Every number here comes from `results/*.json` or the committed Clay spec, written by the commands
in [`scripts/reproduce.sh`](scripts/reproduce.sh). CI fails if this section and those files
disagree.

<!-- RESULTS:START -->

### Live run

Real public data from the sources listed. Account-level counts only; the account list itself is not committed.

| | |
|---|---|
| Accounts looked at | 170 (as of 2026-10-21) |
| Sources used | job boards, websites (off: SEC Form D) |
| Tiers | A 6, B 21, C 143 |
| Job board found | 110 of 170 (ashby 78, greenhouse 22, lever 10; via careers_page 67, guess 43) |
| Open jobs read | 2,306 |
| With a GTM-ops opening | 29 (crm_admin 2, gtm_engineer 8, marketing_ops 2, revops 8, sales_leader 10, sales_ops 8) |
| With a raise in the last year | not checked (SEC lookups off for this run) |
| CRM identified | 108 (high 73, low 1, medium 34 confidence) |
| Accounts with a failed source | 0 |
| Requests | 1,170 (1,150 served from the cache of earlier runs, 20 blocked by robots.txt, 1 failed) |

Hand check of real job titles from this run, labelled by Claude, which also wrote the rules, so not blind: 29 of 30 titles the classifier accepted are GTM-ops roles (precision 97%), and 1 of 30 near-miss titles it rejected (containing sales, revenue, ops, CRM, marketing...) turned out to be GTM-ops roles. Details and borderline calls: [`docs/methodology.md`](docs/methodology.md).

### Offline demo world

`signalscout run --offline`: recorded synthetic responses for three fictional companies, built so every signal path runs. It shows the pipeline works end to end, not how common each signal is.

| | |
|---|---|
| Accounts looked at | 3 (as of 2026-10-15) |
| Sources used | job boards, SEC Form D, websites |
| Tiers | A 1, B 2, C 0 |
| Job board found | 3 of 3 (ashby 1, greenhouse 1, lever 1; via careers_page 1, guess 2) |
| Open jobs read | 5 |
| With a GTM-ops opening | 3 (crm_admin 1, gtm_engineer 1, revops 1) |
| With a raise in the last year | 1 |
| CRM identified | 3 (high 3 confidence) |
| Accounts with a failed source | 0 |
| Requests | 25 (0 served from the cache of earlier runs, 0 blocked by robots.txt, 0 failed) |

### GTM-ops title classifier

Hand-labelled titles. The dev set was used to tune the rules; the holdout was written after tuning and never used to change a rule. Both were written by the rule author, so the holdout is not blind: read these as a floor check, and the live run's hand check (once run) as the real number.

| Set | Precision | Recall | Role kind | Seniority |
|---|---|---|---|---|
| dev (47 titles) | 100% | 100% | 100% | 100% |
| holdout (40 titles) | 100% | 100% | 100% | 100% |

### Clay credit budget

Worst case from [`clay/table_spec.yaml`](clay/table_spec.yaml) on Clay Free (100 credits, 500 actions, 200 rows a month): every email provider tried, none found.

| Per Tier-A account | Per month on this plan |
|---|---|
| 17 credits, 12 actions | 5 accounts, 10 people |

<!-- RESULTS:END -->

## What is real and what is not

- **Free sources only.** No paid data API is called. Clay, where people are found, is used on its
  free plan, and only for Tier A.
- **No people in the repo.** SignalScout works at account level; names and emails live in Clay
  and HubSpot only. Tests use synthetic companies.
- **Signals are evidence, not proof.** A Form D round letter is a guess from the amount; a
  website script is a CRM guess with a confidence level; job-title rules were tested on sets the
  rule author wrote.
- **The job-board APIs are public, but none grants explicit permission for prospecting use.**
  SignalScout reads them politely; see [`docs/ethics.md`](docs/ethics.md).

## Testing

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy                                  # strict, src + tests + scripts
uv run signalscout clay-spec --check
uv run python scripts/render_readme.py --check
uv run pytest --cov                          # fails under 85% branch coverage
uv run signalscout run --offline --out /tmp/out
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the same gates in three jobs
(quality, test, build). It needs no secrets and never touches the network.

## Layout

```
config/scoring.yaml   fit and intent rules, tiers
clay/table_spec.yaml  the Clay tables, validated and budgeted
src/signalscout/
  fetch/              polite cached fetcher, recorded fake
  seeds/              YC directory and seed CSV
  jobs/               Ashby / Greenhouse / Lever boards, board discovery
  roles.py            GTM-ops title classifier, tools named in job posts
  funding.py          SEC Form D
  crm.py              website scripts and Tag Manager container
  score.py            scoring and tiers
  pipeline.py         one run, with counts of everything
  export.py           accounts.csv, tier_a.csv, PipelineOS files
evals/                hand-labelled job titles (dev + holdout)
examples/offline/     recorded demo world
docs/                 methodology, ethics, runbook, generated Clay build guide
results/              committed outputs behind every README number
```

## What I would build next

- **Alerts, not lists.** Re-run daily from the cache and post a Slack message when a known account
  opens a GTM-ops role.
- **Closed loop.** Join HubSpot deal outcomes back to the signals that sourced them, and tune the
  scoring weights on win rate.
- **More boards.** Workable and Recruitee, once a reliable "no board" answer is confirmed for each.
- **Champion moves.** A known buyer changing company is a strong signal; it needs a people source,
  so it would live in Clay, not here.
