$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$fw = Join-Path $root '电控/firmware/stm32f407_m144z'
$mdk = Join-Path $fw 'MDK-ARM'
$project = Join-Path $mdk 'diankongv1.0.uvprojx'
[xml]$xml = Get-Content -LiteralPath $project -Raw
$sources = @($project)
foreach ($node in $xml.SelectNodes('//FilePath')) {
    $sources += (Resolve-Path (Join-Path $mdk $node.InnerText)).Path
}
$sources += Get-ChildItem -LiteralPath (Join-Path $fw 'App/Inc'),
    (Join-Path $fw 'Core/Inc'), (Join-Path $root '电控/stm32_logic/include') -Filter '*.h' |
    ForEach-Object { $_.FullName }
$before = $sources | Sort-Object -Unique | Get-FileHash -Algorithm SHA256
$before | Select-Object Path,Hash | Export-Csv -LiteralPath (Join-Path $PSScriptRoot 'source-hashes-before.csv') -NoTypeInformation -Encoding utf8
$logName = 'motion-completion-20260918-keil.log'
$p = Start-Process -FilePath 'D:/Keil/UV4/UV4.exe' `
    -ArgumentList @('-r','diankongv1.0.uvprojx','-o',$logName) `
    -WorkingDirectory 'S:/firmware/stm32f407_m144z/MDK-ARM' `
    -WindowStyle Hidden -Wait -PassThru
$result = "KeilExitCode=$($p.ExitCode)"
$result | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'keil-exit.txt') -Encoding utf8
Write-Output $result
Copy-Item -LiteralPath (Join-Path $mdk $logName) -Destination (Join-Path $PSScriptRoot 'keil-rebuild.log')
Get-Content -LiteralPath (Join-Path $PSScriptRoot 'keil-rebuild.log')
$after = $sources | Sort-Object -Unique | Get-FileHash -Algorithm SHA256
$after | Select-Object Path,Hash | Export-Csv -LiteralPath (Join-Path $PSScriptRoot 'source-hashes-after.csv') -NoTypeInformation -Encoding utf8
$difference = Compare-Object $before $after -Property Path,Hash
if ($difference) { $difference | Format-List; throw 'Sources changed during build' }
'SourceHashesUnchanged=True' | Add-Content -LiteralPath (Join-Path $PSScriptRoot 'keil-exit.txt')
Get-FileHash -LiteralPath (Join-Path $mdk 'diankongv1.0/diankongv1.hex') -Algorithm SHA256 |
    Select-Object Path,Hash | Export-Csv -LiteralPath (Join-Path $PSScriptRoot 'hex-hash.csv') -NoTypeInformation -Encoding utf8
if ($p.ExitCode -ne 0) { throw "Keil failed: $($p.ExitCode)" }
