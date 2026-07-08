@echo off
title SelfX
wsl -d Ubuntu -u root -e bash /root/selfx-stop.sh
timeout /t 4
