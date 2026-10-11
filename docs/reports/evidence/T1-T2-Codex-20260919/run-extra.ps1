$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '../../../..'))
$ev='docs/reports/evidence/T1-T2-Codex-20260919'
$fw='电控/firmware/stm32f407_m144z'
$flags=@('-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic')
foreach($wait in @(2000,200)) {
  $headers=if($wait -eq 2000){"$ev/baseline-inc"}else{"$ev/wait200-inc"}
  $test=if($wait -eq 2000){"$ev/test_motion_baseline.c"}else{"$ev/test_motion_wait200.c"}
  & gcc @flags -DEC_MOTION_XY_ORDER_X_FIRST=0 -I $headers -I 电控/stm32_logic/include -I "$fw/tests" $test "$fw/App/Src/ec_motion_plan.c" "$fw/App/Src/ec_axis_driver.c" -o "$ev/motion-yfirst-$wait.exe"
  if($LASTEXITCODE -ne 0){throw 'compile failed'}
  & "$ev/motion-yfirst-$wait.exe"
  if($LASTEXITCODE -ne 0){throw 'test failed'}
  Write-Output "Y_FIRST WAIT=$wait exit=0"
}
& gcc @flags -I "$fw/tests" -I "$fw/App/Inc" -I 电控/stm32_logic/include "$ev/wait_probe.c" "$fw/App/Src/ec_axis_driver.c" -o "$ev/wait-probe.exe"
if($LASTEXITCODE -ne 0){throw 'compile failed'}
& "$ev/wait-probe.exe"
if($LASTEXITCODE -ne 0){throw 'test failed'}
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='电控/src'
py -3.14 "$ev/pi_probe.py"
if($LASTEXITCODE -ne 0){throw 'probe failed'}
foreach($test in @('test_gateway.py','test_barrier_ready_resend.py','test_serial_link_serial.py')) {
  py -3.14 -m unittest discover -s 电控/tests/rpi -p $test -v
  if($LASTEXITCODE -ne 0){throw "Python tests failed: $test"}
}
