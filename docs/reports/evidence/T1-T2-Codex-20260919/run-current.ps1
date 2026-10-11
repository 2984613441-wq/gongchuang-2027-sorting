$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '../../../..'))
$ev='docs/reports/evidence/T1-T2-Codex-20260919'
$fw='电控/firmware/stm32f407_m144z'
$flags=@('-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic')
rg -n 'define EC_AXIS_(GRIPPER_SETTLE_MS|PICK_DWELL_MS)' "$fw/App/Inc/ec_axis_driver.h"
foreach($order in @(0,1)) {
  & gcc @flags "-DEC_MOTION_XY_ORDER_X_FIRST=$order" -I "$fw/App/Inc" -I 电控/stm32_logic/include "$fw/tests/test_motion_plan.c" "$fw/App/Src/ec_motion_plan.c" "$fw/App/Src/ec_axis_driver.c" -o "$ev/current-motion-$order.exe"
  if($LASTEXITCODE -ne 0){throw 'compile failed'}
  & "$ev/current-motion-$order.exe"
  if($LASTEXITCODE -ne 0){throw 'test failed'}
  Write-Output "CURRENT motion order=$order exit=0"
}
& gcc @flags -I "$fw/App/Inc" -I 电控/stm32_logic/include "$fw/tests/test_axis_driver.c" "$fw/App/Src/ec_axis_driver.c" -o "$ev/current-axis.exe"
if($LASTEXITCODE -ne 0){throw 'compile failed'}
& "$ev/current-axis.exe"
if($LASTEXITCODE -ne 0){throw 'test failed'}
Write-Output 'CURRENT axis exit=0'
