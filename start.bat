@echo off
start /b python "%~dp0web_ui.py"

:: Wait for server to be ready (up to 10 seconds)
for /L %%i in (1,1,20) do (
    powershell -Command "(New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',5000)" 2>nul && goto :ready
    timeout /t 1 /nobreak >nul
)
echo Server failed to start.
exit /b 1

:ready
start "" http://localhost:5000
echo Reddit Scanner running on http://localhost:5000
echo Press Ctrl+C to stop.
:: Keep window open so the background python process stays alive
pause >nul
