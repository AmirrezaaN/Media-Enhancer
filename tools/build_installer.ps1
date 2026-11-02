# Packs dist\MediaEnhancer (made by PyInstaller) into one self-extracting installer:
#   dist\MediaEnhancer-1.0.0-Windows.exe
# (No "setup"/"install" in the name: Windows would then demand admin rights, which extracting doesn't need.)
# Run from the project root after:  .venv\Scripts\pyinstaller desktop\MediaEnhancer.spec --noconfirm
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$app = Join-Path $root "dist\MediaEnhancer"
$out = Join-Path $root "dist\MediaEnhancer-1.0.0-Windows.exe"
$sevenZip = "C:\Program Files\7-Zip\7z.exe"

if (-not (Test-Path (Join-Path $app "MediaEnhancer.exe"))) { throw "Build the app first (dist\MediaEnhancer\MediaEnhancer.exe is missing)." }
if (-not (Test-Path $sevenZip)) { throw "7-Zip is required: $sevenZip" }
if (Test-Path $out) { Remove-Item $out -Force }

# 7z.sfx asks the user where to extract; the folder "MediaEnhancer" is created inside the chosen place.
Push-Location (Split-Path $app)
try {
    & $sevenZip a -t7z -mx=5 -mmt=on "-sfx7z.sfx" $out "MediaEnhancer" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "7-Zip failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
"{0} ({1:N2} GB)" -f $out, ((Get-Item $out).Length / 1GB)
