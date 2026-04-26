# Run long-running servers in separate terminals: `make backend` in one, `make frontend` in another.
.DEFAULT_GOAL := help
.PHONY: help run-backend run-frontend stop-backend restart-backend

help:
	@echo "Targets:"
	@echo "  make run-backend   - API server (backend/venv python main.py)"
	@echo "  make run-frontend  - Electron app (npm start in frontend/)"
	@echo "  make stop-backend  - Stop any process bound to API port 8000"
	@echo "  make restart-backend - Stop and restart API server"
	@echo "  make install       - Install dependencies"
	@echo "  make run           - Run both backend and frontend"

install:
	cd backend && python3 -m venv venv
	cd backend && venv/bin/pip install -r requirements.txt
	cd frontend && npm install

run-backend:
	cd backend && venv/bin/python main.py

stop-backend:
	@pids=$$(lsof -ti :8000); \
	if [ -n "$$pids" ]; then \
		echo "Stopping process(es) on port 8000: $$pids"; \
		kill $$pids; \
	else \
		echo "No process is bound to port 8000"; \
	fi

restart-backend: stop-backend
	cd backend && venv/bin/python main.py

run-frontend:
	cd frontend && npm start

run:
	make run-backend & make run-frontend