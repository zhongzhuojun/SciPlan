@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0SciPlan.exe" (
  echo 未找到 SciPlan.exe，请先运行 build_windows.ps1 生成安装包。
  pause
  exit /b 1
)
if not exist "%LOCALAPPDATA%\SciPlan" mkdir "%LOCALAPPDATA%\SciPlan" >nul 2>nul
copy /Y "%~dp0SciPlan.exe" "%LOCALAPPDATA%\SciPlan\SciPlan.exe" >nul
echo SciPlan 已安装到 %LOCALAPPDATA%\SciPlan
start "" "%LOCALAPPDATA%\SciPlan\SciPlan.exe"
endlocal
