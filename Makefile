.PHONY: up down health restart status

up:
	./scripts/up.sh

down:
	./scripts/down.sh

health:
	./scripts/health-check.sh

restart: down up

status:
	kubectl -n proving-ground get pods -o wide
