# Run long-running servers in separate terminals: `make backend` in one, `make frontend` in another.
.DEFAULT_GOAL := help

.PHONY: help backend frontend

help:
	@echo "Targets:"
	@echo "  make backend   - API server (backend/.venv python main.py)"
	@echo "  make frontend  - Electron app (npm start in frontend/)"

backend:
	cd backend && .venv/bin/python main.py

frontend:
	cd frontend && npm start
