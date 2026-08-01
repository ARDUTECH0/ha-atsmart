# -----------------------------------------------------------------------------
#  ha-atsmart  -  ship a new version to HACS.
#
#  Bumps the version in manifest.json, commits + pushes everything, tags it,
#  and creates the GitHub Release HACS actually watches (a pushed commit alone
#  never shows up as an update  -  HACS tracks Releases, not commits).
#
#      .\tools\release.ps1                       1.2.0 -> 1.3.0  (the usual)
#      .\tools\release.ps1 -Minor               1.2.0 -> 1.3.0  (same as above; minor IS the default bump)
#      .\tools\release.ps1 -Major               1.2.0 -> 2.0.0
#      .\tools\release.ps1 -Set 1.4.2            exactly that
#      .\tools\release.ps1 -Notes "..."          skip the notes prompt
#
#  Release notes are the one thing this can't invent for you  -  you'll be
#  prompted for them if -Notes isn't passed. Everything else is automatic.
# -----------------------------------------------------------------------------

param(
  [switch]$Major,
  [switch]$Minor,
  [string]$Set,
  [string]$Notes
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$manifest = Join-Path $root 'custom_components\atsmart\manifest.json'
$script:manifestBackup = $null
$script:tagged = $false
$script:pushedCommit = $false
$script:newTag = $null

function Say($msg, $color = 'Cyan') { Write-Host "  $msg" -ForegroundColor $color }

function Undo {
  # A failed step must not leave a half-shipped release behind: a bumped
  # manifest with nothing to show for it, or a tag with no release.
  if ($script:tagged -and $script:newTag) {
    Say "removing tag $($script:newTag) (the release step failed)" 'DarkGray'
    git tag -d $script:newTag 2>$null | Out-Null
    if ($script:pushedCommit) { git push origin ":refs/tags/$($script:newTag)" 2>$null | Out-Null }
  }
  if ($script:manifestBackup -and -not $script:pushedCommit) {
    [System.IO.File]::WriteAllBytes($manifest, $script:manifestBackup)
    Say "manifest.json put back (nothing was committed)" 'DarkGray'
  }
}

function Die($msg) {
  Undo
  Write-Host ""
  Write-Host "  X  $msg" -ForegroundColor Red
  exit 1
}

trap {
  Undo
  Write-Host ""
  Write-Host "  X  $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}

Write-Host ""
Write-Host "  ha-atsmart - release" -ForegroundColor White
Write-Host "  ---------------------" -ForegroundColor DarkGray

# -- 0. Sanity checks ----------------------------------------------------------
if (-not (Test-Path $manifest)) { Die "manifest.json not found. Run this from the repo." }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  Die "GitHub CLI ('gh') isn't installed or isn't on PATH. Get it from https://cli.github.com"
}
$ghAuth = & gh auth status 2>&1
if ($LASTEXITCODE -ne 0) { Die "gh isn't logged in. Run: gh auth login" }

$branch = (git branch --show-current).Trim()
if (-not $branch) { Die "Not on a branch (detached HEAD?). Check out main first." }

# -- 1. Work out the new version ----------------------------------------------
$script:manifestBackup = [System.IO.File]::ReadAllBytes($manifest)
$json = Get-Content $manifest -Raw | ConvertFrom-Json
$verStr = $json.version
if ($verStr -notmatch '^(\d+)\.(\d+)\.(\d+)$') { Die "Couldn't read a plain X.Y.Z version from manifest.json (got '$verStr')." }
$maj = [int]$Matches[1]; $min = [int]$Matches[2]; $pat = [int]$Matches[3]
$old = "$maj.$min.$pat"

if ($Set) {
  if ($Set -notmatch '^\d+\.\d+\.\d+$') { Die "-Set expects X.Y.Z, e.g. 1.4.2" }
  $new = $Set
} elseif ($Major) {
  $maj++; $min = 0; $pat = 0; $new = "$maj.$min.$pat"
} else {
  # Minor is the default bump here (not patch): almost every release of this
  # integration so far has added or changed a platform, not fixed a typo.
  $min++; $pat = 0; $new = "$maj.$min.$pat"
}

$tag = "v$new"
if (git rev-parse "refs/tags/$tag" 2>$null) { Die "Tag $tag already exists. Pick a different version or delete it first." }

Say "version   $old  ->  $new"

# Rewrite only the version line, leaving formatting/key order exactly as-is  - 
# round-tripping through ConvertTo-Json would reorder keys and rewrite quoting.
$lines = Get-Content $manifest
$out = $lines | ForEach-Object {
  if ($_ -match '^\s*"version":\s*"') { '  "version": "' + $new + '"' } else { $_ }
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($manifest, $out, $utf8NoBom)
Say "manifest.json updated" 'DarkGray'

# -- 2. Release notes ----------------------------------------------------------
if (-not $Notes) {
  Write-Host ""
  Write-Host "  Release notes (Arabic, one line; blank line to finish):" -ForegroundColor Yellow
  $noteLines = @()
  while ($true) {
    $line = Read-Host "  >"
    if ([string]::IsNullOrWhiteSpace($line)) { break }
    $noteLines += $line
  }
  if ($noteLines.Count -eq 0) { Die "No release notes given  -  nothing to publish." }
  $Notes = ($noteLines -join "`n")
}

# -- 3. Show what's about to ship, and confirm ---------------------------------
Write-Host ""
Say "changes to be committed:" 'Yellow'
git add -A
git status --short | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
Write-Host ""
$ok = Read-Host "  Commit, push, tag $tag and publish the release? (y/N)"
if ($ok -notmatch '^[Yy]') { Die "Cancelled." }

# -- 4. Commit + push -----------------------------------------------------------
git commit -m "release: $tag`n`n$Notes" | Out-Null
git push origin $branch
if ($LASTEXITCODE -ne 0) { Die "git push failed  -  see above. The commit is local; fix the push and re-run manually (don't re-run this script, it would try to bump the version again)." }
$script:pushedCommit = $true
Say "pushed to origin/$branch" 'DarkGray'

# -- 5. Tag + push tag ----------------------------------------------------------
git tag -a $tag -m $tag
if ($LASTEXITCODE -ne 0) { Die "git tag failed." }
$script:tagged = $true
$script:newTag = $tag
git push origin $tag
if ($LASTEXITCODE -ne 0) { Die "Pushing the tag failed  -  see above." }
Say "tagged $tag" 'DarkGray'

# -- 6. GitHub Release (this is what HACS actually watches) -------------------
gh release create $tag --title "KUSH SMART $tag" --notes $Notes
if ($LASTEXITCODE -ne 0) { Die "Creating the GitHub Release failed  -  the tag is pushed, so re-run just: gh release create $tag --title `"KUSH SMART $tag`" --notes-file <file>" }

$url = (gh release view $tag --json url -q .url)

Write-Host ""
Write-Host "  PUBLISHED  $tag" -ForegroundColor Green
Write-Host ""
Write-Host "  $url" -ForegroundColor White
Write-Host ""
Write-Host "  Users update from HACS, then restart Home Assistant." -ForegroundColor DarkGray
Write-Host ""

try { Set-Clipboard -Value $url; Say "the release URL is on your clipboard" 'DarkGray' } catch {}
Write-Host ""
