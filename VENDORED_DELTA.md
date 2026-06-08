# Vendored Delta scraper (for delta-browser-scrape)

`scrapers/`, `config/`, `db/`, `pipeline/` here are **copied verbatim** from
**points-pilot-scrapers @ browser-scraper-base** so this repo can run the nodriver Delta
browser scrape self-contained (GH Actions Azure IP clears Akamai where Fly's IP gets 444),
without a cross-repo checkout / PAT.

Files: `scrapers/{base,browser,delta}.py`, `config/settings.py`, `db/{connection,queries,schema}.py`,
`pipeline/normalizer.py`. Entry point: `delta_browser_scrape.py`.

**Canonical copy is the scraper repo — fix there first, then re-copy here.** Editing these
copies without propagating upstream is the footgun.
