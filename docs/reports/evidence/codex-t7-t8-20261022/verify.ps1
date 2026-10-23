param([string]$Workspace = 'C:\Users\29845\Desktop\工创赛')
$ErrorActionPreference = 'Stop'
$Evidence = $PSScriptRoot
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ('ct78-' + [guid]::NewGuid().ToString('N').Substring(0,8))
$Project = Join-Path $TempRoot 'project'
$Fw = Join-Path $Project 'firmware\stm32f407_m144z'
$Build = Join-Path $TempRoot 'build'
$Source = Join-Path $Workspace '电控\firmware\stm32f407_m144z'
New-Item -ItemType Directory -Path $Fw -Force | Out-Null
$manifest = @()
function Copy-Verified([string]$from, [string]$to) {
    $before = (Get-FileHash -LiteralPath $from -Algorithm SHA256).Hash
    New-Item -ItemType Directory -Path (Split-Path $to) -Force | Out-Null
    Copy-Item -LiteralPath $from -Destination $to
    $after = (Get-FileHash -LiteralPath $from -Algorithm SHA256).Hash
    $snapshot = (Get-FileHash -LiteralPath $to -Algorithm SHA256).Hash
    if ($before -ne $after -or $before -ne $snapshot) { throw "Concurrent change: $from" }
    $script:manifest += [pscustomobject]@{source=$from; snapshot=$to; sha256=$snapshot}
}
foreach ($sub in @('App\Inc','App\Src','Core\Inc','tests')) {
    Get-ChildItem -LiteralPath (Join-Path $Source $sub) -File | Where-Object {
        $_.Extension -in @('.c','.h') -or $_.Name -eq 'CMakeLists.txt'
    } | ForEach-Object { Copy-Verified $_.FullName (Join-Path (Join-Path $Fw $sub) $_.Name) }
}
foreach ($sub in @('tests\host_stubs','tests\motion_completion_hal')) {
    Get-ChildItem -LiteralPath (Join-Path $Source $sub) -File | ForEach-Object {
        Copy-Verified $_.FullName (Join-Path (Join-Path $Fw $sub) $_.Name)
    }
}
foreach ($sub in @('include','src')) {
    Get-ChildItem -LiteralPath (Join-Path $Workspace "电控\stm32_logic\$sub") -File | ForEach-Object {
        Copy-Verified $_.FullName (Join-Path $Project "stm32_logic\$sub\$($_.Name)")
    }
}
Copy-Verified (Join-Path $Source 'MDK-ARM\diankongv1.0.uvprojx') (Join-Path $Fw 'MDK-ARM\diankongv1.0.uvprojx')
foreach ($file in @('probe.c','probe_hal_extensions.h','verify.ps1')) {
    Copy-Verified (Join-Path $Evidence $file) (Join-Path $TempRoot $file)
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Evidence 'source-manifest.json') -Encoding utf8
$TempRoot | Set-Content -LiteralPath (Join-Path $Evidence 'last-temp-root.txt') -Encoding utf8
$gccArgs = @('-std=c11','-Wall','-Wextra','-Werror','-pedantic','-ffunction-sections','-fdata-sections',
    '-include',(Join-Path $TempRoot 'probe_hal_extensions.h'),
    '-I',"$Fw\tests\motion_completion_hal",'-I',"$Fw\Core\Inc",'-I',"$Fw\App\Inc",'-I',"$Fw\tests",'-I',"$Project\stm32_logic\include",
    (Join-Path $TempRoot 'probe.c'),"$Fw\App\Src\ec_group_test.c","$Fw\App\Src\ec_board_stm32.c","$Fw\App\Src\ec_step_test.c",
    "$Fw\App\Src\ec_inputs.c","$Fw\App\Src\ec_bus_servo.c","$Project\stm32_logic\src\ec_step_profile.c",'-Wl,--gc-sections','-lm','-o',(Join-Path $TempRoot 'probe.exe'))
("Snapshot root: " + $TempRoot + "`ngcc " + ($gccArgs -join ' ')) | Set-Content -LiteralPath (Join-Path $Evidence 'probe-build.log') -Encoding utf8
& gcc @gccArgs 2>&1 | Tee-Object -FilePath (Join-Path $Evidence 'probe-build.log') -Append
if ($LASTEXITCODE -ne 0) { throw 'Probe build failed' }
'Compiler exit=0' | Add-Content -LiteralPath (Join-Path $Evidence 'probe-build.log') -Encoding utf8
& (Join-Path $TempRoot 'probe.exe') --expect-requested-rate 2>&1 | Tee-Object -FilePath (Join-Path $Evidence 'probe-red.log')
$redExit = $LASTEXITCODE
"Expected counterexample exit=$redExit" | Tee-Object -FilePath (Join-Path $Evidence 'probe-red.log') -Append
if ($redExit -eq 0 -or -not (Select-String -LiteralPath (Join-Path $Evidence 'probe-red.log') -SimpleMatch 'assertion failed: 100000U / (min_arr + 1U) <= rates[i]' -Quiet)) { throw 'Expected rate counterexample did not reproduce' }
& (Join-Path $TempRoot 'probe.exe') 2>&1 | Tee-Object -FilePath (Join-Path $Evidence 'probe-green.log')
if ($LASTEXITCODE -ne 0) { throw 'Probe checks failed' }
& cmake -S "$Fw\tests" -B $Build -G 'MinGW Makefiles' -DCMAKE_OBJECT_PATH_MAX=200 2>&1 | Tee-Object -FilePath (Join-Path $Evidence 'cmake-configure.log')
if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed' }
& cmake --build $Build -j 8 2>&1 | Tee-Object -FilePath (Join-Path $Evidence 'cmake-build.log')
if ($LASTEXITCODE -ne 0) { throw 'CMake build failed' }
& ctest --test-dir $Build --output-on-failure 2>&1 | Tee-Object -FilePath (Join-Path $Evidence 'ctest.log')
if ($LASTEXITCODE -ne 0) { throw 'CTest failed' }
$changed = @($manifest | Where-Object {
    (Get-FileHash -LiteralPath $_.source -Algorithm SHA256).Hash -ne $_.sha256
} | ForEach-Object {$_.source})
[pscustomobject]@{ temp_root=$TempRoot; counterexample_exit=$redExit; snapshot_files=$manifest.Count; source_changed_during_run=$changed; hardware_executed=$false } |
    ConvertTo-Json -Depth 4 | Tee-Object -FilePath (Join-Path $Evidence 'result.json')






if ($changed.Count -gt 0) { throw 'Source changed during verification; snapshot only, not current workspace validation' }


