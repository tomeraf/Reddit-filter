@echo off
:: Kill only the process listening on port 5000 (the scanner)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
echo Stopped.
