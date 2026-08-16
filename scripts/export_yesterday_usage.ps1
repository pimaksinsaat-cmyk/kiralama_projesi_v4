param(
    [string]$OutputPath = "./dun_program_kullanim_raporu.csv"
)

$start = (Get-Date).Date.AddDays(-1)
$end = (Get-Date).Date

function Normalize-Command {
    param([string]$Command)

    if ([string]::IsNullOrWhiteSpace($Command)) {
        return ""
    }

    $value = $Command.Trim()
    $value = $value.Trim('"')
    $value = $value.Trim("'")
    return $value
}

function Get-ProgramName {
    param([string]$Command)

    if ([string]::IsNullOrWhiteSpace($Command)) {
        return "bilinmiyor"
    }

    $cmd = Normalize-Command -Command $Command
    if ($cmd -match "([A-Za-z0-9_\-.]+\.exe)") {
        return $Matches[1].ToLowerInvariant()
    }

    $firstToken = ($cmd -split "\s+")[0]
    if ([string]::IsNullOrWhiteSpace($firstToken)) {
        return "bilinmiyor"
    }

    $cleanToken = $firstToken -replace '[<>:"|?*]', ''
    try {
        $name = [System.IO.Path]::GetFileName($cleanToken)
        if ([string]::IsNullOrWhiteSpace($name)) {
            return "bilinmiyor"
        }
        return $name.ToLowerInvariant()
    }
    catch {
        return "bilinmiyor"
    }
}

$startEvents = Get-WinEvent -FilterHashtable @{
    LogName = "Microsoft-Windows-Shell-Core/Operational"
    Id = 9707
    StartTime = $start
    EndTime = $end
} -ErrorAction SilentlyContinue | Sort-Object TimeCreated

$endEvents = Get-WinEvent -FilterHashtable @{
    LogName = "Microsoft-Windows-Shell-Core/Operational"
    Id = 9708
    StartTime = $start
    EndTime = $end
} -ErrorAction SilentlyContinue | Sort-Object TimeCreated

$queuesByCommand = @{}
foreach ($event in $startEvents) {
    $xml = [xml]$event.ToXml()
    $cmd = ($xml.Event.EventData.Data | Where-Object { $_.Name -eq "Command" } | Select-Object -First 1)."#text"
    $cmd = Normalize-Command -Command $cmd

    if (-not $queuesByCommand.ContainsKey($cmd)) {
        $queuesByCommand[$cmd] = New-Object "System.Collections.Generic.Queue[datetime]"
    }

    $queuesByCommand[$cmd].Enqueue($event.TimeCreated)
}

$matched = New-Object "System.Collections.Generic.List[object]"
foreach ($event in $endEvents) {
    $xml = [xml]$event.ToXml()
    $cmd = ($xml.Event.EventData.Data | Where-Object { $_.Name -eq "Command" } | Select-Object -First 1)."#text"
    $cmd = Normalize-Command -Command $cmd

    if ($queuesByCommand.ContainsKey($cmd) -and $queuesByCommand[$cmd].Count -gt 0) {
        $startTime = $queuesByCommand[$cmd].Dequeue()
        $endTime = $event.TimeCreated

        if ($endTime -ge $startTime) {
            $hours = [Math]::Round(($endTime - $startTime).TotalHours, 4)
            $programName = Get-ProgramName -Command $cmd
            if ([string]::IsNullOrWhiteSpace($programName)) {
                $programName = "bilinmiyor"
            }
            $matched.Add([pscustomobject]@{
                Tarih = $start.ToString("yyyy-MM-dd")
                Program = $programName
                Komut = $cmd
                Baslangic = $startTime.ToString("yyyy-MM-dd HH:mm:ss")
                Bitis = $endTime.ToString("yyyy-MM-dd HH:mm:ss")
                SureSaat = $hours
            }) | Out-Null
        }
    }
}

$summary = @()
if ($matched.Count -gt 0) {
    $summary = $matched |
        Group-Object Program |
        ForEach-Object {
            $totalHours = ($_.Group | Measure-Object -Property SureSaat -Sum).Sum
            [pscustomobject]@{
                Tarih = $start.ToString("yyyy-MM-dd")
                Program = $_.Name
                CalismaSayisi = $_.Count
                ToplamSureSaat = [Math]::Round([double]$totalHours, 3)
            }
        } |
        Sort-Object ToplamSureSaat -Descending
}

$summary | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8

Write-Output "RaporOlustu: $OutputPath"
Write-Output "BaslangicOlayi: $($startEvents.Count)"
Write-Output "BitisOlayi: $($endEvents.Count)"
Write-Output "EslesenOturum: $($matched.Count)"
Write-Output "ProgramSayisi: $($summary.Count)"
