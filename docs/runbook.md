# Runbook: a live run

## 1. Configure

```bash
cp .env.example .env
# SIGNALSCOUT_CONTACT_EMAIL=you@yourdomain.com   (required by SEC's fair-access policy)
```

## 2. Run

Start small, check the output, then widen:

```bash
uv run signalscout run --limit 20 --report results/live.json
uv run signalscout run --report results/live.json            # every YC seed in the band
uv run signalscout run --seed-csv my_accounts.csv --no-yc   # your own list only
```

A full run over a few hundred companies takes tens of minutes, because every host is paced. A
re-run reads from `.cache/http` and takes seconds. Outputs land in `data/out/` (ignored by git).

## 3. Check the title classifier on real titles

```bash
uv run python scripts/title_review.py sample      # -> data/out/title_review.csv, from the cache
# label the is_gtm_ops column yes / no by hand
uv run python scripts/title_review.py score --labelled-by "<who labelled it>"
```

The sample is up to 30 titles the classifier accepted, and 30 "near misses" it rejected that
contain words like sales, revenue, ops, CRM or marketing. The score goes to
`results/live_review.json` and into the README.

## 4. Build the Clay tables

Follow [`clay-table.md`](clay-table.md): import `data/out/tier_a.csv` into the Accounts table,
then add the People table. Screenshot both into `docs/img/`.

## 5. Load Tier A into HubSpot

With PipelineOS, against a HubSpot test portal configured from its consultancy spec:

```bash
pipelineos apply --spec portal/gtm-consultancy.yaml --yes
pipelineos load ../signalscout/data/out/pipelineos --spec portal/gtm-consultancy.yaml --yes
```

## 6. Publish the numbers

```bash
uv run python scripts/render_readme.py
```

Commit `results/live.json` (and `results/live_review.json`), never `data/`.
