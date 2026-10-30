@echo off
call "%~dp0Build_SelfContained.bat" %*
exit /b %errorlevel%
