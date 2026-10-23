# Preparation only: no provider actor, credential arguments or task overwrite.
[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$RepoPath,
    [Parameter(Mandatory=$true)][string]$LedgerPath,
    [string]$TaskName = 'ALDI-Watcher-MailSensor'
)
$ErrorActionPreference = 'Stop'
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$LedgerPath = (Resolve-Path -LiteralPath $LedgerPath).Path
$ScriptPath = Join-Path $RepoPath 'mail_monitor_daemon.py'
if (!(Test-Path -LiteralPath $ScriptPath -PathType Leaf)) { throw 'Sensor script missing' }
if (!(Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Python executable missing' }
if (!(Test-Path -LiteralPath $LedgerPath -PathType Leaf)) { throw 'Existing sensor ledger required' }
$Current = [Security.Principal.WindowsIdentity]::GetCurrent()
$Allowed = @($Current.User.Value, 'S-1-5-18', 'S-1-5-32-544')
$StateDirectory = Split-Path -Parent $LedgerPath
foreach ($Target in @($StateDirectory, $LedgerPath)) {
    $Item = Get-Item -LiteralPath $Target
    if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point rejected' }
    $Acl = Get-Acl -LiteralPath $Target
    if (!$Acl.AreAccessRulesProtected) { throw 'Dedicated private state directory/file ACL required' }
    foreach ($Rule in $Acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($Rule.AccessControlType -eq 'Allow' -and $Rule.IdentityReference.Value -notin $Allowed) {
            throw 'State ACL grants another identity access'
        }
    }
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw 'Existing task preserved; inspect before replacing'
}
$ReportPath = Join-Path $StateDirectory 'mail-sensor-report.json'
$Arguments = '-u "{0}" --ledger "{1}" --report "{2}"' -f $ScriptPath, $LedgerPath, $ReportPath
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $Arguments -WorkingDirectory $RepoPath
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Current.Name
$Principal = New-ScheduledTaskPrincipal -UserId $Current.Name -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
if ($PSCmdlet.ShouldProcess($TaskName, 'Register current-user, read-only IMAP sensor at logon')) {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
        -Principal $Principal -Settings $Settings | Out-Null
}
# Does not start the task, set secrets, enable IMAP, create a ledger or book data.
