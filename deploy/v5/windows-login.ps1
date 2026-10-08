$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$image = 'aldi-watcher-v5:windows-login'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Bitte zuerst Docker Desktop installieren und starten.'
    exit 1
}
$engine = & docker info --format '{{.OSType}}' 2>$null
if ($LASTEXITCODE -ne 0 -or "$engine".Trim() -ne 'linux') {
    Write-Host 'Docker Desktop muss laufen und Linux-Container verwenden.'
    exit 1
}

Write-Host 'Der Test meldet sich einmal an. Er bucht kein Datenvolumen.'
& docker build -f (Join-Path $PSScriptRoot 'Dockerfile') -t $image $repoRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Image-Build fehlgeschlagen. Zugangsdaten wurden noch nicht abgefragt.'
    exit 1
}

$number = (Read-Host 'ALDI-TALK-Rufnummer').Trim()
if (-not $number) { throw 'Eine Rufnummer ist erforderlich.' }
$password = Read-Host 'ALDI-TALK-Passwort (Eingabe bleibt verborgen)' -AsSecureString
if ($password.Length -eq 0) {
    $password.Dispose()
    throw 'Ein Passwort ist erforderlich.'
}
$oldUser = [Environment]::GetEnvironmentVariable('ALDI_USER', 'Process')
$oldPass = [Environment]::GetEnvironmentVariable('ALDI_PASS', 'Process')
$bstr = [IntPtr]::Zero
$probeExit = 1
try {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    [Environment]::SetEnvironmentVariable('ALDI_USER', $number, 'Process')
    [Environment]::SetEnvironmentVariable('ALDI_PASS',
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr), 'Process')
    & docker run --rm --pull=never --env ALDI_USER --env ALDI_PASS `
        --env DRY_RUN=true --env AUTO_BOOK_ENABLED=false `
        $image python -m lite login-probe
    $probeExit = $LASTEXITCODE
} finally {
    [Environment]::SetEnvironmentVariable('ALDI_USER', $oldUser, 'Process')
    [Environment]::SetEnvironmentVariable('ALDI_PASS', $oldPass, 'Process')
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $password.Dispose()
}
if ($probeExit -eq 0) {
    Write-Host 'Login bestaetigt. Mailtrigger und Gratisangebot sind noch einzurichten.'
} else {
    Write-Host 'Login nicht bestaetigt. Bitte nur die angezeigte error_class mitteilen.'
}
exit $probeExit
