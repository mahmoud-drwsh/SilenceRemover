@echo off
setlocal enabledelayedexpansion

echo ========================================
echo Add PWSH Directory to User PATH
echo ========================================
echo.

REM Get the script's directory (project root)
set "SCRIPT_DIR=%~dp0"
REM Remove trailing backslash
set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"

REM Set the PWSH directory path
set "PWSH_DIR=!SCRIPT_DIR!\pwsh"

echo PWSH directory: %PWSH_DIR%
echo.

REM Check if pwsh directory exists
if not exist "!PWSH_DIR!" (
    echo ERROR: The pwsh directory does not exist at: !PWSH_DIR!
    echo.
    pause
    exit /b 1
)
echo.

REM Display current PATH
echo Current User PATH variable:
echo ----------------------------------------
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USER_PATH=%%b"
if defined USER_PATH (
    echo %USER_PATH%
) else (
    echo (User PATH is empty or not set)
)
echo ----------------------------------------
echo.

REM Check if pwsh directory is already in PATH
set "ALREADY_IN_PATH=0"
if defined USER_PATH (
    echo %USER_PATH% | findstr /C:"%PWSH_DIR%" >nul
    if !errorlevel! equ 0 (
        set "ALREADY_IN_PATH=1"
        echo WARNING: The pwsh directory is already in your PATH!
        echo.
    )
)

if !ALREADY_IN_PATH! equ 0 (
    echo The pwsh directory will be added to your User PATH.
    echo.
    echo NOTE: You will need to restart any open command prompts
    echo       or applications for the changes to take effect.
    echo.
)

REM Ask for confirmation
set /p CONFIRM="Do you want to proceed? (Y/N): "
if /i not "!CONFIRM!"=="Y" (
    echo Operation cancelled.
    pause
    exit /b 0
)

if !ALREADY_IN_PATH! equ 1 (
    echo The directory is already in PATH. No changes needed.
    pause
    exit /b 0
)

REM Add pwsh directory to user PATH
if defined USER_PATH (
    setx PATH "!USER_PATH!;%PWSH_DIR%"
) else (
    setx PATH "%PWSH_DIR%"
)

if !errorlevel! equ 0 (
    echo.
    echo SUCCESS: The pwsh directory has been added to your User PATH.
    echo.
    echo Please restart your command prompt or terminal for the changes to take effect.
) else (
    echo.
    echo ERROR: Failed to update PATH. Please run this script as Administrator if needed.
)

echo.
pause

