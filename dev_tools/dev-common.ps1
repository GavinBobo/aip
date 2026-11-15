<#
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0

Shared helpers for the Windows PowerShell developer scripts
(`start-dev.ps1` / `stop-dev.ps1`). Dot-source it, do not run it directly.
#>

$DevPorts = @(3000, 3001, 3002)

function Resolve-RepoRoot {
    param([Parameter(Mandatory)][string]$ScriptDir)
    return (Resolve-Path -LiteralPath (Join-Path $ScriptDir '..')).Path
}

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  ok  $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  !!  $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  xx  $Message" -ForegroundColor Red
}

function Get-HttpStatus {
    <# Return the HTTP status code for a URL, or 0 when nothing is listening. #>
    param([Parameter(Mandatory)][string]$Url, [int]$TimeoutSec = 10)
    $raw = & curl.exe -s -o NUL -w '%{http_code}' --max-time $TimeoutSec $Url 2>$null
    $code = 0
    if ([int]::TryParse((("$raw") -replace '\D', ''), [ref]$code)) { return $code }
    return 0
}

function Wait-HttpStatus {
    <#
    Poll a URL until it returns one of the accepted status codes.
    When -ProcessId is supplied, give up as soon as that process exits.
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [int]$TimeoutSec = 120,
        [int[]]$Accept = @(200),
        [int]$ProcessId = 0
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ($ProcessId -gt 0 -and -not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            return $false
        }
        if ($Accept -contains (Get-HttpStatus -Url $Url)) { return $true }
        Start-Sleep -Milliseconds 1000
    }
    return $false
}

function Get-SelfAncestors {
    <# Process ids of this shell and everything that launched it. #>
    $set = New-Object 'System.Collections.Generic.HashSet[int]'
    $cur = $PID
    for ($i = 0; $i -lt 12; $i++) {
        [void]$set.Add($cur)
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
        if (-not $proc) { break }
        $next = [int]$proc.ParentProcessId
        if ($next -le 4 -or $next -eq $cur) { break }
        $cur = $next
    }
    return $set
}

function Test-ProjectCmdLine {
    <#
    True when a command line plausibly belongs to this repository's dev stack.
    Deliberately narrow: a foreign app that happens to sit on port 3000 must not match.
    #>
    param([string]$CommandLine, [string]$RepoRoot)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    $cl = ($CommandLine -replace '/', '\').ToLowerInvariant()
    $root = (($RepoRoot -replace '/', '\').ToLowerInvariant()).TrimEnd('\') + '\'
    if ($cl.Contains($root)) { return $true }
    foreach ($needle in @('uvicorn', 'auto_ontology', 'auto-ontology')) {
        if ($cl.Contains($needle)) { return $true }
    }
    return $false
}

function Stop-ProcessTree {
    <# Kill a process and every descendant; descendants first. #>
    param([Parameter(Mandatory)][int]$RootProcessId)
    $all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
    $children = @{}
    foreach ($p in $all) {
        $parent = [int]$p.ParentProcessId
        if (-not $children.ContainsKey($parent)) { $children[$parent] = New-Object 'System.Collections.Generic.List[int]' }
        $children[$parent].Add([int]$p.ProcessId)
    }
    $order = New-Object 'System.Collections.Generic.List[int]'
    $queue = New-Object 'System.Collections.Generic.Queue[int]'
    $queue.Enqueue($RootProcessId)
    while ($queue.Count -gt 0) {
        $cur = $queue.Dequeue()
        if ($order.Contains($cur)) { continue }
        $order.Add($cur)
        if ($children.ContainsKey($cur)) {
            foreach ($child in $children[$cur]) { $queue.Enqueue($child) }
        }
    }
    for ($i = $order.Count - 1; $i -ge 0; $i--) {
        Stop-Process -Id $order[$i] -Force -ErrorAction SilentlyContinue
    }
}

function Get-ProjectAnchor {
    <#
    Climb from a listener to the outermost ancestor that still looks like part of
    this project (e.g. `uvicorn --reload` parent, `uv` wrapper). Killing from the
    anchor stops the reloader from respawning the child.
    #>
    param([Parameter(Mandatory)][int]$ProcessId, [Parameter(Mandatory)][string]$RepoRoot)
    $walkable = @('python.exe', 'pythonw.exe', 'uv.exe', 'node.exe', 'cmd.exe', 'conhost.exe')
    $ancestors = Get-SelfAncestors
    $anchor = $ProcessId
    $cur = $ProcessId
    for ($i = 0; $i -lt 6; $i++) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
        if (-not $proc) { break }
        if (-not (Test-ProjectCmdLine -CommandLine $proc.CommandLine -RepoRoot $RepoRoot)) { break }
        if ($ancestors.Contains([int]$proc.ProcessId)) { break }
        $anchor = [int]$proc.ProcessId
        if ($walkable -notcontains $proc.Name) { break }
        $next = [int]$proc.ParentProcessId
        if ($next -le 4 -or $next -eq $cur) { break }
        $cur = $next
    }
    return $anchor
}

function Test-ProcessAncestor {
    <# True when $AncestorId is a (transitive) parent of $DescendantId. #>
    param([Parameter(Mandatory)][int]$AncestorId, [Parameter(Mandatory)][int]$DescendantId)
    $cur = $DescendantId
    for ($i = 0; $i -lt 12; $i++) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
        if (-not $proc) { return $false }
        $parent = [int]$proc.ParentProcessId
        if ($parent -le 4) { return $false }
        if ($parent -eq $AncestorId) { return $true }
        $cur = $parent
    }
    return $false
}

function Resolve-ComponentPid {
    <#
    Which pid should be recorded for a component that is already running?
    Prefer the pid we started it with last time (when it is still an ancestor of
    the current port owner), otherwise fall back to the project anchor.
    #>
    param(
        [Parameter(Mandatory)][int]$OwnerPid,
        [int]$RecordedPid = 0,
        [Parameter(Mandatory)][string]$RepoRoot
    )
    if ($RecordedPid -gt 0 -and (Test-ProcessAncestor -AncestorId $RecordedPid -DescendantId $OwnerPid)) {
        return $RecordedPid
    }
    return (Get-ProjectAnchor -ProcessId $OwnerPid -RepoRoot $RepoRoot)
}

function Get-PortOwner {
    <# Process id + process object owning a listening port, or $null. #>
    param([Parameter(Mandatory)][int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    return [pscustomobject]@{ Port = $Port; Pid = [int]$proc.ProcessId; Name = $proc.Name; CommandLine = $proc.CommandLine }
}

function Clear-PortListeners {
    <# Stop stale dev-stack listeners on the given ports. Returns the ports that were freed. #>
    param([Parameter(Mandatory)][string]$RepoRoot, [int[]]$Ports = $DevPorts)
    $freed = @()
    foreach ($port in $Ports) {
        $owner = Get-PortOwner -Port $port
        while ($owner) {
            if (-not (Test-ProjectCmdLine -CommandLine $owner.CommandLine -RepoRoot $RepoRoot)) {
                Write-Warn "port $port is held by pid $($owner.Pid) ($($owner.Name)) which is not part of this repo - leaving it alone"
                break
            }
            $anchor = Get-ProjectAnchor -ProcessId $owner.Pid -RepoRoot $RepoRoot
            Write-Step "stopping stale dev process on port $port (pid $anchor)"
            Stop-ProcessTree -RootProcessId $anchor
            $freed += $port
            Start-Sleep -Milliseconds 500
            $owner = Get-PortOwner -Port $port
            if ($owner -and ($freed -contains $port) -and ($owner.Pid -eq $anchor)) { break }
        }
    }
    return $freed
}

function Start-LoggedProcess {
    <# Start a hidden background process with stdout/stderr captured under <LogDir>. #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$LogDir
    )
    $outLog = Join-Path $LogDir "$Name.log"
    $errLog = Join-Path $LogDir "$Name.err.log"
    foreach ($f in @($outLog, $errLog)) {
        if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
    }
    $proc = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    return [pscustomobject]@{
        Name    = $Name
        Pid     = $proc.Id
        StdOut  = $outLog
        StdErr  = $errLog
    }
}

function Show-LogTail {
    param([string]$Path, [int]$Lines = 25)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $tail = Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue
    if (-not $tail) { return }
    Write-Host "  --- $Path (last $Lines lines) ---" -ForegroundColor DarkGray
    foreach ($line in $tail) { Write-Host "  $line" -ForegroundColor DarkGray }
}

function Get-DotEnvValue {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Key)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*=\s*(.*)$'
    foreach ($line in Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue) {
        if ($line -match $pattern) {
            $value = $matches[1].Trim()
            if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return $null
}

function Test-DockerEngine {
    & docker info --format '{{.ServerVersion}}' *> $null
    return ($LASTEXITCODE -eq 0)
}
