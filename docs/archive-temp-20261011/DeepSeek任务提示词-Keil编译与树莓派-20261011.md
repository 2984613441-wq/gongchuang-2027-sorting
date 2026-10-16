# DeepSeek任务提示词 - Keil编译 + 树莓派WiFi

**生成时间**: 2026-10-11  
**目标AI**: DeepSeek / 其他支持代码执行的AI

---

## 📋 任务A：Keil工程编译（优先）

```
我有一个STM32F407的Keil MDK工程，需要你帮我编译。

**工程信息**:
- 工程路径: C:\Users\29845\Desktop\工创赛\电控\firmware\stm32f407_m144z\MDK-ARM\diankongv1.0.uvprojx
- 芯片型号: STM32F407ZGT6
- IDE: Keil MDK-ARM (MDK5)
- 最近修改: 添加了气动夹爪测试代码

**需要你做的**:
1. 检查Keil是否已安装（如果没有，告诉我怎么快速安装）
2. 在Keil工程中添加源文件：
   - 文件路径: C:\Users\29845\Desktop\工创赛\电控\firmware\stm32f407_m144z\App\Src\ec_pneumatic_gripper.c
   - 添加到工程树的 Application/User/App 组
3. 编译工程（按F7或点击编译按钮）
4. 告诉我编译结果：
   - 成功：告诉我生成的.hex文件路径
   - 失败：给我完整的错误信息

**已修改的文件**:
- main.c: 已添加 #include "ec_pneumatic_gripper.h" 和初始化调用
- ec_pneumatic_gripper.c/h: 新增的气动夹爪驱动代码

**如果编译出错**:
把完整的错误日志发给我，包括：
- Error信息
- Warning信息
- 出错的文件名和行号

请一步步操作并告诉我每步的结果。
```

---

## 📋 任务B：树莓派WiFi连接排查（如果还有问题）

```
我的树莓派4B之前能连接手机热点，现在突然连不上了。

**环境信息**:
- 设备: 树莓派4B 2GB
- 操作系统: Raspberry Pi OS
- 手机: [您的手机型号]，系统: [Android/iOS版本]
- 热点名称: [如果方便透露]
- 最近改动: 刚刚从GPIO引脚供电（物理引脚4接5V，引脚6接GND）

**可用的操作方式**:
- HDMI屏幕已连接，可以直接在树莓派上操作
- 可以访问树莓派终端

**请帮我**:
1. 列出最可能的5个原因（按概率排序）
2. 给出每个原因的诊断命令（我可以在树莓派终端执行）
3. 给出对应的解决方案
4. 如果是手机热点设置问题，告诉我怎么改

**特别关注**:
- 是否和供电方式改变有关？（刚从独立适配器改为GPIO供电）
- 是否是2.4GHz/5GHz频段问题？
- 是否是欠压导致WiFi模块不工作？

**诊断命令集**（你可以要求我在树莓派上运行）:
```bash
# 检查WiFi硬件状态
ifconfig wlan0

# 扫描可用热点
sudo iwlist wlan0 scan | grep -E "ESSID|Quality|Frequency" | head -20

# 检查欠压（供电问题）
vcgencmd get_throttled

# 检查WiFi是否被禁用
rfkill list

# 查看WiFi配置文件
sudo cat /etc/wpa_supplicant/wpa_supplicant.conf

# 查看连接状态
iwconfig wlan0

# 查看系统日志
sudo journalctl -u wpa_supplicant -n 30 --no-pager
```

请一步步指导我排查。如果需要我在树莓派上运行命令，我会把输出粘贴给你。
```

---

## 📱 如果DeepSeek说需要手机热点设置

**追加提示词**:
```
我的手机是 [品牌和型号]，系统是 [Android/iOS 版本]。

请告诉我：
1. 如何查看当前热点使用的是2.4GHz还是5GHz
2. 如何将热点改为2.4GHz（树莓派4B的BCM43455芯片不支持5GHz）
3. 具体的菜单路径（一步步告诉我怎么点）

注意：树莓派之前能连上这个热点，只是今天改了供电方式后连不上了。
```

---

## 🔧 如果DeepSeek需要额外信息

### Keil工程结构
```
MDK-ARM/
├── diankongv1.0.uvprojx          # 工程文件
├── diankongv1.0.uvoptx           # 选项文件
├── Objects/                      # 编译输出
│   └── diankongv1.0.hex          # 生成的hex文件（如果编译成功）
└── Listings/                     # 编译日志

工程树结构:
Application/User/
├── Core/ (已有main.c等)
├── App/  (这里应该添加 ec_pneumatic_gripper.c)
├── Drivers/
└── ...
```

### Include路径（如果编译找不到头文件）
应该包含:
- `../App/Inc`（气动夹爪头文件在这里）
- `../Core/Inc`
- `../Drivers/STM32F4xx_HAL_Driver/Inc`
- `../Drivers/CMSIS/Device/ST/STM32F4xx/Include`
- `../Drivers/CMSIS/Include`

### 供电信息（树莓派相关）
```
当前供电方案:
DCP3512降压模块 5V输出
    ↓
树莓派物理引脚4 (5V)
树莓派物理引脚6 (GND)

之前: 独立5V/3A适配器 → USB Type-C口供电
现在: GPIO引脚供电（可能欠压？）
```

---

## 📊 预期输出

### Keil编译成功
```
Build target 'diankongv1.0'
compiling ec_pneumatic_gripper.c...
compiling main.c...
linking...
Program Size: Code=45678 RO-data=1234 RW-data=567 ZI-data=8901
"Objects\diankongv1.0.axf" - 0 Error(s), 0 Warning(s).

生成文件: 
C:\Users\29845\Desktop\工创赛\电控\firmware\stm32f407_m144z\MDK-ARM\Objects\diankongv1.0.hex
```

### 树莓派WiFi恢复
```
wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.x.x  netmask 255.255.255.0  broadcast 192.168.x.255
        ...

WiFi已连接到: [您的热点名称]
IP地址: 192.168.x.x
ping 8.8.8.8: 正常
```

---

## 🆘 如果DeepSeek遇到问题

**回来告诉我**:
1. Keil编译的具体错误（截图或文字）
2. 树莓派诊断命令的输出
3. DeepSeek建议的解决方案（我可以帮你评估）

---

## ✅ 任务完成标志

**Keil编译**:
- [ ] 成功编译，无Error无Warning
- [ ] 生成 .hex 文件
- [ ] 文件大小合理（约40-50KB）

**树莓派WiFi**:
- [ ] WiFi图标显示已连接
- [ ] 能ping通8.8.8.8
- [ ] SSH能连接（如果需要）

---

**生成时间**: 2026-10-11  
**下次更新**: 根据DeepSeek执行结果
