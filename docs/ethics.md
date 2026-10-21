# Data and ethics

SignalScout works at account level, from public sources, and is polite to every one of them.

## What it reads

| Source | What | Why it is fair to read |
|---|---|---|
| YC directory (yc-oss mirror) | Company name, website, size, location, industry | A public directory. The mirror declares no license, so it is treated as one seed, credited, not redistributed. |
| Ashby, Greenhouse, Lever job-board APIs | Open job postings | Documented public endpoints, built for companies' own careers pages. None grants explicit permission for prospecting use; SignalScout reads them as a person browsing would, slowly. |
| SEC EDGAR | Form D filings | Public filings, read under SEC's fair-access policy. |
| Company websites | Homepage, `/careers`, `/jobs`, `/demo`, `/contact`, a Tag Manager container | Public pages; robots.txt is honoured before any page is fetched. |

## How it reads

- At most one request per second to each job board and website, five per second to SEC (half its
  published limit).
- A User-Agent that names the tool and, for SEC, a contact email; SEC lookups refuse to run
  without one.
- An on-disk cache with conditional requests, so a re-run does not fetch unchanged pages again.
- No logins, no bypassing of robots.txt, no headless browser.

## What it never stores

- **No people.** The repo, its fixtures and its outputs hold companies only. Finding people is
  done in Clay, and their data stays in Clay and HubSpot.
- **No live account lists in git.** A live run's accounts stay in `data/` (ignored); only
  account-level counts are committed.

## Contacting anyone found this way

- **CAN-SPAM (US):** a truthful subject, the sender's postal address and a working unsubscribe
  in every commercial email; opt-outs honoured within 10 business days.
- **GDPR (EU contacts):** B2B outreach usually relies on legitimate interest, which needs a
  written assessment and an easy objection route.
- **No message without a reason.** The Clay opening line must cite a real signal from the
  account's reasons, or it is left empty and the contact is not sent anything.
