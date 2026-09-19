#!/usr/bin/env bash
# build.sh — Build e tag da imagem orion-light
#
# A versão é lida do arquivo VERSION (ex: 1.0.0).
# Para bumpar: edite VERSION, faça commit, depois rode ./build.sh
#
# Uso:
#   ./build.sh              → lê versão do arquivo VERSION
#   ./build.sh push         → build + push para o registry configurado
#
# Registry privado (ex: Azure Container Registry):
#   export REGISTRY=myregistry.azurecr.io
#   ./build.sh push

set -euo pipefail

IMAGE="orion-light"
PUSH="${1:-}"
REGISTRY="${REGISTRY:-docker.upgoos.com}"

# Lê a versão do arquivo VERSION
if [[ ! -f VERSION ]]; then
  echo "Erro: arquivo VERSION não encontrado. Crie-o com o número da versão (ex: 1.0.0)"
  exit 1
fi
VERSION="$(tr -d '[:space:]' < VERSION)"
if [[ -z "${VERSION}" ]]; then
  echo "Erro: arquivo VERSION está vazio."
  exit 1
fi

FULL_NAME="${REGISTRY:+$REGISTRY/}${IMAGE}"

echo "Versão: ${VERSION}"
echo "→ Building ${FULL_NAME}:${VERSION}"
docker build -t "${FULL_NAME}:${VERSION}" .

echo "→ Tagging ${FULL_NAME}:latest"
docker tag "${FULL_NAME}:${VERSION}" "${FULL_NAME}:latest"

if [[ "${PUSH}" == "push" ]]; then
  echo "→ Pushing ${FULL_NAME}:${VERSION}"
  docker push "${FULL_NAME}:${VERSION}"
  echo "→ Pushing ${FULL_NAME}:latest"
  docker push "${FULL_NAME}:latest"
fi

echo ""
echo "✓ Pronto"
docker images "${FULL_NAME}" --format "  {{.Repository}}:{{.Tag}}  ({{.Size}})"
