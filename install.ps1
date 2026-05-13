param(
    [switch]$Plugin,
    [switch]$PatchConfig,
    [switch]$NoPatchConfig
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$argsList = @("scripts/install_user.py")
if ($Plugin) { $argsList += "--plugin" }
if ($PatchConfig) { $argsList += "--patch-config" }
if ($NoPatchConfig) { $argsList += "--no-patch-config" }
python @argsList
