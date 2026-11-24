<#
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0

.SYNOPSIS
    Start All-Ontology against the PostgreSQL database configured in .env.

.DESCRIPTION
    Thin convenience wrapper around dev_tools/start-dev.ps1. It connects to
    POSTGRES_* from .env and never starts Docker or a database container.

.EXAMPLE
    .\start.ps1

.EXAMPLE
    .\start.ps1 -Force
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoFrontend,
    [switch]$NoIngestion
)

$ErrorActionPreference = 'Stop'
$scriptArgs = @()
foreach ($name in 'Force', 'NoFrontend', 'NoIngestion') {
    if ((Get-Variable -Name $name -ValueOnly)) { $scriptArgs += "-$name" }
}

& (Join-Path $PSScriptRoot 'dev_tools\start-dev.ps1') @scriptArgs
