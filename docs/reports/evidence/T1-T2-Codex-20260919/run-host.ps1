$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
Set-Location -LiteralPath $root
$root='.'
$ev='docs/reports/evidence/T1-T2-Codex-20260919'
$fw=Join-Path $root '电控/firmware/stm32f407_m144z'
$logic=Join-Path $root '电控/stm32_logic'
# Preserve the requested baseline despite concurrent production edits.
# wait200-inc and test_motion_wait200.c are the already captured, tested copies.
$baseline=Join-Path $ev 'baseline-inc'
New-Item -ItemType Directory -Force -Path $baseline | Out-Null
Copy-Item -Path "$ev/wait200-inc/*.h" -Destination $baseline
$h=Join-Path (Get-Location) "$baseline/ec_axis_driver.h"
$text=Get-Content -Raw -LiteralPath $h
[IO.File]::WriteAllText($h,$text.Replace('#define EC_AXIS_PICK_DWELL_MS UINT32_C(200)','#define EC_AXIS_PICK_DWELL_MS UINT32_C(2000)'))
$test=Get-Content -Raw -LiteralPath "$ev/test_motion_wait200.c"
$test=[regex]::Replace($test,'(assert_wait\([^\r\n]*, )200U(\);)','${1}2000U${2}')
$test=$test.Replace('EC_AXIS_PICK_DWELL_MS == 200U','EC_AXIS_PICK_DWELL_MS == 2000U')
[IO.File]::WriteAllText((Join-Path (Get-Location) "$ev/test_motion_baseline.c"),$test)
$inc=@('-I',$baseline,'-I',"$logic/include",'-I',"$fw/tests/host_stubs",'-I',"$fw/tests")
$flags=@('-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic')
function BuildRun($name,$sources,$extra) {
  Write-Output "BUILD $name (gcc C11 O2 Wall Wextra Werror pedantic)"
  & gcc @flags @extra @sources -o "$ev/$name.exe"
  if($LASTEXITCODE -ne 0) { throw "compile $name exit=$LASTEXITCODE" }
  & "$ev/$name.exe"
  if($LASTEXITCODE -ne 0) { throw "run $name exit=$LASTEXITCODE" }
  Write-Output "EXIT $name = 0"
}
BuildRun 'profile-tests' @("$ev/profile_main.c","$logic/tests/test_step_profile.c","$logic/src/ec_step_profile.c") @('-I',"$logic/include",'-I',"$logic/tests",'-lm')
$cm=Get-Content -Raw -LiteralPath "$fw/tests/CMakeLists.txt"
foreach($name in @('ec_motion_plan_tests','ec_axis_driver_tests','ec_firmware_host_tests','ec_progress_source_disabled_tests')) {
  $match=[regex]::Match($cm,"add_executable\($name\s+([^\)]+)\)")
  $sources=@($match.Groups[1].Value.Trim() -split '\s+' | ForEach-Object { "$fw/tests/$_" })
  if($name -eq 'ec_motion_plan_tests') { $sources[0]="$ev/test_motion_baseline.c" }
  $extra=$inc
  if($name -like '*host_tests' -or $name -like '*disabled_tests') {
    $sources+="$ev/diag_double.c"
    $enabled=if($name -eq 'ec_progress_source_disabled_tests'){0}else{1}
    $extra+=@('-DEC_DIAGNOSTIC_BUILD=1','-DEC_MOTION_TEST_BUILD=1','-DEC_SERVO_TEST_BUILD=1','-DEC_GROUP_TEST_BUILD=1','-DEC_BARRIER_TEST_BUILD=1','-DEC_APP_TEST_HOOKS=1',"-DEC_APP_PROGRESS_SOURCE_ENABLED=$enabled")
  }
  BuildRun $name $sources $extra
  if($name -eq 'ec_firmware_host_tests') {
    $probeSources=@($sources | Where-Object { (Split-Path $_ -Leaf) -notin @('test_main.c','test_app.c') }) + "$ev/app_probe.c"
    BuildRun 'app-probe' $probeSources $extra
  }
}
$shadow=Join-Path $ev 'wait200-inc'
# Existing tests hard-code 2000: preserve their expected failure as evidence.
$expectedFailure=$false
try {
  BuildRun 'motion-wait200-original-tests' @("$ev/test_motion_baseline.c","$fw/App/Src/ec_motion_plan.c","$fw/App/Src/ec_axis_driver.c") @('-I',$shadow,'-I',"$logic/include",'-I',"$fw/tests")
} catch {
  if($_.Exception.Message -ne 'run motion-wait200-original-tests exit=1') { throw }
  $expectedFailure=$true
  Write-Output "EXPECTED WAIT200 BASELINE TEST FAILURE: $_"
}
if(-not $expectedFailure) { throw 'unexpected success of hard-coded 2000 assertions' }
BuildRun 'motion-wait200-adapted-tests' @("$ev/test_motion_wait200.c","$fw/App/Src/ec_motion_plan.c","$fw/App/Src/ec_axis_driver.c") @('-I',$shadow,'-I',"$logic/include",'-I',"$fw/tests")
$logicSources=@('tests/test_main.c','tests/test_crc32.c','tests/test_dedup.c','tests/test_state_machine.c','tests/test_protocol.c','tests/test_protocol_gateway.c','src/ec_crc32.c','src/ec_dedup.c','src/ec_state_machine.c','src/ec_protocol.c','src/ec_protocol_gateway.c') | ForEach-Object { "$logic/$_" }
BuildRun 'logic-tests' $logicSources @('-I',"$logic/include",'-I',"$logic/tests")
