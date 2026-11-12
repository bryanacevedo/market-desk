.PHONY: setup db demo serve web dev test lint evals evals-live audit export
PY = PYTHONPATH=src .venv/bin/python

setup:            ## install Python and web dependencies
	uv sync
	cd web && npm ci --no-audit --no-fund

db:               ## start a private Postgres in .data/ (uses your installed Postgres 18)
	./scripts/pg.sh start

demo: db web      ## rebuild the demo world from its fixed seed, then serve it on :8800
	$(PY) -m market demo
	$(PY) -m market serve

serve:            ## serve the API and the built web app on :8800
	$(PY) -m market serve

web:              ## build the web app
	cd web && npm run build

dev:              ## web app with hot reload on :5173, API on :8800
	$(PY) -m market serve & cd web && npm run dev

test: db          ## the whole suite, on real Postgres
	$(PY) -m pytest

audit:            ## check the demo database against every product rule
	$(PY) scripts/audit_rules.py

export:           ## write the legacy world export to ./world-export (the shared world now lives in lumen-world)
	$(PY) -m market world-export world-export

evals:            ## every AI eval, replayed from recordings (free; what CI does)
	$(PY) evals/run.py

evals-live:       ## every AI eval against live Claude, recording each answer (capped at $15)
	ANTHROPIC_LIVE=1 $(PY) evals/run.py --cap-cents 1500

lint:
	.venv/bin/ruff check src tests evals scripts
	cd web && npm run typecheck
