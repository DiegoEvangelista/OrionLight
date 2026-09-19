# build.ps1 — Build e tag da imagem orion-light (Windows / PowerShell)
#
# A versao e lida do arquivo VERSION (ex: 1.0.0).
# Para bumpar: edite VERSION, faca commit, depois rode .\build.ps1
#
# Uso:
#   .\build.ps1           => build + tag local (sem push)
#   .\build.ps1 -Push     => build + tag + push para docker.upgoos.com

param(
    [switch]$Push
)

$Image    = "orion-light"
$Registry = "docker.upgoos.com"
$FullName = "$Registry/$Image"

if (-not (Test-Path "VERSION")) {
    Write-Error "Arquivo VERSION nao encontrado. Crie-o com o numero da versao (ex: 1.0.0)"
    exit 1
}

$Version = (Get-Content "VERSION" -Raw).Trim()
if ([string]::IsNullOrEmpty($Version)) {
    Write-Error "Arquivo VERSION esta vazio."
    exit 1
}

Write-Host "Versao  : $Version"
Write-Host "Imagem  : ${FullName}"
Write-Host ""

Write-Host "=> Building ${FullName}:${Version}"
docker build -t "${FullName}:${Version}" .
if (-not $?) { exit 1 }

Write-Host "=> Tagging ${FullName}:latest"
docker tag "${FullName}:${Version}" "${FullName}:latest"

if ($Push) {
    Write-Host ""
    Write-Host "=> Pushing ${FullName}:${Version}"
    docker push "${FullName}:${Version}"
    if (-not $?) { exit 1 }

    Write-Host "=> Pushing ${FullName}:latest"
    docker push "${FullName}:latest"
    if (-not $?) { exit 1 }
}

Write-Host ""
Write-Host "[OK] Pronto"
docker images $FullName --format '  {{.Repository}}:{{.Tag}}  ({{.Size}})'
