$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'Сначала выполните setup.ps1.' }
& .\.venv\Scripts\python.exe -m linklane --open
