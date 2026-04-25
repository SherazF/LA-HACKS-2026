# Run long-running servers in separate terminals: `make backend` in one, `make frontend` in another.
.DEFAULT_GOAL := help
.PHONY: help run-backend run-frontend

help:
	@echo "Targets:"
	@echo "  make run-backend   - API server (backend/.venv python main.py)"
	@echo "  make run-frontend  - Electron app (npm start in frontend/)"
	@echo "  make install       - Install dependencies"

install:
	cd backend && python3 -m venv venv
	cd backend && venv/bin/pip install -r requirements.txt
	cd ../frontend && npm install

run-backend:
	cd backend && .venv/bin/python main.py

run-frontend:
	cd frontend && npm start
