REGISTRY := public.ecr.aws/i0h0h0n4/xyn/artifacts
SHORT_SHA := $(shell git rev-parse --short=7 HEAD)
SHA_TAG := sha-$(SHORT_SHA)

.PHONY: build publish-dev

build:
	docker build -f apps/xyn-ui/Dockerfile -t $(REGISTRY)/xyn-ui:$(SHA_TAG) apps/xyn-ui
	docker build -f services/xyn-api/Dockerfile -t $(REGISTRY)/xyn-api:$(SHA_TAG) services/xyn-api

publish-dev:
	./scripts/publish_dev.sh
