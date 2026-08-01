@echo off
REM Double-click this to ship a new version to HACS.
REM It bumps the version, commits, pushes, tags, and publishes the GitHub
REM Release HACS actually watches for updates.
REM
REM   release.bat                the usual (minor bump)
REM   release.bat -Major         1.3.0 -> 2.0.0
REM   release.bat -Set 1.4.2     exactly that
REM
REM The window stays open at the end so you can read the result.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\release.ps1" %*
echo.
pause
