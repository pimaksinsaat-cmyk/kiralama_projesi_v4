<#
Kullanim:
  .\scripts\import_db_yedek.ps1

Indirilenler klasorundeki en yeni db_yedek_*.sql dosyasini:
  1) proje kokune db_yedek.sql olarak kopyalar
  2) db_yedekler\db_yedek_yyyyMMdd.sql olarak arsivler
  3) Indirilenler klasorundeki orijinali siler

Ornekler:
  .\scripts\import_db_yedek.ps1
  .\scripts\import_db_yedek.ps1 -WhatIf
  .\scripts\import_db_yedek.ps1 -DownloadsDir "D:\Downloads"
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$DownloadsDir = (Join-Path $env:USERPROFILE "Downloads"),
    [string]$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "=== $Message ===" -ForegroundColor Cyan
}

if (-not (Test-Path -LiteralPath $DownloadsDir)) {
    throw "Indirilenler klasoru bulunamadi: $DownloadsDir"
}

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "Proje koku bulunamadi: $ProjectRoot"
}

Write-Step "Kaynak dosya araniyor"
$candidates = Get-ChildItem -LiteralPath $DownloadsDir -Filter "db_yedek_*.sql" -File -ErrorAction Stop |
    Sort-Object LastWriteTime -Descending

if (-not $candidates -or $candidates.Count -eq 0) {
    throw "Indirilenler klasorunde db_yedek_*.sql dosyasi bulunamadi: $DownloadsDir"
}

$source = $candidates[0]
Write-Host "Secilen kaynak: $($source.FullName)"
Write-Host "Boyut: $([math]::Round($source.Length / 1MB, 2)) MB | Son yazma: $($source.LastWriteTime)"

$archiveDir = Join-Path $ProjectRoot "db_yedekler"
$rootTarget = Join-Path $ProjectRoot "db_yedek.sql"
$today = Get-Date -Format "yyyyMMdd"
$archiveTarget = Join-Path $archiveDir "db_yedek_$today.sql"

if (-not (Test-Path -LiteralPath $archiveDir)) {
    if ($PSCmdlet.ShouldProcess($archiveDir, "Create directory")) {
        New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
        Write-Host "Arsiv klasoru olusturuldu: $archiveDir"
    }
}

Write-Step "Dosyalar kopyalaniyor"
if ($PSCmdlet.ShouldProcess($rootTarget, "Copy from $($source.Name)")) {
    Copy-Item -LiteralPath $source.FullName -Destination $rootTarget -Force
    Write-Host "Kok hedef: $rootTarget"
}

if ($PSCmdlet.ShouldProcess($archiveTarget, "Copy from $($source.Name)")) {
    Copy-Item -LiteralPath $source.FullName -Destination $archiveTarget -Force
    Write-Host "Arsiv hedef: $archiveTarget"
}

Write-Step "Kaynak siliniyor"
if ($PSCmdlet.ShouldProcess($source.FullName, "Remove source file")) {
    Remove-Item -LiteralPath $source.FullName -Force
    Write-Host "Silindi: $($source.FullName)"
}

Write-Step "Ozet"
Write-Host "Kaynak : $($source.FullName)"
Write-Host "Aktif  : $rootTarget"
Write-Host "Arsiv  : $archiveTarget"
Write-Host "Tamamlandi." -ForegroundColor Green
