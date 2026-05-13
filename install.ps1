param(
    [switch]$Plugin,
    [switch]$PatchConfig
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$argsList = @("scripts/install_user.py")
if ($Plugin) { $argsList += "--plugin" }
if ($PatchConfig) { $argsList += "--patch-config" }
python @argsList
