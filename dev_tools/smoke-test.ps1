<#
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0

.SYNOPSIS
    Read-only smoke test for a running Auto-Ontology dev stack.

.DESCRIPTION
    Signs in with the bootstrap admin from .env and exercises the paths a
    browser would touch: the API health check, the sign-in endpoint, the main
    Next.js pages, and the ERD canvas for the first zone. Nothing is written.

.EXAMPLE
    .\dev_tools\smoke-test.ps1

.EXAMPLE
    .\dev_tools\smoke-test.ps1 -ApiUrl http://127.0.0.1:3001 -BaseUrl http://localhost:3000
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://localhost:3000',
    [string]$ApiUrl = 'http://127.0.0.1:3001',
    [int]$TimeoutSec = 90
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'dev-common.ps1')

$repo = Resolve-RepoRoot -ScriptDir $PSScriptRoot
$envFile = Join-Path $repo '.env'

$email = Get-DotEnvValue -Path $envFile -Key 'AUTO_ONTOLOGY_ADMIN_EMAIL'
$password = Get-DotEnvValue -Path $envFile -Key 'AUTO_ONTOLOGY_ADMIN_PASSWORD'

$ps7 = $PSVersionTable.PSVersion.Major -ge 6
$results = New-Object 'System.Collections.Generic.List[object]'

function Add-Result {
    param([string]$Check, [bool]$Ok, [string]$Detail = '')
    $results.Add([pscustomobject]@{ Check = $Check; Ok = $Ok; Detail = $Detail })
    if ($Ok) { Write-Ok "$Check $Detail" } else { Write-Fail "$Check $Detail" }
}

function Invoke-Web {
    param(
        [string]$Uri,
        [string]$Method = 'Get',
        $Body = $null,
        $Session = $null,
        [hashtable]$Headers = @{}
    )
    $splat = @{
        Uri             = $Uri
        Method          = $Method
        TimeoutSec      = $TimeoutSec
        Headers         = $Headers
    }
    if ($ps7) { $splat.SkipHttpErrorCheck = $true } 
    if ($Session) { $splat.WebSession = $Session }
    if ($null -ne $Body) {
        $splat.Body = ($Body | ConvertTo-Json -Depth 8)
        $splat.ContentType = 'application/json'
    }
    try {
        return Invoke-WebRequest @splat
    } catch {
        $response = $_.Exception.Response
        if ($response) {
            $code = try { [int]$response.StatusCode } catch { 0 }
            return [pscustomobject]@{ StatusCode = $code; Content = '' }
        }
        throw
    }
}

Write-Host ''
Write-Host 'Auto-Ontology - smoke test' -ForegroundColor White
Write-Host "  frontend $BaseUrl" -ForegroundColor DarkGray
Write-Host "  api      $ApiUrl" -ForegroundColor DarkGray
Write-Host ''

# 1. API health + schema revision
try {
    $health = Invoke-Web -Uri "$ApiUrl/api/health"
    $payload = $health.Content | ConvertFrom-Json
    $revision = $payload.migrations.revision
    Add-Result -Check 'api /api/health' -Ok ($health.StatusCode -eq 200 -and $payload.status -eq 'ok') `
        -Detail "(200, revision $revision)"
} catch {
    Add-Result -Check 'api /api/health' -Ok $false -Detail $_.Exception.Message
}

# 2. Ingestion liveness
try {
    $ingest = Invoke-Web -Uri 'http://127.0.0.1:3002/health/live'
    Add-Result -Check 'ingestion /health/live' -Ok ($ingest.StatusCode -eq 200) -Detail "($($ingest.StatusCode))"
} catch {
    Add-Result -Check 'ingestion /health/live' -Ok $false -Detail $_.Exception.Message
}

# 3. Sign in through the Next.js BFF
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$userId = $null
if (-not $email -or -not $password) {
    Add-Result -Check 'sign-in' -Ok $false -Detail 'AUTO_ONTOLOGY_ADMIN_EMAIL / _PASSWORD missing from .env'
} else {
    $signIn = Invoke-Web -Uri "$BaseUrl/api/auth/sign-in/email" -Method Post -Session $session `
        -Headers @{ Origin = $BaseUrl } -Body @{ email = $email; password = $password }
    Add-Result -Check 'sign-in' -Ok ($signIn.StatusCode -eq 200) -Detail "($($signIn.StatusCode), $email)"
    if ($signIn.StatusCode -eq 200) {
        try {
            $sessionInfo = (Invoke-Web -Uri "$BaseUrl/api/auth/get-session" -Session $session).Content | ConvertFrom-Json
            $userId = $sessionInfo.user.id
        } catch {
            Add-Result -Check 'session' -Ok $false -Detail $_.Exception.Message
        }
    }
}

# 4. Pages the browser loads
foreach ($path in @('/login', '/erd', '/exploration')) {
    try {
        $page = Invoke-Web -Uri "$BaseUrl$path" -Session $session
        Add-Result -Check "page $path" -Ok ($page.StatusCode -eq 200) -Detail "($($page.StatusCode))"
    } catch {
        Add-Result -Check "page $path" -Ok $false -Detail $_.Exception.Message
    }
}

# 5. ERD canvas for the first zone (the drawDB-style board)
try {
    # Go through the Next.js permission-gated proxy, like the browser does.
    if (-not $userId) { throw 'no session user id' }
    $zonesResponse = Invoke-Web -Uri "$BaseUrl/api/zones?uid=$userId" -Session $session
    $zonesPayload = $zonesResponse.Content | ConvertFrom-Json
    $zones = if ($zonesPayload.data) { $zonesPayload.data }
             elseif ($zonesPayload.zones) { $zonesPayload.zones }
             else { $zonesPayload }
    $zone = @($zones) | Select-Object -First 1
    if (-not $zone) {
        Add-Result -Check 'erd canvas' -Ok $true -Detail '(no zones yet - nothing to draw)'
    } else {
        $canvas = Invoke-Web -Uri "$BaseUrl/api/erd/canvases/$($zone.id)" -Session $session
        $canvasPayload = $canvas.Content | ConvertFrom-Json
        if ($canvasPayload.data) { $canvasPayload = $canvasPayload.data }
        $nodeCount = @($canvasPayload.nodes).Count
        $relCount = @($canvasPayload.relationships).Count
        Add-Result -Check 'erd canvas' -Ok ($canvas.StatusCode -eq 200) `
            -Detail "(zone '$($zone.name)', $nodeCount tables, $relCount relationships)"
    }
} catch {
    Add-Result -Check 'erd canvas' -Ok $false -Detail $_.Exception.Message
}

$failed = @($results | Where-Object { -not $_.Ok })
Write-Host ''
if ($failed.Count -eq 0) {
    Write-Host "  all $($results.Count) checks passed" -ForegroundColor Green
    Write-Host ''
    exit 0
}
Write-Host "  $($failed.Count) of $($results.Count) checks failed" -ForegroundColor Red
Write-Host ''
exit 1
