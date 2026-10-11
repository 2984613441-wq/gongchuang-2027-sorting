$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$fw = Join-Path $root '电控/firmware/stm32f407_m144z'
$logic = Join-Path $root '电控/stm32_logic'
$sources = @('ec_app','ec_axis_driver','ec_board_stm32','ec_motion_plan','ec_diag',
    'ec_inputs','ec_step_test','ec_servo_test','ec_group_test','ec_barrier_test',
    'ec_startup_sequence','ec_safety_adapter','ec_demo','ec_bus_servo') |
    ForEach-Object { Join-Path $fw "App/Src/$_.c" }
$sources += @('ec_protocol','ec_protocol_gateway','ec_state_machine','ec_dedup',
    'ec_crc32','ec_step_profile') | ForEach-Object { Join-Path $logic "src/$_.c" }
$sources += Join-Path $fw 'tests/test_motion_completion.c'
$out = Join-Path $PSScriptRoot 'motion-completion-host.exe'
$options = @('-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic',
    '-DEC_DIAGNOSTIC_BUILD=1','-DEC_MOTION_TEST_BUILD=1','-DEC_SERVO_TEST_BUILD=1',
    '-DEC_GROUP_TEST_BUILD=0','-DEC_BARRIER_TEST_BUILD=0','-DEC_APP_PROGRESS_SOURCE_ENABLED=0')
foreach ($inc in @('tests/motion_completion_hal','App/Inc','Core/Inc','tests')) {
    $options += '-I' + (Join-Path $fw $inc)
}
$options += '-I' + (Join-Path $logic 'include')
Push-Location $PSScriptRoot
try {
    & gcc @options @sources -o motion-completion-host.exe 2>&1 | Tee-Object (Join-Path $PSScriptRoot 'host-build.log')
    if ($LASTEXITCODE -ne 0) { throw "Host compile failed: $LASTEXITCODE" }
} finally { Pop-Location }
foreach ($scenario in @('diag','normal','missing_irq','missing_final_latch')) {
    & $out $scenario 2>&1 | Tee-Object (Join-Path $PSScriptRoot "$scenario.log")
    if ($LASTEXITCODE -ne 0) { throw "Host scenario $scenario failed: $LASTEXITCODE" }
}
