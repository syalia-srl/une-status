# une-status

Status board for Empresa Eléctrica de La Habana. Crawls the public Telegram channel
[@EmpresaElectricaDeLaHabana](https://t.me/EmpresaElectricaDeLaHabana), extracts
events with regex/heuristics (zero AI), aggregates rollups, and publishes a
static dashboard.

**Live:** https://syalia-srl.github.io/une-status/

## How it works

- Every 15 minutes, GitHub Actions runs `une-status` which fetches the latest
  page of the public channel preview (`t.me/s/<channel>`), classifies new
  messages, extracts structured events, updates today's rollup, and rewrites
  `data/data.json` (consumed by the dashboard).
- Backfill (2022-08-05 → today) is done offline via `une-backfill` and the
  resulting `daily/` and `monthly/` rollups are committed once.
- Raw messages and per-event records are retained only for the current and
  previous day; older data is preserved as compact daily and monthly rollups.

## Local dev

```sh
uv sync
uv run python -m une_status.update        # one incremental pass
uv run python -m une_status.backfill      # full historical backfill
uv run pytest                              # tests
```

## Data layout

```
data/
├── data.json              # the dashboard reads this
├── state.json             # crawl state (last_msg_id)
├── raw/<date>.jsonl       # raw msgs (today + yesterday only)
├── events/<date>.jsonl    # extracted events (today + yesterday only)
├── daily/<date>.json      # daily rollup (kept forever)
└── monthly/<month>.json   # monthly rollup (kept forever)
```

## Attribution

Datos públicos recolectados automáticamente desde el canal de Telegram
[@EmpresaElectricaDeLaHabana](https://t.me/EmpresaElectricaDeLaHabana).
No afiliado a la Empresa Eléctrica de La Habana ni a la UNE.

## License

MIT.
