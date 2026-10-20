$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python -m pip install -r requirements-desktop.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name SciPlan --icon assets/sciplan.ico --add-data "ui;ui" --add-data "assets;assets" main.py
Write-Host "SciPlan.exe 已生成在 dist\\SciPlan.exe"
