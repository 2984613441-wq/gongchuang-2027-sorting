# 现场-取回取证.ps1 —— 在【你自己的电脑】上跑，把 MaixCAM 的取证结果拉进工程文件夹。
#
# 用法：
#     .\现场-取回取证.ps1                 # 拉到 工创赛\取证-YYYYMMDD\，并打印每份 stdout
#     .\现场-取回取证.ps1 -Open           # 拉完自动打开文件夹
#
# 前置（在 MaixCAM 上，每张图一遍）：
#     ssh root@172.20.10.9
#     python /root/forensic/forensic_v6_frame.py <姿态> <光照> <序号> \
#            | tee /root/forensic/<姿态>_<光照>_<序号>.log
#   姿态取值：prism_flat / prism_tri / cube / cylinder      光照：normal / side

param(
    [switch]$Open,
    [string]$Maix = "root@172.20.10.9",
    [string]$RemoteDir = "/root/forensic"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
$dest = Join-Path $root ("取证-" + (Get-Date).ToString("yyyyMMdd"))
New-Item -ItemType Directory -Force -Path $dest | Out-Null

"从 $Maix`:$RemoteDir 取回 → $dest"
scp -o StrictHostKeyChecking=no -r "${Maix}:${RemoteDir}/*" $dest 2>&1 | ForEach-Object { $_ }

$png = @(Get-ChildItem $dest -Filter *.png -ErrorAction SilentlyContinue)
$log = @(Get-ChildItem $dest -Filter *.log -ErrorAction SilentlyContinue)
"取回：PNG $($png.Count) 张，log $($log.Count) 份"

foreach ($f in $log) {
    ""
    "==================== $($f.Name) ===================="
    Get-Content $f.FullName | Select-String -Pattern `
        "XCHECK|ROI \(320\)|gates|results    :|bin=|reject |extent=|H_histogram|bright_px" |
        ForEach-Object { $_.Line }
}

if ($png.Count -eq 0 -and $log.Count -eq 0) {
    "⚠️ 什么都没取到。检查：① MaixCAM 是否在同一热点；② $Maix 的 SSH 口令是否正确；"
    "③ 取证脚本是否真跑过（$RemoteDir 里有文件吗）。"
    exit 1
}
if ($Open) { Invoke-Item $dest }
"完成。目录：$dest"
