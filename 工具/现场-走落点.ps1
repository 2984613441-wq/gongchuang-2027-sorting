# 现场-走落点.ps1 —— 在【你自己的电脑】上跑，自动 ssh 到树莓派执行移动。
#
# 用法（在本文件所在目录开 PowerShell）：
#     .\现场-走落点.ps1 -Target 2                 # 从当前锚点走到固定落点 ②
#     .\现场-走落点.ps1 -Nudge -Dx 3 -Dy -2       # 相对微调：X +3mm、Y -2mm
#     .\现场-走落点.ps1 -Show                     # 只看锚点在哪，不动
#     .\现场-走落点.ps1 -SetAnchor -X -43 -Y 87.5 # 手动校正锚点（机构已在某点时用）
#
# 安全设计：
#   · 负方向（往 HOME 走）默认拒绝，必须显式加 -AllowNeg
#   · 目标超出 [WorkspaceLimits]（滑台 x∈[-95,85] y∈[-97.5,87.5]）直接拒绝，不发命令
#   · 每段移动后回报 STEP_RESULT（1=正常发完 2=超时 3=安全中止）
#
# 落点表（滑台系 mm）——2026-09-21 现场标定
#   ① 已按现场目视修正 X 负 18.0mm

param(
    [int]$Target = 0,
    [switch]$Nudge,
    [double]$Dx = 0,
    [double]$Dy = 0,
    [switch]$AllowNeg,
    [switch]$Show,
    [switch]$SetAnchor,
    [double]$X = 0,
    [double]$Y = 0,
    [string]$Pi = "pi@172.20.10.8"
)

$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
$stateF = Join-Path $root "工具\.drop_anchor.json"

# 固定落点表（滑台记账坐标，mm）
$DROP = @{
    1 = @{ x = -43.0; y = 87.5 }   # ① 现场目视修正后
    2 = @{ x = -95.0; y = 47.5 }   # ②
    3 = @{ x =  45.0; y = 47.5 }   # ③
}
# 工作区上限（[WorkspaceLimits]，滑台系）
$WS = @{ xmin = -95.0; xmax = 85.0; ymin = -97.5; ymax = 87.5 }

function Get-Anchor {
    if (Test-Path $stateF) {
        $j = Get-Content $stateF -Raw | ConvertFrom-Json
        return @{ x = [double]$j.x; y = [double]$j.y }
    }
    return @{ x = -95.0; y = -97.5 }   # 默认锚点 = HOME
}
function Set-Anchor($x, $y) {
    [pscustomobject]@{ x = $x; y = $y; at = (Get-Date).ToString("s") } |
        ConvertTo-Json | Set-Content $stateF -Encoding UTF8
}

$anchor = Get-Anchor

if ($SetAnchor) {
    Set-Anchor $X $Y
    "锚点已设为 ($X, $Y) —— 仅记录，未发任何运动命令。"
    exit 0
}
if ($Show) {
    "当前锚点（滑台系）= ({0}, {1})" -f $anchor.x, $anchor.y
    "可用落点： " + (($DROP.Keys | Sort-Object) -join "  ")
    exit 0
}

if ($Nudge) {
    $tx = $anchor.x + $Dx; $ty = $anchor.y + $Dy
} elseif ($DROP.ContainsKey($Target)) {
    $tx = $DROP[$Target].x; $ty = $DROP[$Target].y
} else {
    throw "请给 -Target 1|2|3，或 -Nudge -Dx .. -Dy ..，或 -Show"
}

$dx = [math]::Round($tx - $anchor.x, 3)
$dy = [math]::Round($ty - $anchor.y, 3)

"锚点 (滑台系) = ({0}, {1})" -f $anchor.x, $anchor.y
"目标          = ({0}, {1})" -f $tx, $ty
"本次位移      = dx {0:+0.0;-0.0} mm   dy {1:+0.0;-0.0} mm" -f $dx, $dy

if ($tx -lt $WS.xmin -or $tx -gt $WS.xmax -or $ty -lt $WS.ymin -or $ty -gt $WS.ymax) {
    throw ("目标越界：[WorkspaceLimits] 滑台 x∈[{0},{1}] y∈[{2},{3}] —— 已拒绝，未发命令。" -f `
           $WS.xmin, $WS.xmax, $WS.ymin, $WS.ymax)
}
if (($dx -lt 0 -or $dy -lt 0) -and -not $AllowNeg) {
    throw "本次位移含负方向（往 HOME 走）。确认安全后重跑，并加 -AllowNeg。已拒绝，未发命令。"
}

$flags = if ($AllowNeg) { "--allow-neg" } else { "" }
"--- 发往树莓派：python3 /home/pi/pi_goto.py $dx $dy $flags ---"
$out = ssh $Pi "python3 /home/pi/pi_goto.py $dx $dy $flags" 2>&1
$out | ForEach-Object { $_ }

$ok = ($out | Select-String -Pattern "STEP_RESULT=1" -AllMatches).Matches.Count
$bad = ($out | Select-String -Pattern "STEP_RESULT=(2|3)" -AllMatches).Matches.Count
if ($bad -gt 0 -or $ok -eq 0) {
    "❌ 未确认完成（STEP_RESULT 异常或缺失）。锚点**不更新**，请现场核对机构实际位置后再决定。"
    exit 1
}
Set-Anchor $tx $ty
"✅ 已到 ({0}, {1})，锚点已更新。" -f $tx, $ty
"   下一步：现场目视这一步落点准不准；不准就用 -Nudge -Dx .. -Dy .. -AllowNeg 微调，"
"   调准后告诉我，我把它写回 /home/pi/sorting_config.ini 的 [DropPoints]。"
