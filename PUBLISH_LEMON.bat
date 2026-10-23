@echo off
title Publish a new LEMON version
cd /d "%~dp0"
set REPO=7jzzi/lemon-downloader
echo ============================================================
echo   PUBLISH A NEW LEMON VERSION  (build + zip + GitHub release)
echo   Before this: raise APP_VERSION in lemon_app_arcade.pyw.
echo ============================================================
echo.
where gh >nul 2>nul
if errorlevel 1 goto nogh
gh auth status >nul 2>nul
if errorlevel 1 goto noauth
where python >nul 2>nul && (set PY=python) || (set PY=py)
echo Closing LEMON if it is running...
taskkill /F /IM LEMON.exe >nul 2>nul
ping -n 3 127.0.0.1 >nul
if exist "%~dp0exe_build\dist_new" rd /s /q "%~dp0exe_build\dist_new"
echo.
echo [1/4] Building the exe (a few minutes)...
%PY% exe_build\build_exe.py --out "%~dp0exe_build\dist_new"
if errorlevel 1 goto failed
robocopy "%~dp0exe_build\dist_new\LEMON" "%~dp0exe_build\dist\LEMON" /MIR /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul
echo.
echo [2/4] Making the zip...
%PY% exe_build\make_release.py
if errorlevel 1 goto failed
set /p VER=<exe_build\last_release.txt
set ZIP=%~dp0exe_build\LEMON-%VER%.zip
echo.
echo ------------------------------------------------------------
echo   Ready to publish LEMON v%VER% to https://github.com/%REPO%
echo   (1) push your code  (2) create the release v%VER% with the zip
echo   After this, every LEMON user sees the green NEW label.
echo ------------------------------------------------------------
set /p GO=Publish now? Type YES and press Enter (anything else cancels): 
if /I not "%GO%"=="YES" goto cancelled
echo.
echo [3/4] Pushing the code...
git add -A
git commit -m "LEMON v%VER%"
git push
if errorlevel 1 goto pushfailed
echo.
echo [4/4] Creating the GitHub release v%VER% ...
gh release create v%VER% "%ZIP%" --repo %REPO% --title "LEMON v%VER%" --generate-notes
if errorlevel 1 goto failed
echo.
echo ============================================================
echo   DONE. LEMON v%VER% is published. Users get the update when they open LEMON.
echo ============================================================
pause
exit /b 0
:nogh
echo The GitHub tool is missing. Install it once with this command, then run this file again:
echo     winget install GitHub.cli
pause
exit /b 1
:noauth
echo You are not logged in to GitHub yet. Run this once, then run this file again:
echo     gh auth login
pause
exit /b 1
:cancelled
echo Cancelled. Nothing was published. Your new exe and zip are ready in exe_build.
pause
exit /b 0
:pushfailed
echo Pushing the code failed, so the release was NOT created. Scroll up to see why.
pause
exit /b 1
:failed
echo.
echo   Something failed. Scroll up to see the error, or copy the last lines and send them to me.
pause
exit /b 1
