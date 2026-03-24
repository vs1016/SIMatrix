$ErrorActionPreference = "Stop"

$root = "E:\Program\RTG"
$bundle = Join-Path $root "exports\RTG.1209-portable"
$pythonSrc = "C:\Python314"
$zip = Join-Path $root "exports\RTG.1209-portable.zip"

if (Test-Path $bundle) {
    Remove-Item $bundle -Recurse -Force
}

New-Item -ItemType Directory -Path $bundle | Out-Null
New-Item -ItemType Directory -Path (Join-Path $bundle "data") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $bundle "data\provider-icons") | Out-Null

Copy-Item -Path (Join-Path $root "app") -Destination $bundle -Recurse
Copy-Item -Path (Join-Path $root "icon") -Destination $bundle -Recurse
Copy-Item -Path (Join-Path $root "README.md") -Destination $bundle
Copy-Item -Path (Join-Path $root "requirements.txt") -Destination $bundle
Copy-Item -Path (Join-Path $root "portable-clear-rtg-data.bat") -Destination $bundle
Copy-Item -Path (Join-Path $root "portable-run-rtg-server.bat") -Destination $bundle
Copy-Item -Path (Join-Path $root "portable-start-rtg-clean.bat") -Destination $bundle
Copy-Item -Path (Join-Path $root "data\provider-icons\*") -Destination (Join-Path $bundle "data\provider-icons") -Force

Write-Host "Copying Python runtime..."
robocopy $pythonSrc (Join-Path $bundle "python") /E /NFL /NDL /NJH /NJS /NP /XD "__pycache__" "Doc" "Tools" "tcl" "Lib\test" "Lib\tkinter" "Lib\idlelib" | Out-Null

Get-ChildItem -Path (Join-Path $bundle "python") -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path (Join-Path $bundle "python") -Recurse -Include "*.pyc" |
    Remove-Item -Force -ErrorAction SilentlyContinue

if (Test-Path $zip) {
    Remove-Item $zip -Force
}

Compress-Archive -Path (Join-Path $bundle "*") -DestinationPath $zip -CompressionLevel Optimal

Write-Host "BUNDLE=$bundle"
Write-Host "ZIP=$zip"
