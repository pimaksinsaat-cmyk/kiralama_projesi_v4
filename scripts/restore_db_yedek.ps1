<#
Kullanim:
  .\scripts\restore_db_yedek.ps1

Varsayilan olarak db_yedek.sql dosyasini kiralama_veritabani icindeki
kiralama_db veritabanina aktarir. Restore oncesi backups/ altina yedek alir,
kiralama_web ve kiralama_scheduler konteynerlerini gecici durdurur ve is
bitince tekrar baslatir.

Ornekler:
  .\scripts\restore_db_yedek.ps1 -SqlFile .\db_yedek.sql
  .\scripts\restore_db_yedek.ps1 -SqlFile .\firma_data.sql -NoStopWeb
  .\scripts\restore_db_yedek.ps1 -SqlFile .\firma_data.sql -NoCleanPublicSchema
  .\scripts\restore_db_yedek.ps1 -SkipBackup

db_yedek.utf8.sql Turkce karakterleri bozuk/mojibake icerebilir; script bu
dosyayi varsayilan olarak engeller. Bilerek kullanmak icin:
  .\scripts\restore_db_yedek.ps1 -SqlFile .\db_yedek.utf8.sql -AllowMojibakeFile
#>

param(
    [string]$SqlFile = "db_yedek.sql",
    [string]$DbContainer = "kiralama_veritabani",
    [string]$WebContainer = "kiralama_web",
    [string]$SchedulerContainer = "kiralama_scheduler",
    [string]$DbService = "db",
    [string]$WebService = "web",
    [string]$SchedulerService = "scheduler",
    [string]$DbName = "kiralama_db",
    [string]$DbUser = "postgres",
    [string]$BackupDir = "backups",
    [switch]$NoStopWeb,
    [switch]$SkipBackup,
    [switch]$NoCleanPublicSchema,
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

function Test-DockerDaemonAvailable {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        docker ps -q > $null 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-DockerDesktopPath {
    $possiblePaths = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
    )

    return $possiblePaths |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
        Select-Object -First 1
}

function Get-DockerStartupStatus {
    $dockerService = Get-Service -Name com.docker.service -ErrorAction SilentlyContinue
    $dockerDesktopProcess = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue |
        Select-Object -First 1

    $serviceStatus = if ($null -eq $dockerService) {
        "bulunamadi"
    }
    else {
        $dockerService.Status.ToString()
    }

    $desktopStatus = if ($null -eq $dockerDesktopProcess) {
        "calismiyor"
    }
    else {
        "calisiyor (PID=$($dockerDesktopProcess.Id))"
    }

    return "Docker Desktop servisi=$serviceStatus; Docker Desktop uygulamasi=$desktopStatus; daemon=erisilemiyor"
}

function Ensure-DockerDaemonRunning([int]$TimeoutSeconds = 120) {
    Write-Step "Docker daemon kontrol ediliyor"

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker komutu bulunamadi. Docker Desktop'i kurun veya docker.exe dosyasini PATH'e ekleyin."
    }

    if (Test-DockerDaemonAvailable) {
        Write-Host "Docker daemon zaten calisiyor." -ForegroundColor Green
        return
    }

    $dockerService = Get-Service -Name com.docker.service -ErrorAction SilentlyContinue
    if ($null -ne $dockerService) {
        if ($dockerService.Status -ne 'Running') {
            Write-Host "Docker Desktop servisi duruyor; baslatilmasi deneniyor." -ForegroundColor Cyan
            try {
                Start-Service -Name com.docker.service -ErrorAction Stop
                Write-Host "Docker Desktop servisi baslatildi." -ForegroundColor Green
            }
            catch {
                Write-Host "Docker Desktop servisi baslatilamadi: $($_.Exception.Message)" -ForegroundColor Yellow
                Write-Host "Yonetici yetkisi gerektirmeyen Docker Desktop baslatma yontemi denenecek." -ForegroundColor Yellow
            }
        }
        else {
            Write-Host "Docker Desktop servisi calisiyor; daemon henuz kullanilabilir degil." -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "Docker Desktop servisi bulunamadi." -ForegroundColor Yellow
    }

    if (Test-DockerDaemonAvailable) {
        Write-Host "Docker daemon servis baslatildiktan sonra kullanilabilir hale geldi." -ForegroundColor Green
        return
    }

    $dockerDesktopPath = Get-DockerDesktopPath
    if (-not $dockerDesktopPath) {
        throw "Docker daemon erisilemiyor ve Docker Desktop uygulamasi bulunamadi. Docker Desktop'i kurun veya elle baslatin."
    }

    $dockerDesktopProcess = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $dockerDesktopProcess) {
        Write-Host "Docker Desktop baslatiliyor: $dockerDesktopPath" -ForegroundColor Cyan
        try {
            Start-Process -FilePath $dockerDesktopPath -WindowStyle Hidden -ErrorAction Stop
        }
        catch {
            throw "Docker Desktop baslatilamadi: $($_.Exception.Message)"
        }
    }
    else {
        Write-Host "Docker Desktop uygulamasi zaten acik; daemon hazir olmasi bekleniyor." -ForegroundColor Yellow
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $elapsedSeconds = 0
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerDaemonAvailable) {
            Write-Host "Docker daemon kullanilabilir." -ForegroundColor Green
            return
        }

        Start-Sleep -Seconds 2
        $elapsedSeconds += 2
        if (($elapsedSeconds % 10) -eq 0) {
            Write-Host "Docker daemon bekleniyor... $elapsedSeconds/$TimeoutSeconds saniye" -ForegroundColor Cyan
        }
    }

    $startupStatus = Get-DockerStartupStatus
    throw "Docker daemon $TimeoutSeconds saniye icinde kullanilabilir hale gelmedi. $startupStatus. Docker Desktop'i acip hata bildirimlerini kontrol edin."
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

function Get-DumpVersionLine([string]$SqlText) {
    $match = [regex]::Match($SqlText, '(?m)^-- Dumped by pg_dump version .+$')
    if ($match.Success) {
        return $match.Value.Trim()
    }

    return "Dumped by pg_dump version satiri bulunamadi."
}

function New-CompatibleSqlRestoreFile {
    param(
        [string]$SourcePath,
        [string]$WorkDir,
        [string]$Timestamp
    )

    if (-not (Test-Path -LiteralPath $WorkDir)) {
        New-Item -ItemType Directory -Path $WorkDir | Out-Null
    }

    $sourceName = [System.IO.Path]::GetFileNameWithoutExtension($SourcePath)
    $targetPath = Join-Path $WorkDir "$sourceName.restore_$Timestamp.sql"
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $linesRemoved = 0

    $reader = [System.IO.StreamReader]::new($SourcePath, [System.Text.Encoding]::UTF8, $true)
    try {
        $writer = [System.IO.StreamWriter]::new($targetPath, $false, $utf8NoBom)
        try {
            while (($line = $reader.ReadLine()) -ne $null) {
                if ($line -match '^\\(un)?restrict(\s|$)') {
                    $linesRemoved += 1
                    continue
                }

                $writer.WriteLine($line)
            }
        }
        finally {
            $writer.Dispose()
        }
    }
    finally {
        $reader.Dispose()
    }

    return [pscustomobject]@{
        Path = $targetPath
        LinesRemoved = $linesRemoved
    }
}

function Invoke-PsqlFileWithLog {
    param(
        [string]$DbContainer,
        [string]$DbUser,
        [string]$DbName,
        [string]$ContainerSql,
        [string]$LogPath
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = docker exec $DbContainer psql -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -f $ContainerSql 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    $output | Tee-Object -FilePath $LogPath

    if ($exitCode -ne 0) {
        Write-Host ""
        Write-Host "psql hata logu: $LogPath" -ForegroundColor Yellow
        throw "SQL yedegi PostgreSQL'e aktariliyor basarisiz oldu. ExitCode=$exitCode"
    }
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
$RestoreWorkDir = Join-Path $BackupDir "restore_work"
$CompatibleSql = $null
$RestoreCompleted = $false
$AppContainersStopped = $false
$DumpVersionLine = Get-DumpVersionLine $SqlText
$RestoreLog = Join-Path $RestoreWorkDir "restore_$Timestamp.log"

Write-Step "Ayarlar"
Write-Host "Proje      : $ProjectRoot"
Write-Host "SQL        : $SqlPath"
Write-Host "DB         : $DbContainer / $DbName"
Write-Host "Web        : $WebContainer"
Write-Host "Scheduler  : $SchedulerContainer"
Write-Host "Encoding   : UTF-8 olarak okunuyor"
Write-Host "Dump       : $DumpVersionLine"

try {
    Ensure-DockerDaemonRunning
    Start-ContainerIfStopped $DbContainer $DbService
    Wait-ContainerHealthy $DbContainer

    Invoke-Checked "PostgreSQL surum ve encoding kontrolu" {
        docker exec $DbContainer psql --version
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

    Write-Step "SQL dosyasi restore icin hazirlaniyor"
    $CompatibleSql = New-CompatibleSqlRestoreFile $SqlPath $RestoreWorkDir $Timestamp
    Write-Host "Gecici SQL : $($CompatibleSql.Path)"
    Write-Host "Kaldirilan PostgreSQL 16 meta-komut satiri: $($CompatibleSql.LinesRemoved)"

    Invoke-Checked "SQL dosyasi konteynere kopyalaniyor" {
        docker cp $CompatibleSql.Path "${DbContainer}:$ContainerSql"
    }

    if (-not $NoStopWeb) {
        Stop-ContainerIfRunning $SchedulerContainer
        Stop-ContainerIfRunning $WebContainer
        $AppContainersStopped = $true
    }

    Invoke-Checked "Aktif veritabani baglantilari kapatiliyor" {
        docker exec $DbContainer psql -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -Atc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();"
    }

    if (-not $NoCleanPublicSchema) {
        Invoke-Checked "Public schema temizleniyor" {
            docker exec $DbContainer psql -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO postgres; GRANT ALL ON SCHEMA public TO public;"
        }
    }
    else {
        Write-Host ""
        Write-Host "UYARI: -NoCleanPublicSchema verildi, public schema restore oncesi temizlenmedi." -ForegroundColor Yellow
    }

    try {
        Write-Step "SQL yedegi PostgreSQL'e aktariliyor"
        Invoke-PsqlFileWithLog $DbContainer $DbUser $DbName $ContainerSql $RestoreLog

        Invoke-Checked "Kullanici aktif oturumlari temizleniyor" {
            $ClearActiveSessionsSql = "DO `$`$ BEGIN EXECUTE 'UPDATE ' || chr(34) || 'user' || chr(34) || ' SET active_session_token = NULL, active_session_started_at = NULL, active_session_seen_at = NULL'; END `$`$;"
            docker exec $DbContainer psql -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -c $ClearActiveSessionsSql
        }
    }
    finally {
        if ($AppContainersStopped) {
            Start-Or-Restart-Container $WebContainer $WebService
            Start-Or-Restart-Container $SchedulerContainer $SchedulerService
        }
    }

    Invoke-Checked "Turkce karakter ve satir kontrolu" {
        docker exec $DbContainer psql -U $DbUser -d $DbName -Atc "SHOW server_encoding; SHOW client_encoding; SELECT company_name || ' | ' || company_address FROM app_settings LIMIT 1; SELECT COUNT(*) FROM firma; SELECT firma_adi FROM firma WHERE firma_adi ~ ('[' || chr(304) || chr(350) || chr(286) || chr(220) || chr(214) || chr(199) || chr(305) || chr(351) || chr(287) || chr(252) || chr(246) || chr(231) || ']') LIMIT 5;"
    }

    Write-Step "Konteyner durumu"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

    $RestoreCompleted = $true
    Write-Host ""
    Write-Host "Tamamlandi." -ForegroundColor Green
}
finally {
    if ($null -ne $CompatibleSql -and (Test-Path -LiteralPath $CompatibleSql.Path)) {
        if ($RestoreCompleted) {
            Remove-Item -LiteralPath $CompatibleSql.Path -Force
            Write-Host "Gecici SQL temizlendi: $($CompatibleSql.Path)" -ForegroundColor Green
        }
        else {
            Write-Host ""
            Write-Host "Hata ayiklama icin gecici SQL silinmedi: $($CompatibleSql.Path)" -ForegroundColor Yellow
        }
    }
}
