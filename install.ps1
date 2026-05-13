param(
    [switch]$SkillsOnly,
    [switch]$WithHook,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$argsList = @("scripts/install_user.py")
if ($SkillsOnly) { $argsList += "--skills-only" }
if ($WithHook) { $argsList += "--with-hook" }
if ($DryRun) { $argsList += "--dry-run" }
python @argsList
