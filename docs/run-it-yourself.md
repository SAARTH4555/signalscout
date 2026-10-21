# Run it yourself

About 40 minutes, start to finish. At the end you have a real list of startups hiring for GTM
operations right now, a Clay table built from it in your own Clay account, and (optionally) the
same accounts in your HubSpot portal.

You need a Mac, Linux or Windows (with WSL) terminal. Nothing is paid: Clay's free plan is
enough.

## 1. Install and try the demo (5 minutes)

```bash
# 1. Install uv, the Python tool the project uses (it installs Python 3.12 for you)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Get the code
git clone https://github.com/SAARTH4555/signalscout.git
cd signalscout
uv sync --group dev

# 3. The recorded demo: three made-up companies, no internet needed
uv run signalscout run --offline
```

It should end with `Tier A 1, Tier B 2, Tier C 0` and five reasons for the Tier-A company.

## 2. A live run on real companies (10-25 minutes)

```bash
uv run signalscout run --no-funding --limit 20      # 20 companies, about 2 minutes
uv run signalscout run --no-funding                 # all ~170, about 20 minutes
```

It reads the YC company directory, the companies' public job boards and websites, slowly and
politely. Each line shows a company, its tier and its score. The results land in `data/out/`:

| File | What it is |
|---|---|
| `accounts.csv` | Every company, with its signals and the reasons for its score |
| `tier_a.csv` | The Tier-A accounts, ready to import into Clay |
| `pipelineos/companies.csv` | The same accounts in PipelineOS's format, for HubSpot |

**Funding (optional).** To add the "raised recently" signal from SEC filings, SEC asks every
tool to identify itself, so set an email first:
`SIGNALSCOUT_CONTACT_EMAIL=you@yourdomain.com uv run signalscout run`. A re-run is fast: pages
already fetched come from a local cache.

## 3. Build the Clay tables (15 minutes)

1. Create a free account at [clay.com](https://www.clay.com/).
2. Print the build guide with the credit budget: `uv run signalscout clay-spec` (or open
   [`clay-table.md`](clay-table.md)).
3. Follow its section 1: create a table called **SignalScout Accounts** and import
   `data/out/tier_a.csv`. Each column in the file becomes a column in Clay.
4. Add the **`gtm_research`** column: an "Enrich with Claygent" column with the prompt from the
   guide, set to run only when `tier` is `A`.
5. Follow section 2: create **SignalScout People** with "Find people" on the Accounts table,
   matching on `domain`, at most 2 per company, with the job titles listed. Then add the work
   email waterfall (pick any three email providers Clay offers), the validation step, and the
   `opening_line` AI column with its prompt.

On the free plan's 100 credits, budget for about 5 Tier-A accounts a month in the worst case.
Clay's share menu can create a link to the table to show someone.

## 4. Into HubSpot (optional, 5 minutes)

With [PipelineOS](https://github.com/SAARTH4555/pipelineos) set up on your HubSpot test portal
(its `docs/run-it-yourself.md`), point it at the consultancy setup and load the Tier-A accounts:

```bash
cd ../pipelineos
uv run pipelineos apply --spec portal/gtm-consultancy.yaml --yes
uv run pipelineos load ../signalscout/data/out/pipelineos --spec portal/gtm-consultancy.yaml --yes
```

Each company in HubSpot then shows its tier, score, the open role, its CRM and the reasons.

## Good to know

- The repo never stores people. Names and emails exist only in your Clay and HubSpot.
- Before emailing anyone you find this way, read [`ethics.md`](ethics.md): every email needs a
  reason from the account's signals, an unsubscribe link and a postal address.
