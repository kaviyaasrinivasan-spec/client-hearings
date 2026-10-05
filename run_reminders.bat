@echo off
rem Called by the scheduled task at 11:00 AM every day.
cd /d "%~dp0"
python send_reminders.py
