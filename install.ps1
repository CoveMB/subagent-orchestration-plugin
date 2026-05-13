param(
    [ValidateSet("user", "project")]
    [string]$Scope = "user",
    [switch]$SkillsOnly,
    [switch]$WithHook,
    [switch]$DryRun,
    [string]$RepoRoot,
    [string]$FromVendor,
    [switch]$ActivateGate,
    [switch]$LinkSkills,
    [switch]$WithProjectAgents,
    [switch]$AppendProjectAgentsMd,
    [switch]$WithRepoMarketplace,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$argsList = @("scripts/install_user.py", "--scope", $Scope)
if ($SkillsOnly) { $argsList += "--skills-only" }
if ($WithHook) { $argsList += "--with-hook" }
if ($DryRun) { $argsList += "--dry-run" }
if ($RepoRoot) { $argsList += @("--repo-root", $RepoRoot) }
if ($FromVendor) { $argsList += @("--from-vendor", $FromVendor) }
if ($ActivateGate) { $argsList += "--activate-gate" }
if ($LinkSkills) { $argsList += "--link-skills" }
if ($WithProjectAgents) { $argsList += "--with-project-agents" }
if ($AppendProjectAgentsMd) { $argsList += "--append-project-agents-md" }
if ($WithRepoMarketplace) { $argsList += "--with-repo-marketplace" }
if ($Uninstall) { $argsList += "--uninstall" }
python @argsList
