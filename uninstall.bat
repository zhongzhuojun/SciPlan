@echo off
setlocal
if exist "%LOCALAPPDATA%\SciPlan\SciPlan.exe" del /f /q "%LOCALAPPDATA%\SciPlan\SciPlan.exe"
if exist "%LOCALAPPDATA%\SciPlan" rmdir "%LOCALAPPDATA%\SciPlan" 2>nul
echo SciPlan 已移除。你的数据仍保留在 %%APPDATA%%\ResearchFlow。
pause
endlocal
