$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
python scripts/install_user.py --uninstall
