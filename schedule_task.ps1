# Registers a Windows scheduled task that runs the reminders every day at 11:00 AM.
#   powershell -ExecutionPolicy Bypass -File schedule_task.ps1
# Remove it again with:  Unregister-ScheduledTask -TaskName "ABI Hearing WhatsApp Reminders"

$taskName = "ABI Hearing WhatsApp Reminders"
$here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$time     = "11:00"

$action   = New-ScheduledTaskAction -Execute "$here\run_reminders.bat" -WorkingDirectory $here
$trigger  = New-ScheduledTaskTrigger -Daily -At $time
# StartWhenAvailable: if the PC was off/asleep at 11:00, run as soon as it is back.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
# Runs as the current user, only while logged in, so Chrome can open visibly.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Scheduled '$taskName' daily at $time."
