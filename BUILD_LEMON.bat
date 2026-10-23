@echo off
title Build LEMON.exe
cd /d "%~dp0"
echo ============================================
echo   Building LEMON.exe from lemon_app_arcade.pyw
echo ============================================
echo.
echo Closing LEMON if it is running...
taskkill /F /IM LEMON.exe >nul 2>nul
ping -n 3 127.0.0.1 >nul
where python >nul 2>nul && (set PY=python) || (set PY=py)
rem Tell the exe where its source is: pressing the update lemon later rebuilds from these files.
for /f "delims=" %%P in ('%PY% -c "import sys;print(sys.executable)"') do set PYEXE=%%P
if not exist "%LOCALAPPDATA%\LEMON" mkdir "%LOCALAPPDATA%\LEMON"
(echo %~dp0& echo %PYEXE%) > "%LOCALAPPDATA%\LEMON\dev_source.txt"
rem Build into a scratch folder first (PyInstaller wipes its output folder, which fails if something holds it open).
if exist "%~dp0exe_build\dist_new" rd /s /q "%~dp0exe_build\dist_new"
%PY% exe_build\build_exe.py --out "%~dp0exe_build\dist_new"
if errorlevel 1 goto failed
echo.
echo Copying the new build into exe_build\dist\LEMON ...
robocopy "%~dp0exe_build\dist_new\LEMON" "%~dp0exe_build\dist\LEMON" /MIR /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto copyfailed
echo.
echo Making the release zip for GitHub...
%PY% exe_build\make_release.py
echo.
echo ============================================
echo   DONE. Your new exe: %~dp0exe_build\dist\LEMON\LEMON.exe
echo   Release zip (for GitHub, when you are ready): see the ZIP line above
echo ============================================
pause
exit /b 0
:copyfailed
echo.
echo   Couldn't copy into exe_build\dist\LEMON (something holds it open).
echo   The new build is ready here instead: %~dp0exe_build\dist_new\LEMON\LEMON.exe
pause
exit /b 0
:failed
echo.
echo   The build failed. Scroll up to see the error,
echo   or copy the last lines and send them to me.
pause
exit /b 1
