@echo off
setlocal
cd /d "%~dp0"
python ..\..\sigilc.py terminator.sigil -o terminator.c
if errorlevel 1 exit /b 1
gcc -std=c99 -Wall -Wextra -Werror -pedantic terminator.c -o terminator.exe
if errorlevel 1 exit /b 1
terminator.exe
