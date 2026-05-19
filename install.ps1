param(
    [string]$GimpVersion = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Root "divide-scanned-images"
$GimpConfigRoot = Join-Path $env:APPDATA "GIMP"

if ($GimpVersion) {
    $ProfileDir = Join-Path $GimpConfigRoot $GimpVersion
} else {
    $ProfileDir = Get-ChildItem -LiteralPath $GimpConfigRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^3(\.\d+)?$' } |
        Sort-Object {
            [version](
                if ($_.Name -match '^\d+$') {
                    "$($_.Name).0"
                } else {
                    $_.Name
                }
            )
        } -Descending |
        Select-Object -First 1 -ExpandProperty FullName

    if (-not $ProfileDir) {
        $ProfileDir = Join-Path $GimpConfigRoot "3.0"
    }
}

$Target = Join-Path $ProfileDir "plug-ins\divide-scanned-images"

if (-not (Test-Path -LiteralPath $Source)) {
    throw "Cannot find source plug-in folder: $Source"
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Target -Recurse -Force

Write-Host "Installed Divide Scanned Images to:"
Write-Host $Target
Write-Host "Restart GIMP 3.x, then use Filters > Divide Scanned Images..."
