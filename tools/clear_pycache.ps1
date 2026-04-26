$deletedAmount = 0

$rootPath = Join-Path $PSScriptRoot "..\src"
$pycacheFolders = Get-ChildItem -Path $rootPath -Recurse -Directory -Filter "__pycache__"

foreach ($folder in $pycacheFolders) {
    Remove-Item -Path $folder.FullName -Recurse -Force
    $deletedAmount++
}

Write-Host "Deleted $deletedAmount __pycache__ folders"
Read-Host "Press Enter to exit"