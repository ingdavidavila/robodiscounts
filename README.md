# robodiscounts

Watches Best Buy (official API), TCGplayer and Amazon product pages and sends a WhatsApp message (Meta Cloud API) when an item hits your deal rules.

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
- `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TO`, `BESTBUY_API_KEY`, and optionally `WHATSAPP_TEMPLATE`

If every item fails to load, the run fails (red) so you notice. When a page can't be parsed, the workflow uploads
its HTML and a screenshot as the `debug-pages` artifact on the run page (kept 3 days); locally, set
`ROBODISCOUNTS_DEBUG_DIR=debug` to get the same files.

Last-seen prices are kept between runs with the Actions cache, so you only get one alert per price.
Caveats: GitHub may pause scheduled workflows after 60 days without repo activity, runs can be delayed
by several minutes, and Amazon often blocks datacenter IPs like GitHub's runners (a self-hosted runner
or a small VPS with cron is more reliable).

## Deal rules (per item)
- `target_price`: alert when price <= value
- `min_discount_percent`: alert when discount vs the strike-through list price >= value (Amazon)
- `min_drop_percent`: alert when price falls this much vs the last price seen

An alert is sent once per price, so you won't get repeats until the price changes.

## Notes
- Scraping can break when sites change layout, and Amazon may show CAPTCHAs; keep intervals sane (hourly+).
  Failures are logged and skipped. Prefer official APIs (Amazon PA-API, TCGplayer API) if you need reliability.
- Run it on an always-on machine (VPS, Raspberry Pi) or a cron job; Cloud containers are ephemeral.

## Tests
`python -m pytest`
