# robodiscounts

Watches Amazon and TCGplayer product pages and sends a WhatsApp message when an item hits your deal rules.

## Setup
```bash
pip install -r requirements.txt
playwright install chromium
cp config.example.yaml config.yaml   # add your products
cp .env.example .env                 # add Twilio credentials
```

### WhatsApp (Twilio)
1. Create a Twilio account and open **Messaging → Try it out → Send a WhatsApp message**.
2. Join the sandbox by sending the join code from your phone to the sandbox number.
3. Put the SID, auth token, sandbox number and your number in `.env`.
   (For production use, register a WhatsApp sender with Twilio.)

## Usage
```bash
python -m robodiscounts.cli test-message      # verify WhatsApp works
python -m robodiscounts.cli check --dry-run   # one pass, print alerts only
python -m robodiscounts.cli check             # one pass, send alerts (use with cron)
python -m robodiscounts.cli watch             # loop every check_interval_minutes
```

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
