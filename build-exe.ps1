$ErrorActionPreference = "Stop"

$root = "E:\Program\RTG"
$distRoot = Join-Path $root "exports\RTG.1209-exe"
$workRoot = Join-Path $root "tmp\pyinstaller"
$specRoot = Join-Path $root "tmp\pyinstaller-spec"
$zipPath = Join-Path $root "exports\RTG.1209-exe.zip"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python was not found in PATH"
}

python -m pip install --upgrade pyinstaller

if (Test-Path $distRoot) {
    Remove-Item $distRoot -Recurse -Force
}
if (Test-Path $workRoot) {
    Remove-Item $workRoot -Recurse -Force
}
if (Test-Path $specRoot) {
    Remove-Item $specRoot -Recurse -Force
}
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

New-Item -ItemType Directory -Path $distRoot | Out-Null
New-Item -ItemType Directory -Path $workRoot | Out-Null
New-Item -ItemType Directory -Path $specRoot | Out-Null

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name RTG.1209 `
    --distpath $distRoot `
    --workpath $workRoot `
    --specpath $specRoot `
    --add-data "$root\app\templates;app\templates" `
    --add-data "$root\app\static;app\static" `
    --add-data "$root\icon;icon" `
    --add-data "$root\data\provider-icons;data\provider-icons" `
    "$root\launcher.py"

Compress-Archive -Path (Join-Path $distRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "EXE_DIR=$distRoot"
Write-Host "ZIP=$zipPath"
