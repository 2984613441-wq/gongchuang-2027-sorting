#!/bin/sh
# 给树莓派添加一个 WiFi 网络（换热点用，例如换到 Ziyann 的 iPhone）。
#
# 用法（在树莓派本机跑，不是在你 PC 上）：
#   sudo sh pi_add_wifi.sh "Ziyann的iPhone" "48115888"
#
# 为什么要在本机跑：换热点是先有鸡还是先有蛋 —— 树莓派得先连上她的热点，
# 你才能远程 ssh 进去。所以第一次必须在本机（屏幕+键盘）执行。
#
# 兼容两套网络栈：
#   · NetworkManager（Bookworm 及以后）→ 用 nmcli
#   · dhcpcd + wpa_supplicant（Bullseye 及以前）→ 写 wpa_supplicant.conf
# 脚本自己判断用哪套，不用你先查。
#
# 安全：会先备份原配置（同目录 .bak-时间戳），失败可原样还原。

set -e

SSID="$1"
PSK="$2"

if [ -z "$SSID" ] || [ -z "$PSK" ]; then
    echo "用法: sudo sh $0 \"<SSID>\" \"<密码>\""
    exit 2
fi

if [ "$(id -u)" != "0" ]; then
    echo "需要 root：请用 sudo 跑"
    exit 2
fi

# 密码长度合法性检查（WPA2-PSK 为 8~63 个字符）
LEN=$(printf '%s' "$PSK" | wc -c | tr -d ' ')
if [ "$LEN" -lt 8 ] || [ "$LEN" -gt 63 ]; then
    echo "密码长度 $LEN 不在 WPA2-PSK 允许的 8~63 范围内，拒绝写入"
    exit 2
fi

echo "=== 目标 SSID: $SSID ==="

# ---------- 路线 1：NetworkManager ----------
if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
    echo "检测到 NetworkManager，走 nmcli"
    # 同名连接先删掉，避免残留旧密码导致连不上
    nmcli connection delete "$SSID" >/dev/null 2>&1 || true
    nmcli dev wifi connect "$SSID" password "$PSK"
    echo "--- 结果 ---"
    nmcli -f DEVICE,STATE,CONNECTION dev status
    nmcli -f IP4.ADDRESS,IP4.GATEWAY dev show wlan0 2>/dev/null || true
    echo "OK：已用 NetworkManager 连上 $SSID"
    exit 0
fi

# ---------- 路线 2：wpa_supplicant ----------
CONF=""
for c in /etc/wpa_supplicant/wpa_supplicant-wlan0.conf \
         /etc/wpa_supplicant/wpa_supplicant.conf; do
    [ -f "$c" ] && CONF="$c" && break
done

if [ -z "$CONF" ]; then
    echo "两套网络栈都没找到，且 $CONF 不存在。"
    echo "请先在本机确认网络栈： systemctl is-active NetworkManager wpa_supplicant"
    exit 3
fi

cp -a "$CONF" "$CONF.bak-$(date +%Y%m%d-%H%M%S)"
echo "已备份 -> $CONF.bak-*"

if grep -q "ssid=\"$SSID\"" "$CONF" 2>/dev/null; then
    echo "SKIP：$SSID 已在 $CONF 里，不重复追加"
else
    if command -v wpa_passphrase >/dev/null 2>&1; then
        # wpa_passphrase 会额外吐一行 '#psk="明文"' 注释，必须滤掉
        wpa_passphrase "$SSID" "$PSK" \
            | grep -v '^[[:space:]]*#' \
            | grep -v '^[[:space:]]*psk="' >> "$CONF"
    else
        printf '\nnetwork={\n\tssid="%s"\n\tpsk="%s"\n}\n' "$SSID" "$PSK" >> "$CONF"
    fi
    echo "已写入 $CONF"
fi

wpa_cli -i wlan0 reconfigure 2>/dev/null \
    || systemctl restart wpa_supplicant 2>/dev/null \
    || systemctl restart "wpa_supplicant@wlan0" 2>/dev/null \
    || true

sleep 5
echo "--- wlan0 地址 ---"
ip -4 addr show wlan0 2>/dev/null || true
echo "OK：已写入 $CONF 并触发重连"
