VANCE  := docker compose -f infra/docker/docker-compose.vance.yml
TOOLS  := docker compose -f infra/docker/docker-compose.tools.yml

CORE_SERVICES   := postgres redis orchestrator marketing forge
ALL_AGENTS      := marketing outreach sales reviews ads content video viral seo support \
                   dev qa deploy security backup scaling onboarding launch \
                   research intel strategy finance analytics reporting memory \
                   forge localrankgrader integrations

.PHONY: dev agents tools all logs stop

## dev — start core services only (postgres, redis, orchestrator, marketing, forge)
dev:
	$(VANCE) up -d $(CORE_SERVICES)

## agents — start all agent services (includes core)
agents:
	$(VANCE) up -d postgres redis orchestrator webhooks celery_worker celery_beat searxng playwright $(ALL_AGENTS)

## tools — start the ops tools stack
tools:
	$(TOOLS) up -d

## all — start everything
all: agents tools

## logs — tail all running service logs
logs:
	$(VANCE) logs -f --tail=100

## stop — stop all services cleanly
stop:
	$(VANCE) down
	$(TOOLS) down
