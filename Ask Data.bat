@echo off
rem Ask questions about the Chinook database. Starts Ollama and stops it again on exit.
title Ask Data
cd /d "%~dp0"
".venv\Scripts\python.exe" -m askdata.launcher
