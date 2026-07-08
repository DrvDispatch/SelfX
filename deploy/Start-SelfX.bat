@echo off
title SelfX
echo Starting SelfX in WSL2...
wsl -d Ubuntu -u root -e bash /root/selfx-start.sh
echo.
echo Open the http URL shown above in your browser (admin / your password).
timeout /t 10
