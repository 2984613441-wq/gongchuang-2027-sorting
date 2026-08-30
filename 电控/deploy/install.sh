#!/usr/bin/env bash
# ============================================================================
# 树莓派端部署安装脚本（需 root：sudo bash install.sh）
#
# 职责：
#   1. apt 安装中文字体 fonts-wqy-zenhei + python3-venv/pip；
#   2. 创建 venv 并 pip 安装 requirements.txt；
#   3. 把 电控/src 写入 venv 的 .pth，使 electrical_control.rpi.* 无需手动 PYTHONPATH；
#   4. /boot/config.txt：备份原文件后追加 1024x600 屏配置块（幂等，带标记）。
#
# 注意：本脚本只做安装与配置；上电 / 接线 / 烧录属于项目 L4 授权操作，执行前需用户批准。
# 可选参数：$1 = 自定义 config.txt 路径（默认自动探测 /boot/firmware/config.txt 或 /boot/config.txt）
# ============================================================================
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "错误：本脚本需要 root 权限，请用 sudo 运行：sudo bash install.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(dirname "$SCRIPT_DIR")/src"                 # 电控/src（electrical_control 包根）
VENV_DIR="$SCRIPT_DIR/.venv"
MARKER="EC-CHAIN HDMI 1024x600"

echo "==> [1/4] 安装系统包：fonts-wqy-zenhei / python3-venv / python3-pip"
apt-get update
apt-get install -y fonts-wqy-zenhei python3-venv python3-pip

echo "==> [2/4] 创建虚拟环境并安装 Python 依赖"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

echo "==> [3/4] 把电控/src 写入 venv 的 .pth（run_chain.py 的 electrical_control.rpi.* 可直接导入）"
SITE_PKG="$(ls -d "$VENV_DIR"/lib/python*/site-packages | head -n 1)"
echo "$SRC_DIR" > "$SITE_PKG/ec-chain.pth"
echo "    .pth -> $SITE_PKG/ec-chain.pth : $SRC_DIR"

echo "==> [4/4] 配置 config.txt（1024x600，追加前备份原文件）"
if [[ -n "${1:-}" ]]; then
  CONFIG_TXT="$1"
elif [[ -f /boot/firmware/config.txt ]]; then
  CONFIG_TXT="/boot/firmware/config.txt"   # Bookworm 及更新系统
else
  CONFIG_TXT="/boot/config.txt"            # buster/老镜像（随屏资料镜像）
fi

# 屏配置块：与 docs/design/2026-08-29-hdmi-screen-arrival-verification.md §3 逐行一致
CONFIG_BLOCK=(
  "# === $MARKER (2026-08-29 screen spec) ==="
  "max_usb_current=1"
  "hdmi_force_hotplug=1"
  "config_hdmi_boost=7"
  "hdmi_group=2"
  "hdmi_mode=1"
  "hdmi_mode=87"
  "hdmi_drive=1"
  "display_rotate=0"
  "hdmi_cvt 1024 600 60 6 0 0 0"
)

if [[ -f "$CONFIG_TXT" ]]; then
  if grep -q "$MARKER" "$CONFIG_TXT"; then
    echo "    $CONFIG_TXT 已包含屏配置块，跳过（幂等）"
  else
    cp -a "$CONFIG_TXT" "$CONFIG_TXT.bak.$(date +%Y%m%d%H%M%S)"
    printf '%s\n' "${CONFIG_BLOCK[@]}" >> "$CONFIG_TXT"
    echo "    已备份并追加屏配置 -> $CONFIG_TXT"
  fi
else
  echo "    警告：未找到 $CONFIG_TXT（可能未烧录系统），跳过屏配置；烧录后重跑本脚本" >&2
fi

echo
echo "安装完成。"
echo "  venv          : $VENV_DIR"
echo "  源码路径      : $SRC_DIR（已写入 .pth，无需手动 PYTHONPATH）"
echo "  运行示例      : $VENV_DIR/bin/python $SCRIPT_DIR/run_chain.py \\"
echo "                    --port /dev/ttyAMA0 --image-dir /opt/ec-chain/images \\"
echo "                    --names-file /opt/ec-chain/names.json --round-id round-1 --round-task-id 7"
echo "  开发/冒烟     : $VENV_DIR/bin/python $SCRIPT_DIR/run_chain.py --fake-link"
echo "  开机自启      : 见 README.md「开机自启」章节（cp ec-chain.service /etc/systemd/system/ ...）"
