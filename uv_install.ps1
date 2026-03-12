[CmdletBinding()]
param(
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

function Write-Info([string]$Message) {
  if (-not $Quiet) { Write-Host $Message }
}

function Test-UvCommand {
  try {
    return [bool](Get-Command uv -ErrorAction SilentlyContinue)
  } catch {
    return $false
  }
}

function Add-ToProcessPathIfMissing([string[]]$Dirs) {
  $current = $env:Path
  foreach ($d in $Dirs) {
    if ([string]::IsNullOrWhiteSpace($d)) { continue }
    if (-not (Test-Path -LiteralPath $d)) { continue }
    $escaped = [Regex]::Escape($d)
    if ($current -notmatch "(^|;)${escaped}(;|$)") {
      $current = "$d;$current"
    }
  }
  $env:Path = $current
}

function Add-ToUserPathIfMissing([string[]]$Dirs) {
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if ($null -eq $userPath) { $userPath = '' }

  $updated = $userPath
  $changed = $false

  foreach ($d in $Dirs) {
    if ([string]::IsNullOrWhiteSpace($d)) { continue }
    if (-not (Test-Path -LiteralPath $d)) { continue }
    $escaped = [Regex]::Escape($d)
    if ($updated -notmatch "(^|;)${escaped}(;|$)") {
      if ($updated) { $updated = "$d;$updated" } else { $updated = $d }
      $changed = $true
    }
  }

  if ($changed) {
    [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
  }

  return $changed
}

function Try-OfficialInstall {
  try {
    Write-Info 'Running official uv installer in separate PowerShell process...'

    $cmd = 'irm https://astral.sh/uv/install.ps1 | iex'

    $args = @(
      '-NoProfile'
      '-ExecutionPolicy', 'Bypass'
      '-Command', $cmd
    )

    $exe = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell' }

    $p = Start-Process -FilePath $exe -ArgumentList $args -Wait -PassThru

    return ($p.ExitCode -eq 0)
  } catch {
    Write-Info "Official installer failed: $($_.Exception.Message)"
    return $false
  }
}

function Try-PipInstall {
  try {
    $runner = $null
    $py = Get-Command py -ErrorAction SilentlyContinue
    $python = Get-Command python -ErrorAction SilentlyContinue

    if ($py) { $runner = $py.Source }
    elseif ($python) { $runner = $python.Source }

    if (-not $runner) {
      Write-Info 'Python not found.'
      return $false
    }

    & $runner -m pip install --user --upgrade uv

    $userBase = (& $runner -c "import site; print(site.USER_BASE)").Trim()
    if ($userBase) {
      Add-ToProcessPathIfMissing @(Join-Path $userBase 'Scripts')
    }

    return $true
  } catch {
    Write-Info "pip install failed: $($_.Exception.Message)"
    return $false
  }
}

function Try-WingetInstall {
  try {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { return $false }
    & $winget.Source install -e --id Astral.Uv --accept-source-agreements --accept-package-agreements | Out-Null
    return $true
  } catch { return $false }
}

function Try-ScoopInstall {
  try {
    $scoop = Get-Command scoop -ErrorAction SilentlyContinue
    if (-not $scoop) { return $false }
    & $scoop.Source install uv | Out-Null
    return $true
  } catch { return $false }
}

if (Test-UvCommand) {
  Write-Info 'uv already installed.'
  & uv --version
  exit 0
}

$home = $env:USERPROFILE
$candidateDirs = @(
  (Join-Path $home '.local\bin'),
  (Join-Path $home '.cargo\bin'),
  (Join-Path $env:LOCALAPPDATA 'Programs\uv'),
  (Join-Path $env:LOCALAPPDATA 'uv'),
  (Join-Path $env:APPDATA 'uv')
)

Add-ToProcessPathIfMissing $candidateDirs
if (Test-UvCommand) {
  & uv --version
  exit 0
}

$officialOk = Try-OfficialInstall

Add-ToProcessPathIfMissing $candidateDirs
if (Test-UvCommand) {
  & uv --version
  Add-ToUserPathIfMissing $candidateDirs | Out-Null
  exit 0
}

$pipOk = Try-PipInstall

Add-ToProcessPathIfMissing $candidateDirs
if (Test-UvCommand) {
  & uv --version
  Add-ToUserPathIfMissing $candidateDirs | Out-Null
  exit 0
}

$wingetOk = Try-WingetInstall

Add-ToProcessPathIfMissing $candidateDirs
if (Test-UvCommand) {
  & uv --version
  Add-ToUserPathIfMissing $candidateDirs | Out-Null
  exit 0
}

$scoopOk = Try-ScoopInstall

Add-ToProcessPathIfMissing $candidateDirs
if (Test-UvCommand) {
  & uv --version
  Add-ToUserPathIfMissing $candidateDirs | Out-Null
  exit 0
}

Write-Error "uv installation failed. official=$officialOk pip=$pipOk winget=$wingetOk scoop=$scoopOk"
exit 1
