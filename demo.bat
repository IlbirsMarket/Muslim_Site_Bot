@echo off
rem Демо-версия «Муслим» только на этом компьютере. "demo.bat new" — пересоздать демо-базу.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo.ps1" %1
