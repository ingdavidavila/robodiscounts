# robodiscounts

Watches Best Buy (official API), Card Kingdom, TCGplayer and Amazon product pages and sends a WhatsApp message (Meta Cloud API) when an item hits your deal rules.

## Setup
```bash
pip install -r requirements.txt
playwright install chromium
cp config.example.yaml config.yaml   # add your products
cp .env.example .env                 # add Twilio credentials
```

### WhatsApp (Meta Cloud API)
1. At developers.facebook.com create an app (type *Business*) and add the **WhatsApp** product.
2. In **WhatsApp → API Setup** copy the **Phone number ID**; add your own phone as a recipient
   and verify it. The free test number works for this.
3. Token: the temporary token expires in 24h. For permanent use create a **System User** in
   Business Settings, give it the app, and generate a token with `whatsapp_business_messaging`.
4. Put `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_TO` in `.env`.
5. **Template (recommended):** Meta only allows free-text messages within 24h of the
   recipient messaging your number. For alerts any time, create a Utility template in
   WhatsApp Manager with this body, wait for approval, and set `WHATSAPP_TEMPLATE` to its name:
   `Deal alert: {{1}} is now {{2}} ({{3}}). {{4}}`
   Without a template, send any message to the business number first, then alerts work for 24h.

### Best Buy
Get a free key at https://developer.bestbuy.com and set `BESTBUY_API_KEY` (in `.env`, and as a repo secret
for GitHub Actions). Use any product URL containing the SKU, e.g. `.../6578291.p?skuId=6578291`.
This uses Best Buy's official API, so no browser is needed and it isn't blocked on GitHub runners.

### Card Kingdom
Paste any Card Kingdom item page URL (sealed product or a single). No key needed. It reads the first listed
price (near mint for singles). Card Kingdom has no strike-through list price in the parser, so use
`target_price` or `min_drop_percent` rather than `min_discount_percent`. Out-of-stock items have no
price and are logged as failures.

## Usage
```bash
python -m robodiscounts.cli test-message      # verify WhatsApp works
python -m robodiscounts.cli check --dry-run   # one pass, print alerts only
python -m robodiscounts.cli check             # one pass, send alerts (use with cron)
python -m robodiscounts.cli watch             # loop every check_interval_minutes
```

## Run hourly on GitHub Actions
`.github/workflows/check-discounts.yml` runs `check` every hour (and on demand via **Actions → Check discounts → Run workflow**).
In the repo go to **Settings → Secrets and variables → Actions** and add these secrets:
- `CONFIG_YAML`: the full contents of your `config.yaml` (keeps your watchlist out of the repo)
- `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TO`, `BESTBUY_API_KEY`, and optionally `WHATSAPP_TEMPLATE` / `WHATSAPP_STATUS_TEMPLATE`

If every item fails to load, the run fails (red) so you notice. When a page can't be parsed, the workflow uploads
its HTML and a screenshot as the `debug-pages` artifact on the run page (kept 3 days); locally, set
`ROBODISCOUNTS_DEBUG_DIR=debug` to get the same files.

Last-seen prices are kept between runs with the Actions cache, so you only get one alert per price.
Caveats: GitHub may pause scheduled workflows after 60 days without repo activity, runs can be delayed
by several minutes, and Amazon often blocks datacenter IPs like GitHub's runners (a self-hosted runner
or a small VPS with cron is more reliable).

## Run on a Raspberry Pi (recommended)
GitHub's hourly schedule is best effort and can run hours late. A Pi with cron checks on an exact schedule,
keeps price history on its own disk, and a home connection is less likely to be blocked by stores.

Needs: Raspberry Pi 3B+/4/5 (1 GB RAM or more) on **64-bit Raspberry Pi OS** (`uname -m` must print `aarch64`),
always on and online.
```bash
git clone --branch main https://github.com/ingdavidavila/robodiscounts.git
cd robodiscounts
./deploy/pi/setup.sh                 # one time: Python env, Chromium, config files
nano config.yaml                     # your products, URLs, MSRPs
nano .env                            # WhatsApp and Best Buy credentials
.venv/bin/python -m robodiscounts.cli test-message   # a WhatsApp message should arrive
./deploy/pi/run-check.sh             # one real check; read logs/check.log
./deploy/pi/cron.sh --every 20       # start the schedule (5, 10, 15, 20, 30 or 60 minutes)
```
- Logs: `tail -f logs/check.log` (rotated at ~2 MB). Stop the schedule with `./deploy/pi/cron.sh --remove`.
- Dashboard: rebuilt after every check at `site/index.html`. To view it from another device on your home network:
  `cd site && python3 -m http.server 8080`, then open `http://<pi-name>.local:8080`. Don't expose it to the internet.
- Update later with `./deploy/pi/update.sh`. Your `config.yaml`, `.env` and price history are left alone.
- **Turn off the GitHub schedule** once the Pi works (Actions → Check discounts → ⋯ → Disable workflow), otherwise
  both would send alerts, each with its own separate history.

## Dashboard
`python -m robodiscounts.cli dashboard` writes `site/index.html`: one row per product with status
(deal / failing / sold out / watching), current price, lowest price seen, target, a price-trend sparkline
and the last check time. It is a static file with no JavaScript, so you can open it in any browser.

On GitHub Actions it is rebuilt every run and attached to the run as the `dashboard` artifact (kept 7 days).
For a permanent web page:
1. **Settings → Pages → Build and deployment → Source: GitHub Actions**
2. **Settings → Secrets and variables → Actions → Variables**: add `ENABLE_PAGES` = `true`

Heads-up: a Pages site is normally readable by anyone who has the URL, so it exposes your product list and
target prices. If you don't want that, skip Pages and use the artifact.

Price history lives in the same Actions cache as the rest of the state, so it resets if the cache is
ever evicted (after 7 days with no runs).

## Bot-health messages
If a product can't be read for `fail_alert_after` checks in a row (default 3), you get one WhatsApp message
naming it and the reason, and another when it starts working again. Like deal alerts, these need an approved
template outside Meta's 24-hour window: create a Utility template with the body `robodiscounts: {{1}}`
and set `WHATSAPP_STATUS_TEMPLATE` to its name (without it, plain text is sent and may be dropped).

## If WhatsApp isn't working
Sending problems never stop price tracking. Missing credentials, a bad token or a network error are logged, the run
exits with an error, and the alert is **not** marked as delivered, so it is retried on the next run. Prices, history
and the dashboard keep updating meanwhile.

## Deal rules (per item)
The bot has no built-in idea of a "good price": a deal is whatever your rules say. The main rule for
sealed product is MSRP:
- `msrp` + `max_percent_of_msrp`: alert when price <= that percentage of the MSRP you set
  (default 100 = at or below MSRP; 90 = at least 10% off; 130 = up to 30% over). Alerts read like
  `87% of MSRP $49.99`. You supply the MSRP, since sites don't publish it reliably. Works on every site.

History rules, based on the prices the bot has recorded for that product (in-stock reads only):
- `below_avg_percent`: alert when the price is at least this % below the average of the last `history_days`
  days (default 30). Alert reads like `15% below the 30-day average $94.00`.
- `alert_on_new_low: true`: alert when the price beats the lowest price ever recorded.
- Both stay silent until there are at least 5 earlier reads, so they need a few days of hourly checks before
  they can fire. History starts when you deploy; the bot can't look back at prices from before that.

Other rules, combinable with all of the above (any one matching triggers an alert):
- `target_price`: alert when price <= value
- `min_discount_percent`: alert when discount vs the strike-through list price >= value (only Best Buy and Amazon show one)
- `min_drop_percent`: alert when price falls this much vs the last price seen

Also per item:
- `alert_on_restock: true`: alert when an item that was sold out is available again. Stock status is
  only known for Best Buy (via the API); other sites report it as unknown. Sold-out items never trigger
  price alerts, and they are not counted as failures.

An alert is sent once per price, so you won't get repeats until the price changes. If a price stops qualifying and later returns to the same level, it alerts again.

## Notes
- Scraping can break when sites change layout, and Amazon may show CAPTCHAs; keep intervals sane (hourly+).
  Failures are logged and skipped. Prefer official APIs (Amazon PA-API, TCGplayer API) if you need reliability.
- Run it on an always-on machine (VPS, Raspberry Pi) or a cron job; Cloud containers are ephemeral.

## Tests
`python -m pytest`
