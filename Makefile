PYTHON := ./venv/bin/python

.PHONY: test backend-test frontend-test build evaluate verify

backend-test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -q -p no:cacheprovider

frontend-test:
	cd frontend && npm test -- --run

build:
	cd frontend && npm run build

evaluate:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. $(PYTHON) scripts/run_evaluation.py

verify: backend-test frontend-test evaluate build

test: verify
