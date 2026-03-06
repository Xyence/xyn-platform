#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REGISTRY="public.ecr.aws/i0h0h0n4/xyn/artifacts"
UI_REPO="$REGISTRY/xyn-ui"
API_REPO="$REGISTRY/xyn-api"
NET_INVENTORY_REPO="$REGISTRY/net-inventory-api"
SHORT_SHA="$(git rev-parse --short=7 HEAD)"
SHA_TAG="sha-${SHORT_SHA}"
PUBLISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

login_ecr_public() {
  if command -v aws >/dev/null 2>&1; then
    aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws
  else
    echo "aws CLI not found; skipping ECR login. Ensure you are already authenticated to push."
  fi
}

get_digest() {
  local ref="$1"
  local digest=""

  if docker buildx imagetools inspect "$ref" >/tmp/xyn-imagetools.txt 2>/dev/null; then
    digest="$(awk '/Digest:/ {print $2; exit}' /tmp/xyn-imagetools.txt)"
  elif docker manifest inspect "$ref" >/tmp/xyn-manifest.json 2>/dev/null; then
    digest="$(grep -m1 -o '"digest"[[:space:]]*:[[:space:]]*"[^"]*"' /tmp/xyn-manifest.json | sed -E 's/.*"([^"]+)"/\1/')"
  fi

  if [[ -n "$digest" ]]; then
    echo "$digest"
  else
    echo "(digest unavailable)"
  fi
}

echo "Logging in to ECR Public..."
login_ecr_public

echo "Building xyn-ui image..."
docker build \
  -f apps/xyn-ui/Dockerfile \
  -t "${UI_REPO}:dev" \
  -t "${UI_REPO}:${SHA_TAG}" \
  apps/xyn-ui

echo "Building xyn-api image..."
docker build \
  -f services/xyn-api/Dockerfile \
  -t "${API_REPO}:dev" \
  -t "${API_REPO}:${SHA_TAG}" \
  services/xyn-api

echo "Building net-inventory-api image..."
docker build \
  -f services/net-inventory-api/Dockerfile \
  -t "${NET_INVENTORY_REPO}:dev" \
  -t "${NET_INVENTORY_REPO}:${SHA_TAG}" \
  services/net-inventory-api

echo "Pushing xyn-ui tags..."
docker push "${UI_REPO}:dev"
docker push "${UI_REPO}:${SHA_TAG}"

echo "Pushing xyn-api tags..."
docker push "${API_REPO}:dev"
docker push "${API_REPO}:${SHA_TAG}"

echo "Pushing net-inventory-api tags..."
docker push "${NET_INVENTORY_REPO}:dev"
docker push "${NET_INVENTORY_REPO}:${SHA_TAG}"

mkdir -p releases
if [[ "${SKIP_RELEASE_MANIFEST_WRITE:-0}" != "1" ]]; then
  cat > releases/dev.json <<JSON
{
  "channel": "dev",
  "published_at": "${PUBLISHED_AT}",
  "images": {
    "xyn-ui": "${UI_REPO}:${SHA_TAG}",
    "xyn-api": "${API_REPO}:${SHA_TAG}",
    "net-inventory-api": "${NET_INVENTORY_REPO}:${SHA_TAG}"
  }
}
JSON
fi

echo
printf 'Published image refs:\n'
printf '  %s (digest: %s)\n' "${UI_REPO}:dev" "$(get_digest "${UI_REPO}:dev")"
printf '  %s (digest: %s)\n' "${UI_REPO}:${SHA_TAG}" "$(get_digest "${UI_REPO}:${SHA_TAG}")"
printf '  %s (digest: %s)\n' "${API_REPO}:dev" "$(get_digest "${API_REPO}:dev")"
printf '  %s (digest: %s)\n' "${API_REPO}:${SHA_TAG}" "$(get_digest "${API_REPO}:${SHA_TAG}")"
printf '  %s (digest: %s)\n' "${NET_INVENTORY_REPO}:dev" "$(get_digest "${NET_INVENTORY_REPO}:dev")"
printf '  %s (digest: %s)\n' "${NET_INVENTORY_REPO}:${SHA_TAG}" "$(get_digest "${NET_INVENTORY_REPO}:${SHA_TAG}")"
if [[ "${SKIP_RELEASE_MANIFEST_WRITE:-0}" == "1" ]]; then
  printf '\nSkipped bridge manifest write (SKIP_RELEASE_MANIFEST_WRITE=1).\n'
else
  printf '\nWrote bridge manifest: releases/dev.json\n'
fi
