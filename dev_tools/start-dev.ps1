<#
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0

.SYNOPSIS
    Start the Auto-Ontology development stack natively (no application containers).

.DESCRIPTION
    Brings up, in order and only once:

      1. Postgres            Docker container `postgres` (the only containerised piece)
      2. FastAPI backend     .venv python -m uvicorn, --reload, 127.0.0.1:3001
      3. Ingestion service   .venv python -m all_ontology.ingestion_service, 3002
      4. Next.js frontend    pnpm dev, 3000

    Each step waits for the previous one to actually answer before the next
    starts, so the "connection timeout expired / schema revision unreadable"
    startup race cannot happen. Services already running and healthy are
    reused instead of started twice. Logs go to <repo>\logs\.

.EXAMPLE
    .\dev_tools\start-dev.ps1

.EXAMPLE
    .\dev_tools\start-dev.ps1 -Force          # restart everything

.EXAMPLE
    .\dev_tools\start-dev.ps1 -NoFrontend     # backend + ingestion only
#>
[CmdletBinding()]
param(
    # Stop and restart components that are already running.
    [switch]$Force,
    # Skip the Next.js frontend.
    [switch]$NoFrontend,
    # Skip the standalone ingestion service.
    [switch]$NoIngestion,
    # Do not wait for the database at all (rarely useful).
    [switch]$SkipPostgres,
    # Start the bundled Postgres container from docker-compose.yml. Off by
    # default: the database is whatever POSTGRES_* in .env points at, which is
    # normally an instance this repository does not manage.
    [switch]$WithDockerPostgres,
    # How long to wait for the backend /health endpoint.
    [int]$HealthTimeoutSec = 240,
    [int]$FrontendTimeoutSec = 300
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'dev-common.ps1')

$repo = Resolve-RepoRoot -ScriptDir $PSScriptRoot
Set-Location -LiteralPath $repo

$logs = Join-Path $repo 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$pidsFile = Join-Path $logs 'dev-pids.json'

$python = Join-Path $repo '.venv\Scripts\python.exe'
$frontendDir = Join-Path $repo 'frontend'

$previous = $null
if (Test-Path -LiteralPath $pidsFile) {
    try { $previous = Get-Content -LiteralPath $pidsFile -Raw | ConvertFrom-Json } catch { $previous = $null }
}

$backendUrl = 'http://127.0.0.1:3001/api/health'
$ingestUrl = 'http://127.0.0.1:3002/health/live'
$frontendUrl = 'http://localhost:3000/login'

Write-Host ''
Write-Host 'Auto-Ontology - native dev stack' -ForegroundColor White
Write-Host "repo: $repo" -ForegroundColor DarkGray
Write-Host ''

if (-not (Test-Path -LiteralPath $python)) {
    Write-Fail "Python virtualenv not found: $python"
    Write-Host '  create it once from the repo root:  uv sync' -ForegroundColor DarkGray
    exit 1
}

# --------------------------------------------------------------------------- #
# 1. Postgres
#
# The database is whatever POSTGRES_* in .env points at. This repository does
# not own it: in a company setup it is a managed instance, and starting a
# container would either be pointless or shadow the real one. `-WithDockerPostgres`
# is the opt-in for the bundled compose service, which is only useful on a
# machine that has nothing else.
# --------------------------------------------------------------------------- #
if ($SkipPostgres) {
    Write-Warn 'skipping the database wait (-SkipPostgres)'
} else {
    Write-Step 'Postgres'
    if ($WithDockerPostgres) {
        if (-not (Test-DockerEngine)) {
            $desktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
            if (Test-Path -LiteralPath $desktop) {
                Write-Warn 'Docker engine is not responding; launching Docker Desktop'
                Start-Process -FilePath $desktop | Out-Null
            }
            $deadline = (Get-Date).AddSeconds(180)
            while ((Get-Date) -lt $deadline -and -not (Test-DockerEngine)) { Start-Sleep -Seconds 3 }
            if (-not (Test-DockerEngine)) {
                Write-Fail 'Docker engine did not come up within 180s - start Docker Desktop and retry'
                exit 1
            }
        }

        & docker compose up -d --wait postgres
        if ($LASTEXITCODE -ne 0) {
            Write-Fail 'docker compose up -d --wait postgres failed'
            exit 1
        }
    }

    # Either way, prove the app's own credentials and target database work before
    # starting anything that reads the Alembic revision at import time. A
    # `--wait` that only watched a container healthcheck is not that proof.
    & $python -m dev_tools.wait_for_db 180
    if ($LASTEXITCODE -ne 0) {
        Write-Fail 'the database in .env never accepted a connection'
        Write-Host "  host: $((Get-DotEnvValue -Path (Join-Path $repo '.env') -Key 'POSTGRES_HOST'))" -ForegroundColor DarkGray
        if ($WithDockerPostgres) { & docker compose logs --tail 40 postgres }
        exit 1
    }
    Write-Ok 'database accepting connections'
}

# --------------------------------------------------------------------------- #
# 2. FastAPI backend (port 3001)
# --------------------------------------------------------------------------- #
Write-Step 'backend (FastAPI, 127.0.0.1:3001)'
$backendPid = 0

$owner = Get-PortOwner -Port 3001
$reusable = $owner -and
    (Test-ProjectCmdLine -CommandLine $owner.CommandLine -RepoRoot $repo) -and
    ((Get-HttpStatus -Url $backendUrl) -eq 200)

if ($Force -or -not $reusable) {
    if ($owner) { [void](Clear-PortListeners -RepoRoot $repo -Ports @(3001)) }
} else {
    # `--reload` binds the port from a worker child; record the supervisor so
    # stopping later tears the whole tree down instead of being respawned.
    $recorded = if ($previous) { [int]$previous.backend } else { 0 }
    $backendPid = Resolve-ComponentPid -OwnerPid $owner.Pid -RecordedPid $recorded -RepoRoot $repo
    Write-Ok "already running and healthy (pid $backendPid)"
}

if ($backendPid -eq 0) {
    if (Get-PortOwner -Port 3001) {
        Write-Fail 'port 3001 is still busy after cleanup - free it and retry'
        exit 1
    }
    $backend = Start-LoggedProcess -FilePath $python -WorkingDirectory $repo -Name 'backend' -LogDir $logs -Arguments @(
        '-m', 'uvicorn', 'all_ontology.server.__main__:create_app',
        '--factory', '--reload', '--reload-dir', 'all_ontology',
        '--host', '127.0.0.1', '--port', '3001'
    )
    Write-Host "  ..  starting (pid $($backend.Pid)), waiting for $backendUrl" -ForegroundColor DarkGray
    if (-not (Wait-HttpStatus -Url $backendUrl -TimeoutSec $HealthTimeoutSec -Accept @(200) -ProcessId $backend.Pid)) {
        Write-Fail 'backend did not become healthy'
        Show-LogTail -Path $backend.StdErr -Lines 30
        Show-LogTail -Path $backend.StdOut -Lines 15
        exit 1
    }
    $backendPid = $backend.Pid
    Write-Ok "started (pid $backendPid)"
}

# --------------------------------------------------------------------------- #
# 3. Ingestion service (port 3002)
# --------------------------------------------------------------------------- #
$ingestPid = 0
if ($NoIngestion) {
    Write-Warn 'skipping ingestion service (-NoIngestion)'
} else {
    Write-Step 'ingestion service (127.0.0.1:3002)'
    $owner = Get-PortOwner -Port 3002
    $reusable = $owner -and
        (Test-ProjectCmdLine -CommandLine $owner.CommandLine -RepoRoot $repo) -and
        ((Get-HttpStatus -Url $ingestUrl) -eq 200)

    if ($Force -or -not $reusable) {
        if ($owner) { [void](Clear-PortListeners -RepoRoot $repo -Ports @(3002)) }
    } else {
        $recorded = if ($previous) { [int]$previous.ingestion } else { 0 }
        $ingestPid = Resolve-ComponentPid -OwnerPid $owner.Pid -RecordedPid $recorded -RepoRoot $repo
        Write-Ok "already running and healthy (pid $ingestPid)"
    }

    if ($ingestPid -eq 0) {
        $ingest = Start-LoggedProcess -FilePath $python -WorkingDirectory $repo -Name 'ingestion' -LogDir $logs -Arguments @(
            '-m', 'all_ontology.ingestion_service'
        )
        Write-Host "  ..  starting (pid $($ingest.Pid)), waiting for $ingestUrl" -ForegroundColor DarkGray
        if (-not (Wait-HttpStatus -Url $ingestUrl -TimeoutSec 120 -Accept @(200) -ProcessId $ingest.Pid)) {
            Write-Fail 'ingestion service did not become healthy'
            Show-LogTail -Path $ingest.StdErr -Lines 25
            Show-LogTail -Path $ingest.StdOut -Lines 15
            exit 1
        }
        $ingestPid = $ingest.Pid
        Write-Ok "started (pid $ingestPid)"
    }
}

# --------------------------------------------------------------------------- #
# 4. Next.js frontend (port 3000)
# --------------------------------------------------------------------------- #
$frontendPid = 0
if ($NoFrontend) {
    Write-Warn 'skipping frontend (-NoFrontend)'
} else {
    Write-Step 'frontend (Next.js, localhost:3000)'
    $owner = Get-PortOwner -Port 3000
    $frontendStatus = if ($owner) { Get-HttpStatus -Url $frontendUrl } else { 0 }
    $reusable = $owner -and
        (Test-ProjectCmdLine -CommandLine $owner.CommandLine -RepoRoot $repo) -and
        ($frontendStatus -ge 200 -and $frontendStatus -lt 400)

    if ($Force -or -not $reusable) {
        if ($owner) { [void](Clear-PortListeners -RepoRoot $repo -Ports @(3000)) }
    } else {
        $recorded = if ($previous) { [int]$previous.frontend } else { 0 }
        $frontendPid = Resolve-ComponentPid -OwnerPid $owner.Pid -RecordedPid $recorded -RepoRoot $repo
        Write-Ok "already running and answering (pid $frontendPid)"
    }

    if ($frontendPid -eq 0) {
        if (Get-PortOwner -Port 3000) {
            Write-Fail 'port 3000 is still busy after cleanup - free it and retry'
            exit 1
        }
		# `pnpm build` leaves a production `.next` behind, and `next dev` then
		# serves pages while 404-ing every route handler (the app-paths manifest
		# on disk wins over the dev compiler). Clear it before starting dev.
		$nextDir = Join-Path $frontendDir '.next'
		if (Test-Path -LiteralPath (Join-Path $nextDir 'BUILD_ID')) {
			Write-Warn 'frontend\.next holds a production build; clearing it for dev'
			try {
				Remove-Item -LiteralPath $nextDir -Recurse -Force -ErrorAction Stop
			} catch {
				# Locked file or a policy that blocks recursive deletes: moving it
				# out of the way is enough, and keeps the old build recoverable.
				$stale = Join-Path $frontendDir ('.next.stale-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
				Move-Item -LiteralPath $nextDir -Destination $stale -Force
				Write-Warn "moved the old build to $(Split-Path -Leaf $stale)"
			}
		}
        $pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
        if (-not $pnpm) { $pnpm = Get-Command pnpm -ErrorAction SilentlyContinue }
        if (-not $pnpm) {
            Write-Fail 'pnpm not found on PATH'
            exit 1
        }
        $frontend = Start-LoggedProcess -FilePath $pnpm.Source -WorkingDirectory $frontendDir -Name 'frontend' -LogDir $logs -Arguments @('dev')
        Write-Host "  ..  starting (pid $($frontend.Pid)), first compile can take a minute" -ForegroundColor DarkGray
        if (-not (Wait-HttpStatus -Url $frontendUrl -TimeoutSec $FrontendTimeoutSec -Accept @(200) -ProcessId $frontend.Pid)) {
            Write-Fail 'frontend did not answer on http://localhost:3000/login'
            Show-LogTail -Path $frontend.StdErr -Lines 30
            Show-LogTail -Path $frontend.StdOut -Lines 20
            exit 1
        }
        $frontendPid = $frontend.Pid
        Write-Ok "started (pid $frontendPid)"
    }
}

# --------------------------------------------------------------------------- #
# Record PIDs + summarise
# --------------------------------------------------------------------------- #
$record = [ordered]@{
    repo      = $repo
    startedAt = (Get-Date).ToString('o')
    backend   = $backendPid
    ingestion = $ingestPid
    frontend  = $frontendPid
}
$record | ConvertTo-Json | Set-Content -LiteralPath $pidsFile -Encoding utf8

$adminEmail = Get-DotEnvValue -Path (Join-Path $repo '.env') -Key 'ALL_ONTOLOGY_ADMIN_EMAIL'
$adminPassword = Get-DotEnvValue -Path (Join-Path $repo '.env') -Key 'ALL_ONTOLOGY_ADMIN_PASSWORD'

Write-Host ''
Write-Host '  dev stack is up' -ForegroundColor Green
Write-Host ''
Write-Host '    frontend   http://localhost:3000'
Write-Host '    api        http://127.0.0.1:3001/api/health'
if ($ingestPid -gt 0) { Write-Host '    ingestion  http://127.0.0.1:3002/health/live' }
if ($adminEmail) { Write-Host "    sign in    $adminEmail / $adminPassword" }
Write-Host ''
Write-Host "    logs       $logs"
Write-Host '    stop       .\dev_tools\stop-dev.ps1'
Write-Host ''
exit 0
