<#
Kullanim:
  .\scripts\restore_db_yedek.ps1

Varsayilan olarak db_yedek.sql dosyasini kiralama_veritabani icindeki
kiralama_db veritabanina aktarir. Restore oncesi backups/ altina yedek alir,
kiralama_web konteynerini gecici durdurur ve is bitince tekrar baslatir.

Ornekler:
  .\scripts\restore_db_yedek.ps1 -SqlFile .\db_yedek.sql
  .\scripts\restore_db_yedek.ps1 -SqlFile .\firma_data.sql -NoStopWeb
  .\scripts\restore_db_yedek.ps1 -SkipBackup

db_yedek.utf8.sql Turkce karakterleri bozuk/mojibake icerebilir; script bu
dosyayi varsayilan olarak engeller. Bilerek kullanmak icin:
  .\scripts\restore_db_yedek.ps1 -SqlFile .\db_yedek.utf8.sql -AllowMojibakeFile
#>

param(
    [string]$SqlFile = "db_yedek.sql",
    [string]$DbContainer = "kiralama_veritabani",
    [string]$WebContainer = "kiralama_web",
    [string]$DbService = "db",
    [string]$WebService = "web",
    [string]$DbName = "kiralama_db",
    [string]$DbUser = "postgres",
    [string]$BackupDir = "backups",
    [switch]$NoStopWeb,
    [switch]$SkipBackup,
    [switch]$AllowMojibakeFile
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "=== $Message ===" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [string]$Label,
        [scriptblock]$Command
    )

    Write-Step $Label
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label basarisiz oldu. ExitCode=$LASTEXITCODE"
    }
}

function Get-ContainerRunningState([string]$ContainerName) {
    $state = docker inspect -f '{{.State.Running}}' $ContainerName 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "$ContainerName konteyneri bulunamadi."
    }
    return ($state -eq "true")
}

function Test-ContainerExists([string]$ContainerName) {
    $name = docker ps -a --filter "name=^/$ContainerName$" --format "{{.Names}}"
    if ($LASTEXITCODE -ne 0) {
        throw "Docker konteyner listesi okunamadi. ExitCode=$LASTEXITCODE"
    }
    return ($name -eq $ContainerName)
}

function Start-ComposeService([string]$ServiceName) {
    docker compose up -d $ServiceName
    if ($LASTEXITCODE -ne 0) {
        throw "$ServiceName servisi docker compose ile baslatilamadi. ExitCode=$LASTEXITCODE"
    }
}

function Stop-ContainerIfRunning([string]$ContainerName) {
    Write-Step "$ContainerName konteyneri kontrol ediliyor"
    if (-not (Test-ContainerExists $ContainerName)) {
        Write-Host "$ContainerName bulunamadi; restore sonunda docker compose ile olusturulacak." -ForegroundColor Yellow
        return
    }

    if (Get-ContainerRunningState $ContainerName) {
        docker stop $ContainerName
        if ($LASTEXITCODE -ne 0) {
            throw "$ContainerName konteyneri durdurulamadi. ExitCode=$LASTEXITCODE"
        }
        Write-Host "$ContainerName durduruldu." -ForegroundColor Green
    }
    else {
        Write-Host "$ContainerName zaten calismiyor." -ForegroundColor Yellow
    }
}

function Start-Or-Restart-Container([string]$ContainerName, [string]$ServiceName) {
    Write-Step "$ContainerName konteyneri calistiriliyor"
    if (-not (Test-ContainerExists $ContainerName)) {
        Write-Host "$ContainerName bulunamadi; docker compose ile olusturuluyor." -ForegroundColor Yellow
        Start-ComposeService $ServiceName
        return
    }

    if (Get-ContainerRunningState $ContainerName) {
        docker restart $ContainerName
        if ($LASTEXITCODE -ne 0) {
            throw "$ContainerName konteyneri yeniden baslatilamadi. ExitCode=$LASTEXITCODE"
        }
        Write-Host "$ContainerName yeniden baslatildi." -ForegroundColor Green
    }
    else {
        docker start $ContainerName
        if ($LASTEXITCODE -ne 0) {
            throw "$ContainerName konteyneri baslatilamadi. ExitCode=$LASTEXITCODE"
        }
        Write-Host "$ContainerName baslatildi." -ForegroundColor Green
    }
}

function Start-ContainerIfStopped([string]$ContainerName, [string]$ServiceName) {
    Write-Step "$ContainerName konteyneri kontrol ediliyor"
    if (-not (Test-ContainerExists $ContainerName)) {
        Write-Host "$ContainerName bulunamadi; docker compose ile olusturuluyor." -ForegroundColor Yellow
        Start-ComposeService $ServiceName
        return
    }

    if (Get-ContainerRunningState $ContainerName) {
        Write-Host "$ContainerName calisiyor." -ForegroundColor Green
    }
    else {
        docker start $ContainerName
        if ($LASTEXITCODE -ne 0) {
            throw "$ContainerName konteyneri baslatilamadi. ExitCode=$LASTEXITCODE"
        }
        Write-Host "$ContainerName baslatildi." -ForegroundColor Green
    }
}

function Wait-ContainerHealthy([string]$ContainerName, [int]$TimeoutSeconds = 60) {
    Write-Step "$ContainerName saglik durumu bekleniyor"

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $ContainerName 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "$ContainerName konteyneri saglik durumu okunamadi."
        }

        if ($status -eq "healthy") {
            Write-Host "$ContainerName healthy." -ForegroundColor Green
            return
        }

        if ($status -eq "none") {
            Write-Host "$ContainerName icin healthcheck yok; calisiyor kabul edildi." -ForegroundColor Yellow
            return
        }

        Start-Sleep -Seconds 2
    }

    throw "$ContainerName konteyneri $TimeoutSeconds saniye icinde healthy olmadi."
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

$SqlPath = Resolve-Path $SqlFile
$SqlName = Split-Path $SqlPath -Leaf

if ($SqlName -ieq "db_yedek.utf8.sql" -and -not $AllowMojibakeFile) {
    throw "db_yedek.utf8.sql dosyasi mojibake/Turkce karakter bozulmasi icerebilir. Dogru dosya genelde db_yedek.sql. Yine de kullanmak icin -AllowMojibakeFile ekleyin."
}

$SqlText = [System.IO.File]::ReadAllText($SqlPath, [System.Text.Encoding]::UTF8)
$MojibakeMarkers = @(
    [string][char]0x00C3,
    [string][char]0x00C4,
    [string][char]0x00C5
)
$MojibakeCount = 0
foreach ($Marker in $MojibakeMarkers) {
    $MojibakeCount += ([regex]::Matches($SqlText, [regex]::Escape($Marker))).Count
}

if ($MojibakeCount -gt 20 -and -not $AllowMojibakeFile) {
    throw "SQL dosyasinda $MojibakeCount adet mojibake isareti bulundu. Turkce karakterler bozulmus olabilir. Dogru dosyayi secin veya bilerek devam etmek icin -AllowMojibakeFile kullanin."
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ContainerSql = "/tmp/db_yedek_$Timestamp.sql"

Write-Step "Ayarlar"
Write-Host "Proje      : $ProjectRoot"
Write-Host "SQL        : $SqlPath"
Write-Host "DB         : $DbContainer / $DbName"
Write-Host "Web        : $WebContainer"
Write-Host "Encoding   : UTF-8 olarak okunuyor"

Start-ContainerIfStopped $DbContainer $DbService
Wait-ContainerHealthy $DbContainer

Invoke-Checked "PostgreSQL encoding kontrolu" {
    docker exec $DbContainer psql -U $DbUser -d $DbName -Atc "SHOW server_encoding; SHOW client_encoding;"
}

if (-not $SkipBackup) {
    if (-not (Test-Path $BackupDir)) {
        New-Item -ItemType Directory -Path $BackupDir | Out-Null
    }

    $BackupFile = Join-Path $BackupDir "kiralama_db_before_restore_$Timestamp.dump"
    $ContainerBackup = "/tmp/kiralama_db_before_restore_$Timestamp.dump"

    Invoke-Checked "Restore oncesi DB yedegi aliniyor" {
        docker exec $DbContainer pg_dump -U $DbUser -d $DbName -Fc -f $ContainerBackup
        docker cp "${DbContainer}:$ContainerBackup" $BackupFile
    }

    Write-Host "Yedek      : $BackupFile" -ForegroundColor Green
}
else {
    Write-Host ""
    Write-Host "UYARI: -SkipBackup verildi, restore oncesi yedek alinmadi." -ForegroundColor Yellow
}

Invoke-Checked "SQL dosyasi konteynere kopyalaniyor" {
    docker cp $SqlPath "${DbContainer}:$ContainerSql"
}

if (-not $NoStopWeb) {
    Stop-ContainerIfRunning $WebContainer
}

try {
    Invoke-Checked "SQL yedegi PostgreSQL'e aktariliyor" {
        docker exec $DbContainer psql -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -f $ContainerSql
    }

    Invoke-Checked "Kullanici aktif oturumlari temizleniyor" {
        $ClearActiveSessionsSql = "DO `$`$ BEGIN EXECUTE 'UPDATE ' || chr(34) || 'user' || chr(34) || ' SET active_session_token = NULL, active_session_started_at = NULL, active_session_seen_at = NULL'; END `$`$;"
        docker exec $DbContainer psql -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -c $ClearActiveSessionsSql
    }
}
finally {
    if (-not $NoStopWeb) {
        Start-Or-Restart-Container $WebContainer $WebService
    }
}

Invoke-Checked "Turkce karakter ve satir kontrolu" {
    docker exec $DbContainer psql -U $DbUser -d $DbName -Atc "SHOW server_encoding; SHOW client_encoding; SELECT company_name || ' | ' || company_address FROM app_settings LIMIT 1; SELECT COUNT(*) FROM firma; SELECT firma_adi FROM firma WHERE firma_adi ~ ('[' || chr(304) || chr(350) || chr(286) || chr(220) || chr(214) || chr(199) || chr(305) || chr(351) || chr(287) || chr(252) || chr(246) || chr(231) || ']') LIMIT 5;"
}

Write-Step "Konteyner durumu"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

Write-Host ""
Write-Host "Tamamlandi." -ForegroundColor Green
