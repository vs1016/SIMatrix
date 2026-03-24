$ErrorActionPreference = "Stop"

$root = "E:\Program\RTG"
$exportRoot = "E:\Program\1-ProgramExports"
$appName = "RTG-OneClick"
$distRoot = Join-Path $exportRoot $appName
$zipPath = Join-Path $exportRoot "$appName.zip"
$stageRoot = Join-Path $root "tmp\oneclick-stage"
$payloadRoot = Join-Path $stageRoot "payload"
$workRoot = Join-Path $root "tmp\pyinstaller-oneclick"
$specRoot = Join-Path $root "tmp\pyinstaller-oneclick-spec"
$pythonSrc = "C:\Python314"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$versionFile = Join-Path $payloadRoot "payload.version"

if (-not (Test-Path $pythonSrc)) {
    throw "Bundled Python runtime was not found at $pythonSrc"
}

foreach ($path in @($distRoot, $stageRoot, $workRoot, $specRoot, $zipPath)) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
    }
}

New-Item -ItemType Directory -Path $exportRoot -Force | Out-Null
New-Item -ItemType Directory -Path $payloadRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $payloadRoot "data") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $payloadRoot "data\provider-icons") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $payloadRoot "wheelhouse") -Force | Out-Null

Copy-Item -Path (Join-Path $root "app") -Destination $payloadRoot -Recurse
Copy-Item -Path (Join-Path $root "icon") -Destination $payloadRoot -Recurse

foreach ($fileName in @(
    "launcher.py",
    "requirements.txt",
    "README.md",
    "0-ensure-rtg-env.bat",
    "1-clear-rtg-data.bat",
    "2-start-rtg-service.bat",
    "123-clean-start-open-rtg.bat",
    "start-rtg.bat"
)) {
    Copy-Item -Path (Join-Path $root $fileName) -Destination $payloadRoot
}

foreach ($dataFile in @(
    "destination-catalog.json",
    "provider-catalog.json",
    "provider-page-index.json"
)) {
    $sourcePath = Join-Path $root "data\$dataFile"
    if (Test-Path $sourcePath) {
        Copy-Item -Path $sourcePath -Destination (Join-Path $payloadRoot "data")
    }
}

$providerIconsSource = Join-Path $root "data\provider-icons\*"
if (Test-Path (Join-Path $root "data\provider-icons")) {
    Copy-Item -Path $providerIconsSource -Destination (Join-Path $payloadRoot "data\provider-icons") -Force
}

Write-Host "[RTG-BUILD] Downloading offline wheelhouse..."
python -m pip download --only-binary=:all: --dest (Join-Path $payloadRoot "wheelhouse") -r (Join-Path $root "requirements.txt")

Write-Host "[RTG-BUILD] Copying bundled Python runtime..."
robocopy $pythonSrc (Join-Path $payloadRoot "python") /E /NFL /NDL /NJH /NJS /NP /XD "__pycache__" "Doc" "Tools" "Lib\test" "Lib\tkinter" "Lib\idlelib" | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed while copying the Python runtime"
}

Get-ChildItem -Path (Join-Path $payloadRoot "python") -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path (Join-Path $payloadRoot "python") -Recurse -Include "*.pyc" |
    Remove-Item -Force -ErrorAction SilentlyContinue

Set-Content -Path $versionFile -Value $timestamp -Encoding UTF8

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name $appName `
    --distpath $exportRoot `
    --workpath $workRoot `
    --specpath $specRoot `
    --add-data "$payloadRoot;payload" `
    "$root\oneclick_launcher.py"

Compress-Archive -Path (Join-Path $distRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "EXE_DIR=$distRoot"
Write-Host "EXE_PATH=$(Join-Path $distRoot "$appName.exe")"
Write-Host "ZIP=$zipPath"
