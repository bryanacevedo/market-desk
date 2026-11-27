# Runbook

## Static snapshot of the public demo

The public demo can be served as static files: the web app plus every response it needs, saved from a demo database. No server, no database, no sign-in. Decided by Bryan on 2026-11-15 (Backlog bl_116); how it works is `docs/DECISIONS.md` 62. It is staged on Cloudflare Pages, project `market-desk-demo`, with noindex, and linked from nowhere until Bryan says so. The Render demo is unchanged. 2026-11-18: the README links the snapshot as the live demo (0645005), and the two Cloudflare secrets are set on the repository, so the workflow deploys.

### What the snapshot holds

- Every page in the navigation as both people the desk lets you act as, RevOps and the manager, with the acting-as menu working between them (Sources and Settings are RevOps's pages, as in the demo).
- Every page of the account list (17,989 companies: the list leaves out competitors and sole traders) and the first 3 pages of each single filter: tier, segment, owner, unassigned, region group.
- Every sheet a page can open: each company, segment, finding, profile version (with what moves and the publish preview), territory plan (with the activate preview), person, move by hand, test, proposal, book and source.
- The handoff files and ICP previews the pages offer as downloads, as plain files under `api/books/` and `api/handoffs/preview/`.

### What degrades, and how

- Every change (publish, activate, move, start a test, draft or dismiss a proposal, write a book, save a setting) gets "The public demo does not do this. Run it yourself to try it." Market Desk's own server has no such sentence (its public demo accepts writes into a throwaway database); the wording is the one CRM Desk's snapshot uses.
- A search or a combined filter on Accounts, and the account list past the first 3 pages of a single filter, says the snapshot keeps every page of the list and the first pages of each single filter, and that searches need the full demo.
- The "Move accounts" form's search, territory preview and candidate lists: not in the snapshot, with the same pointer. A transfer that was already saved opens.
- The notice a manager has seen is not remembered (a change).
- The snapshot is as old as its build, and the desk's clock is the demo's (the world clock stays).

### Build

```bash
make demo          # or any demo database: DATABASE_URL=... python -m market demo
make snapshot      # writes .snapshot/; DATABASE_URL names the demo database
```

`scripts/build_static_snapshot.py` builds the web app, runs the API inside the script's own process (FastAPI's test client, no port) against the demo database with `PUBLIC_DEMO=1`, and reads it the way the screens do. It sends only GETs. One read in this app writes: the first read of the marketing qualified rule publishes its version 1, so the script makes that read before it takes the database's fingerprint. The fingerprint (row count and newest row version of every table) is compared before and after the crawl, so the build stops if the crawl changed anything. It also stops when a path the screens read (parsed from `web/src`) has no saved answer, when the bundle is over 60 MB, or over 19,000 files.

The bundle: `index.html` with `<meta name="robots" content="noindex,nofollow">`, `snapshot-config.js` (who the visitors can act as and the date) and `snapshot-shim.js` loaded first; `_snapshot/` holds the saved answers as gzip shards (up to 4,096) keyed by the first 3 hex digits of each request's SHA-1 (method, path, sorted query, body, and who is acting); an answer that is the same for both people is saved once and the other key points to it; `_headers` sends `X-Robots-Tag: noindex, nofollow` on every path; `robots.txt` disallows everything; `snapshot-manifest.json` lists every saved request. On 2026-11-17 it was 16.3 MB in 4,129 files (4,096 of them shards), built in about 4 minutes on a laptop with 37,468 saved answers.

`tests/test_static_snapshot.py` checks that every path the screens read has a saved answer, that the crawl changes nothing and sends only GETs, that the shim and the build compute the same key, that the shim answers from the bundle (including the answers kept once) and refuses every change with one sentence, that the handoff files are plain files, and that the bundle is noindex.

### Deploy

GitHub Actions, `.github/workflows/static-snapshot.yml`: on a push to `main` that touches `web/`, `src/`, `world/`, `migrations/`, the snapshot script, `scripts/static_snapshot/` or the workflow, and by hand (Actions, static snapshot, Run workflow). It builds the demo on a throwaway Postgres, builds the snapshot, keeps it as an artifact for 30 days (`market-desk-snapshot-<commit>`), and deploys to Pages only when the repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are set. Without them the run passes and deploys nothing. Both secrets are set (2026-11-18), so every such push deploys; the latest, run 45962315544 on 2026-11-27, deployed 6313327. To set them again, set the two secrets (each command asks for the value):

```bash
gh secret set CLOUDFLARE_API_TOKEN -R bryanacevedo/market-desk
gh secret set CLOUDFLARE_ACCOUNT_ID -R bryanacevedo/market-desk
```

From a laptop, with the token from Infisical (project prod, root path; never printed):

```bash
infisical run --env prod --recursive -- sh -c 'env -i PATH="$PATH" HOME="$HOME" CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" CLOUDFLARE_ACCOUNT_ID="$CLOUDFLARE_ACCOUNT_ID" npx --yes wrangler@4.156.1 pages deploy .snapshot --project-name market-desk-demo --branch main'
```

### Roll back

Each deploy is kept. Either:

- List the deployments (`npx wrangler@4.156.1 pages deployment list --project-name market-desk-demo`, same environment as above) and roll production back to an earlier one: in the Cloudflare dashboard (Workers and Pages, market-desk-demo, Deployments, the deployment's menu, Rollback to this deployment), or through the API, `POST /accounts/<account>/pages/projects/market-desk-demo/deployments/<deployment id>/rollback` with the token. Verified on 2026-11-17: a rollback to the first deployment and back to the second, each serving 200 within seconds.
- Or download an earlier run's artifact from GitHub Actions and deploy that folder with the command above.

To take the snapshot down entirely, delete the Pages project in the dashboard (only on Bryan's word).
