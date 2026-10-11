# 把"屏幕点亮"这一环推到树莓派并跑起来（只做屏幕，不碰串口/落点表/run_chain）
#
# 用法：
#   pwsh -File 工具\deploy_screen_test.ps1 -Pi 172.20.10.9
#   pwsh -File 工具\deploy_screen_test.ps1 -Pi 172.20.10.9 -Pull    # 跑完把 PNG 拉回来看
#
# 为什么存在：run_chain.py 真实模式有 8 道 fail-closed 门，[DropPoints] 六盒落点与
# --image-dir 两道过不去，启动就 SystemExit，屏幕根本跑不到。本脚本绕开整条链路，
# 只验证"合成帧 -> /dev/fb0 -> 肉眼"这一段。
#
# 本脚本不修改树莓派上的任何配置，只 scp 一个脚本 + 一个图片目录，然后跑一次探针。

param(
    [Parameter(Mandatory = $true)][string]$Pi,
    [string]$User = "pi",
    [string]$Remote = "/opt/ec-chain",
    [string]$Venv = "/opt/ec-chain/deploy/.venv/bin/python",
    [switch]$Pull,
    [string]$PullTo = "$env:USERPROFILE\Desktop\屏幕样张"
)

$ErrorActionPreference = "Stop"

$root   = Split-Path -Parent $PSScriptRoot
$probe  = Join-Path $root "工具\pi_screen_probe.py"
$images = Join-Path $root "电控\deploy\cargo_images"
$target = "$User@$Pi"

# 单引号 here-string：本地不做任何展开，远程变量原样送达；
# 需要注入的路径用 @占位符@ 再替换，避免反引号转义写错。
$preflight = @'
set +e
PY="@VENV@"
[ -x "$PY" ] || PY=python3
echo "HOST:    $(hostname)  $(uname -m)"
echo "USER:    $(id -un)"
echo "REMOTE:  $(test -d @REMOTE@ && echo yes || echo NO)"
echo "PYTHON:  $PY"
echo "PIL:     $("$PY" -c 'import PIL;print(PIL.__version__)' 2>&1 | tail -1)"
echo "EC_PKG:  $("$PY" -c 'import electrical_control.rpi;print("import ok")' 2>&1 | tail -1)"
echo "FB0:     $(ls -l /dev/fb0 2>/dev/null || echo MISSING)"
echo "BPP:     $(cat /sys/class/graphics/fb0/bits_per_pixel 2>/dev/null || echo unknown)   <- 16/24/32 都支持【2026-09-21 更正：原写\"必须 32\"已过期】；本屏实测是 16，display_hdmi.py 从 sysfs 读真实 bpp 按 RGB565 打包"
echo "FONT:    $(ls /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc 2>/dev/null || echo MISSING)"
exit 0
'@
$preflight = $preflight -replace '@REMOTE@', $Remote -replace '@VENV@', $Venv

$runprobe = @'
set +e
PY="@VENV@"
[ -x "$PY" ] || PY=python3
echo "using: $PY"
"$PY" @REMOTE@/deploy/pi_screen_probe.py --image-dir @REMOTE@/cargo_images --all-images --png /tmp/screen_probe --write-anyway
echo "probe_exit=$?"
ls -l /tmp/screen_probe*.png 2>/dev/null | head -20
'@
$runprobe = $runprobe -replace '@REMOTE@', $Remote -replace '@VENV@', $Venv

Write-Host "`n=== 1/4  连通性与环境（先看清对面是什么，再传东西）===" -ForegroundColor Cyan
ssh -o ConnectTimeout=6 -o BatchMode=yes $target $preflight
if ($LASTEXITCODE -ne 0) { throw "ssh 到 $target 失败 —— 确认 IP/用户名/免密，或树莓派没开机" }

Write-Host "`n=== 2/4  上传探针与 6 张货物图（1..6 对应 box_id，依据 stage1_contour_v3.py 的 BIN_MAP）===" -ForegroundColor Cyan
ssh $target "mkdir -p $Remote/deploy"
scp $probe "${target}:$Remote/deploy/pi_screen_probe.py"
scp -r $images "${target}:$Remote/cargo_images"
if ($LASTEXITCODE -ne 0) { throw "scp 失败" }

Write-Host "`n=== 3/4  在树莓派上跑探针（真写 /dev/fb0）===" -ForegroundColor Cyan
ssh $target $runprobe

Write-Host "`n=== 4/4  拉回样张 ===" -ForegroundColor Cyan
if ($Pull) {
    New-Item -ItemType Directory -Force -Path $PullTo | Out-Null
    scp "${target}:/tmp/screen_probe*.png" $PullTo
    Write-Host "样张已拉到 $PullTo —— 逐张打开，重点看：中文是不是方块、左栏有没有图、有没有黑边" -ForegroundColor Yellow
} else {
    Write-Host "（加 -Pull 可把 PNG 拉回本机肉眼确认）" -ForegroundColor DarkGray
}

Write-Host "`n完成。注意：跑通本探针 != run_chain 能启动 —— [DropPoints] 六盒落点与 --image-dir 两道门仍需修。" -ForegroundColor Yellow
