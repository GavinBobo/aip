<#
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0

.SYNOPSIS
    Stop the native Auto-Ontology dev stack started by start-dev.ps1.

.DESCRIPTION
    Kills the recorded process trees from <repo>\logs\dev-pids.json and, as a
    fallback, anything of this repo still listening on 3000/3001/3002.
    Postgres (the Docker container) keeps running unless -IncludePostgres is
    passed, so the next start is instant.

.EXAMPLE
    .\dev_tools\stop-dev.ps1

.EXAMPLE
    .\dev_tools\stop-dev.ps1 -IncludePostgres
#>
[CmdletBinding()]
param(
    # Also stop the Postgres container.
    [switch]$IncludePostgres
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'dev-common.ps1')

$repo = Resolve-RepoRoot -ScriptDir $PSScriptRoot
Set-Location -LiteralPath $repo

$logs = Join-Path $repo 'logs'
$pidsFile = Join-Path $logs 'dev-pids.json'

Write-Host ''
Write-Host 'Auto-Ontology - stopping dev stack' -ForegroundColor White
Write-Host ''

# 1. Anything we recorded last start.
if (Test-Path -LiteralPath $pidsFile) {
    $record = Get-Content -LiteralPath $pidsFile -Raw | ConvertFrom-Json
    foreach ($name in @('frontend', 'ingestion', 'backend')) {
        $procId = [int]($record.$name)
        if ($procId -le 0) { continue }
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
        if (-not $proc) {
            Write-Ok "$name (pid $procId) already gone"
            continue
        }
        Write-Step "stopping $name (pid $procId)"
        Stop-ProcessTree -RootProcessId $procId
    }
    Remove-Item -LiteralPath $pidsFile -Force -ErrorAction SilentlyContinue
} else {
    Write-Warn 'no logs\dev-pids.json - falling back to port scan'
}

# 2. Anything of this repo still listening (covers manual `pnpm dev` / uvicorn runs).
$freed = Clear-PortListeners -RepoRoot $repo
foreach ($port in $freed) { Write-Ok "port $port freed" }

# 3. Report leftovers we deliberately did not touch.
foreach ($port in $DevPorts) {
    $owner = Get-PortOwner -Port $port
    if ($owner) { Write-Warn "port $port is still held by pid $($owner.Pid) ($($owner.Name)) - not ours, left alone" }
}

if ($IncludePostgres) {
    Write-Step 'stopping Postgres container'
    & docker compose stop postgres
    if ($LASTEXITCODE -eq 0) { Write-Ok 'postgres stopped' } else { Write-Warn 'could not stop postgres' }
}

Write-Host ''
Write-Host '  dev stack stopped' -ForegroundColor Green
Write-Host ''
exit 0
