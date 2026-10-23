# Installs the ableton-mcp-max Remote Script into every Ableton Live install on
# Windows (Live 11 and 12), backing up any existing AbletonMCP script.
#
# Windows counterpart of install_remote_script.sh. Live installs live under
# C:\ProgramData\Ableton\<edition>\Resources\MIDI Remote Scripts. To target one
# install, pass its root:
#   powershell -File scripts\install_remote_script.ps1 -LiveRoot "C:\ProgramData\Ableton\Live 12 Suite"
param([string]$LiveRoot = '')

$ErrorActionPreference = 'Stop'
$Src = Join-Path $PSScriptRoot '..\remote_script\AbletonMCP\__init__.py'
$Src = (Resolve-Path $Src).Path
# Backups go OUTSIDE the Remote Scripts dir: Live imports every subfolder there
# as a control surface, and "AbletonMCP.bak.<ts>" is an invalid module name.
$BackupDir = Join-Path $env:USERPROFILE '.ableton-mcp-rs-backups'

if ($LiveRoot) {
    $roots = @($LiveRoot)
} else {
    $roots = @(Get-ChildItem 'C:\ProgramData\Ableton' -Directory -Filter 'Live*' -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName })
}

$installed = 0
foreach ($root in $roots) {
    $rs = Join-Path $root 'Resources\MIDI Remote Scripts'
    if (-not (Test-Path $rs)) { Write-Host "SKIP: no MIDI Remote Scripts dir in $root"; continue }
    $dest = Join-Path $rs 'AbletonMCP'
    Write-Host ("=== {0} ===" -f (Split-Path $root -Leaf))
    if (Test-Path $dest) {
        New-Item -ItemType Directory -Force $BackupDir | Out-Null
        $bk = Join-Path $BackupDir ("AbletonMCP.{0}.bak.{1}" -f (Split-Path $root -Leaf), (Get-Date -Format yyyyMMdd-HHmmss))
        Write-Host "Backing up existing $dest -> $bk"
        Copy-Item -LiteralPath $dest -Destination $bk -Recurse
    }
    Write-Host "Installing Remote Script -> $dest"
    New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item -LiteralPath $Src -Destination (Join-Path $dest '__init__.py') -Force
    # Drop stale bytecode so Live recompiles from the new source.
    $cache = Join-Path $dest '__pycache__'
    if (Test-Path $cache) { Remove-Item -LiteralPath $cache -Recurse -Force }
    $installed++
}

if ($installed -eq 0) {
    Write-Error 'No Ableton Live install found under C:\ProgramData\Ableton with a MIDI Remote Scripts dir.'
    exit 1
}
Write-Host ""
Write-Host "Done ($installed install(s)). Restart Ableton Live, then select 'AbletonMCP' as a Control Surface (Input/Output = None)."
exit 0
