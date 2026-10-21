# Methodology

How SignalScout decides which accounts to show, and the reasons behind each choice.

## Who it looks for

US B2B tech startups, Series A to C, 50 to 500 people: big enough to have a sales team and a CRM
that hurts, small enough that nobody owns GTM systems full time yet. The band lives in
`config/scoring.yaml` (fit) and in the YC seed filter (`--min-team`, `--max-team`).

## Seeds

The YC company directory, via the public yc-oss mirror, filtered to active, US, B2B companies in
the size band; plus any `name,domain` CSV. Seeds decide what gets looked at, never the score: a
company that fails a fit rule still appears, with the reason it scored low. Limits: the YC filter
keeps a few hundred companies at most, and YC team sizes are self-reported.

Every account is keyed by its registrable domain (`acme.io`), the same `company_key` PipelineOS
upserts companies on. The domain code is copied from PipelineOS and pinned to the same test cases.

## Signal 1: open GTM-ops roles

- **Finding the board.** No vendor offers company-to-board lookup. The company's own `/careers`
  or `/jobs` page is read first; a link or embed there is proof. Otherwise up to 3 slug guesses
  are tried on each vendor. A guessed board is accepted only if Greenhouse names the company or,
  for Ashby and Lever, a job description mentions it. URLs are never used to verify, because a
  posting URL always contains the guessed slug.
- **Reading roles.** Titles are matched on explicit phrases (`roles.py`), never on "ops" alone,
  so DevOps, SecOps, People Ops and revenue accounting are excluded. A sales-leader posting
  counts as a weaker signal: a new revenue leader usually rebuilds the GTM stack.
- **Dates.** Ashby's `publishedAt` resets when a job is republished, Greenhouse's
  `first_published` is the first date, Lever's `createdAt` is creation time. Each job keeps which
  field its date came from.
- **Left out.** SmartRecruiters answers 200 with zero jobs for any slug, so "no board" and "not
  hiring" cannot be told apart.

## Signal 2: a recent raise

EDGAR full-text search for Form D (and D/A) filings by company name over 18 months, legal forms
stripped first, then the newest filing's raw XML. The issuer must match the company's name after
normalisation; two different matching issuers is no answer, not a guess. Pooled funds and
fund-like names are dropped. Form D gives amount sold and date of first sale, not the round
letter, so the stage is a labelled guess from the amount.

## Signal 3: the CRM

Job descriptions that name Salesforce or HubSpot give the CRM with high confidence. Otherwise the
homepage and `/demo` or `/contact` are scanned with about 20 regex signatures, plus the Google Tag
Manager container when one is referenced, since tags it injects are invisible in plain HTML. A
marketing script is not the CRM: HubSpot or Pardot scripts give a medium-confidence guess,
Marketo alone a low one.

## Scoring

`config/scoring.yaml`, validated before use:

- **Fit, up to 30:** inside the size band 15 (unknown size 5), US 5, B2B 5, CRM known 5.
- **Intent:** the strongest open role (RevOps or GTM engineer 30, CRM admin or Sales Ops 25,
  sales leader 20, Marketing Ops 15, CS Ops 10), halved every 45 days since posting; +5 when the
  role leads the function; +10 for two or more GTM-ops roles; a raise within a year up to 20,
  halved every 120 days; +10 when a GTM-ops opening follows a raise.
- **Tiers:** A at 60, B at 35. Tier A needs an open GTM-ops role. Outside the size band caps at C.

Every point adds a sentence to the account's reasons; the score never appears without them.

## Failure handling

Each account is collected independently. A broken careers page, an SEC error or an unreachable
site costs that account that signal; the failure is recorded on the account and counted in the
run report, and the run continues.
