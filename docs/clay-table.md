# Building the SignalScout tables in Clay

Generated from `clay/table_spec.yaml` by `signalscout clay-spec`. Do not edit by hand.

Plan: **Clay Free**: 100 data credits and 500 actions a month, 200 rows per table. Credit costs are worst-case estimates (Clay publishes no per-provider prices).

| Budget | Worst case |
|---|---|
| Credits per Tier-A account | 17 |
| Actions per Tier-A account | 12 |
| Tier-A accounts per month on this plan | 5 |
| People reached per month | 10 |

## 1. SignalScout Accounts

One row per Tier-A account from SignalScout, with the signals already filled in.

Create a table and import `data/out/tier_a.csv` (one row per account).

| Column | Kind | Run only if | Worst-case credits |
|---|---|---|---|
| `company_name` | imported | always | 0 |
| `domain` | imported | always | 0 |
| `tier` | imported | always | 0 |
| `score` | imported | always | 0 |
| `why_now` | imported | always | 0 |
| `best_role` | imported | always | 0 |
| `best_role_url` | imported | always | 0 |
| `crm` | imported | always | 0 |
| `funding_amount` | imported | always | 0 |
| `funding_date` | imported | always | 0 |
| `team_size` | imported | always | 0 |
| `gtm_research` | claygent | tier = A | 0 |

**`gtm_research` prompt**

> Read the job posting at {{best_role_url}} and the company site {{domain}}. In at most three bullet points, say what GTM-ops problem this hire is meant to fix (for example: no single source of truth for pipeline, a CRM migration, lead routing, reporting for a board). Quote the posting where you can. If the posting is gone, say so and stop.

Output fields: `problems` (list of strings), `quote` (string), `posting_live` (boolean)

## 2. SignalScout People

The 1-2 people at each account who would hire a RevOps consultancy.

Create a table from **Find people** on `SignalScout Accounts`, matching on `domain`, at most 2 per company, titles:

- Head of Revenue Operations
- VP Revenue Operations
- Director of Revenue Operations
- Chief Revenue Officer
- VP Sales
- Head of Sales
- Chief Operating Officer

| Column | Kind | Run only if | Worst-case credits |
|---|---|---|---|
| `full_name` | provided | always | 0 |
| `title` | provided | always | 0 |
| `linkedin_url` | provided | always | 0 |
| `company_domain` | provided | always | 0 |
| `work_email` | waterfall | title is not empty | 7 |
| `email_valid` | enrichment | work_email is not empty | 1 |
| `opening_line` | ai | email_valid = true | 0 |

**`work_email` waterfall** (stop at first result): email provider 1 (2) -> email provider 2 (2) -> email provider 3 (3)

**`opening_line` prompt**

> Write one sentence, under 25 words, to {{full_name}} ({{title}}) that names one specific signal from: {{why_now}}. Use only facts in that text. No flattery, no questions. If the text has no concrete signal, return an empty string.

## Contact policy

- People data stays in Clay and HubSpot. It is never exported back into the SignalScout repo.
- Every opening line must cite a signal from why_now; empty means do not send.
- Sequences carry an unsubscribe link and a postal address (CAN-SPAM).
