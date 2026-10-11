#ifndef EC_MOTION_PLAN_H
#define EC_MOTION_PLAN_H

/* Motion planner: maps one item's PICK and DROP coordinates (both mm10, origin
 * = device center per interface-contract sec. 5.2) to the fixed-size
 * pick-place program executed by ec_axis_driver. Pure logic, no HAL.
 *
 * 2026-09-16 (P2): the pick point is a PARAMETER, not a constant. The two
 * removed "fixed pick waypoint" macros pinned the grasp point to the device
 * center while the drop point was the argument - the exact reverse of the task,
 * which hands the machine goods placed at random that the operator may not
 * touch. The pick point differs per item (vision); the drop point is one of six
 * fixed boxes.
 *
 * Still PLACEHOLDER awaiting the mechanical interface: the direction
 * convention, the HOME waypoint, and the servo pulse widths are not calibrated.
 * They are collected here (not scattered in ec_app.c) so a single file is the
 * "待实机确认" calibration surface.
 *
 * The mm->steps ratio (EC_AXIS_STEPS_PER_MM_X/Y = 80 steps/mm) is NOT a
 * placeholder: the user measured it 50 times (2026-09-15, ledger E-07 closed).
 */

#include "ec_axis_driver.h"

#include <stdbool.h>
#include <stdint.h>

/* Direction convention: which physical direction a POSITIVE mm coordinate maps
 * to. The mapping is:
 *   delta_mm10 >= 0 -> EC_MOTION_POSITIVE_*_DIR
 *   delta_mm10 <  0 -> the opposite direction.
 *
 * ✅ 2026-09-18 实机标定（用户最终裁定，以此为准）：
 *      X：正方向 = DIR0  → EC_DIRECTION_0
 *      Y：正方向 = DIR1  → EC_DIRECTION_1   ← **Y 要反一下才是正方向**
 *    标定方式：树莓派经 USART2 发 `MOVE X|Y DIR0|DIR1 STEPS 1600 HZ 1000`
 *    （1600 步 = 20mm = 半圈；1 圈 = 40mm = 3200 步），由用户目视判定。
 *    ⚠️ 标定过程中此宏曾反复改动（0→1→0→1），**最终以本节为准**。
 *
 * ⚠️ 若日后电机线被对调，要跟着翻修正方向的那一个轴。
 *    规律：换【某一相】的两根线 → 该轴方向反转；两相都换 → 方向不变。
 */
#define EC_MOTION_POSITIVE_X_DIR EC_DIRECTION_0
#define EC_MOTION_POSITIVE_Y_DIR EC_DIRECTION_1

/* —— 坐标域的两个边界（2026-09-15 用户裁决后必须区分）———————
 *
 * 1) 协议合法域 = ±145.0mm。这是 ITEM_TASK wire 格式的硬边界
 *    （interface-contract §5.2；镜像 EC_PROTO_ITEM_TASK_X_LIMIT）。
 *    **改它属 L4 红线（改系统间通信协议），2026-09-15 未动。**
 *
 * 2) 机械可达域必须区分「理论值」与「生效值」（2026-09-18 二次修正 + 四次修正）：
 *      X 生效 = ±95.0mm  → EC_MOTION_REACH_LIMIT_X_MM10 **950**
 *      Y 理论 = ±107.5mm → 1075（215mm 尺量全程的半程，见下）
 *      Y 生效 = ±97.5mm  → EC_MOTION_REACH_LIMIT_Y_MM10 **975**（下方 Y 轴注释取保守）
 *
 *    🔴 **二次修正的原因：X 与 Y 的实测行程此前被记反了。**
 *    旧记录（已作废）：可用行程 X = 210mm / Y = 190mm → 1050 / 950。
 *    实测复核（用户用尺手工推量，2026-09-18，单位 cm）：
 *      **X 总行程 19.0cm = 190mm → 半程 ±95.0mm  → 950**（此值即现行生效宏）
 *      **Y 总行程 21.5cm = 215mm → 半程 ±107.5mm → 1075**（理论半程，不是生效宏）
 *    ⚠️ 即旧值把 X 与 Y 记反了：X 被多算 20mm、Y 被少算 25mm。
 *    ⚠️ 旧 1050/950 与现行 950/975 的关系：X 纠正后 950 沿用至今；Y 纠正后的
 *       1075 只是理论半程，生效值再被下方 Y 轴注释收成 975（机械修复后仍留约
 *       1.5cm 不可达，超程会堵转带挂主控，故取小）。
 *
 *    🔴 **X 多算 20mm 的后果是真实事故**：固件误以为 X 可走 210mm，于是放行了
 *    16000 步（200mm）命令，而 X 实际只有 190mm —— 超出的约 10mm 脉冲全部打在
 *    硬限位上。`STEP_REMAIN` 照样递减到 0、`RESULT` 照样报 DONE，**但实际已丢步**；
 *    因该轴无回零无限位，**丢步后坐标基准即永久失准**。
 *
 *    历史沿革：165mm 全程 → ±82.5mm(825)；旧实测 245~250mm → ±105/±95（已作废）；
 *    二次复核理论值 → ±95.0/±107.5；Y 生效值 = 宏 EC_MOTION_REACH_LIMIT_Y_MM10 975。
 *
 * ⚠️ 交付命令必须落在【协议域 ∩ 生效可达域】内，即实际以宏 **950/975** 为准
 *    （不是理论 950/1075）。
 *    若只按协议域 1450 放行，会向物理上够不到的坐标发脉冲 ——
 *    而 X/Y 已不装限位开关（2026-09-15 裁决），**没有任何硬件能发现越界**，
 *    结果是丢步、位置漂移、后续落点全错。
 *
 * ⚠️ 方案 A 的连带影响：原点靠人工把机构摆到中心来建立，
 *    摆位偏差会直接吃掉可达余量。摆偏 10mm，一侧就只剩 85mm（X）。
 *    落点表必须在真实标定后填写，并保留 ≥5mm 余量。
 *
 * ⚠️ **两个轴的值不同（X≠Y），不要再合并成一个宏。**
 * ⚠️ **每次改动本组数值，都要同步 电控/calibration_config.ini 的 [WorkspaceLimits]。**
 *
 * 🔴 2026-09-19 起**正端另行收窄**（「甲′」，见下方同名小节）：上面各处的 ± 值现只当
 *    **负端**用（-950 / -975），正端各让 5mm = EC_MOTION_REACH_FAR_*（+900 / +925）。
 *    读本节时不要再把可达域当成 ±对称。
 */
#define EC_MOTION_WORKSPACE_LIMIT_MM10 1450
#define EC_MOTION_REACH_LIMIT_X_MM10 950    /* X 实测总行程 190mm，半程 ±95.0mm */
/* 🔴 Y 轴（2026-09-18 四次修正，以本行为准）：
 *    机械组于 2026-09-18 修复了 Y 末端阻挡问题，可达行程增加约 15mm。
 *    实测沿革：
 *      205mm 移动 → 撞限位 → 堵转 → 主控挂死（复现 2 次，修复前）
 *      180mm 移动 → 正常完成（修复前）
 *      **修复后：仍保留约 1.5cm 不可达 → 当前可达 ≈195mm → 半程 ±97.5mm**
 *    旧值：1075（±107.5mm，215mm 理论全程）、875（±87.5mm，修复前保守值）。
 *    ⚠️ **本值取保守侧**：若实际可达为 200mm 而按 195mm 设定，仅少用 5mm 行程；
 *       反之若按 200mm 设定而实际仅 195mm，则会出现**超程堵转并带挂主控**。
 *       故任何不确定时一律取小。
 *    ⚠️ 机械若再次调整，必须重新实测后再改本值。 */
#define EC_MOTION_REACH_LIMIT_Y_MM10 975    /* Y 当前可达 195mm，半程 ±97.5mm */

/* —— 可达域「甲′」：正负两端不再对称（2026-09-19 用户裁决）———————
 *
 *   · **负端 = EC_MOTION_REACH_LIMIT_{X,Y}_MM10**（-950 / -975）。
 *     这一端**不能动**：HOME 方案乙取的就是负方向最里角 = 上电原点，
 *     坐标正好**压在负端边界上**（HOME_X = -950、HOME_Y = -975）。
 *     若把负端收紧到 -900/-925，`ec_motion_plan.c` 里对 HOME 的校验立刻失败，
 *     整条规划每次都返回 false —— 链路全废（这是「对称收窄」方案的致命点）。
 *
 *   · **正端 = EC_MOTION_REACH_FAR_{X,Y}_MM10**（+900 / +925）。
 *     各让出 5.0mm（50 mm10）机械余量：实际行程若比实测值略短（或原点摆位有偏差），
 *     落在正端边界上的坐标会直接顶死堵转；而 X/Y 已不装限位开关，
 *     超程后 `STEP_REMAIN` 照样递减到 0、`RESULT` 照样报 DONE，**无硬件能发现**。
 *     故正端一律取小。
 *
 *  ⚠️ 生效可达域因此是 **X ∈ [-950, +900]、Y ∈ [-975, +925]**，不是 ±对称。
 *  ⚠️ 别把这两个宏和 EC_MOTION_REACH_LIMIT_* 合并回一个数 —— 合并就等于
 *     要么废掉 HOME、要么丢掉正端余量。
 *  ⚠️ 每次改动本组数值，同样要同步 电控/calibration_config.ini 的 [WorkspaceLimits]。 */
#define EC_MOTION_REACH_FAR_X_MM10 900    /* X 正端：950 让 5.0mm 余量 */
#define EC_MOTION_REACH_FAR_Y_MM10 925    /* Y 正端：975 让 5.0mm 余量 */

/* Home (rest) waypoint in the device-center frame.
 *
 * ✅ 2026-09-18 用户裁定（以本行为准）：HOME = X、Y **负方向最里角**，
 *    与落料点 (+90.0, +92.0) 的正方向最远处成对角。
 *      X: -900 (-90.0mm)   可达域 ±950 → 余量 50（5.0mm）
 *      Y: -920 (-92.0mm)   可达域 ±975 → 余量 55（5.5mm）
 *    余量与落料点取同一口径（都留 5mm）：该点是一条靠边的死角，而方案 A 的
 *    原点靠人工把机构摆到中心建立，摆偏会直接吃掉余量。
 *
 * 沿革：-1450（协议域极限，未用）→ -800（±80.0mm，2026-09-15 保守收窄，当时
 *    停放角未定）→ 本次 -900/-920。
 *
 * ⚠️ **X≠Y，不要再合并成一个宏。**
 * ⚠️ 改本组数值后**必须重算** test_motion_plan.c 里 HOME→PICK 与 PLACE→HOME
 *    两段的步数断言（steps = |Δmm10| × 8，80 步/mm）。
 */
/* 🔴 2026-09-18 实机定位（X+ 越程堵转第 3 次，无损坏）：HOME 必须等于**上电原点**。
 *
 * 原值 (-900,-920) 是"设备坐标系里靠边的停靠角"，但运动规划的第一段是
 * HOME→PICK，而下发下去的只是**增量** —— 规划假定"程序开始时滑台就在 HOME"。
 * 方案 A（用户 2026-09-15 裁决）却规定"上电位置即原点"：滑台起手在设备 (0,0)，
 * 根本不在 HOME。于是第一段被下成 PICK-HOME = (39.6+90.0, 2.2+92.0) =
 * (+129.6, +94.2)mm，而 X 真机行程只有 ±95.0mm（2026-09-18 实测 190mm）→
 * 超程 34.6mm（2768 步）全部顶在 X+ 端堵转（现场确认电机堵转声）。
 * 同时该段 X 腿 10368 步 @500Hz = 20.7s > 15s 失活窗口，虽窗口会被运动进展续命
 * （EC_APP_PROGRESS_SOURCE_ENABLED=1，见 ec_app.h:25-26）且运动期间不判超时
 * （2026-09-22），但堵转导致进展停滞 → DEADLINE_EXPIRED → FAULT_LOCK，
 * 所以 MOTION_DONE 从来不上报。**两个症状同一个根因。**
 *
 * 改成 (0,0) 后：第一段 (0,0)→PICK ≈ +39.6mm，第二段 PICK→PLACE，回程 PLACE→(0,0)，
 * 全部远在 ±95.0mm 行程内（总时长约 13s，刚好压进 15s 窗口）。
 *
 * ⚠️ 代价：机器现在停在托盘中心，不再是负方向角落的停靠位。日后若要恢复"停靠角"，
 *    必须改 ec_motion_plan.c 的组腿逻辑，把首段换成「上电原点→PICK」并另加
 *    「原点→HOME」避让腿，**不能只改这两个宏**。 */
/* 🔴 2026-09-19 方案乙（用户裁决）：上电位置 = 负方向最里角，因此 HOME 必须等于它。
 *
 * 与上面 2026-09-18 记录的那次 X+ 超程**是同一个约束**（HOME 必须等于上电原点），
 * 区别只在"上电原点"取在哪里：
 *   · 2026-09-18：方案 A 规定上电位置 = 设备中心 → 故 HOME 取 (0,0)，代价是机器
 *     停在托盘中心，且"中心"没有物理标记，只能人工摆位。
 *   · 本次方案乙：用户改用**硬限位**做基准 —— 每次上电前把滑台推到 X/Y 负方向
 *     最里角顶住，那里就是上电原点。硬限位可重复，不再依赖手摆。
 *     故 HOME 必须等于该角在**设备中心系**里的坐标 = (-95.0mm, -97.5mm)。
 *
 * ⚠️ 坐标系**不变**：线上坐标仍是设备中心系，协议合法域 ±1450 **不动**（L4 红线）。
 *    所以 PICK / 落点 / 相机中心全部继续用中心系的数
 *    （相机中心 = (65.0, -32.5)，即用户实测"距最里角 X 160mm / Y 65mm"换算而来。
 *    🔴 2026-09-19 更正：X 偏移原记 140mm → 160mm（用户实测 A + (160,65)）。
 *    此更正【不影响】已写入 电控/calibration_config.ini 的 tx/ty 标定值 ——
 *    标定锚在「夹爪确实罩住物料」这一物理结果上，不在相机中心坐标上）。
 *    只有 HOME 这个"上电位置"从中心挪到了角上。
 *
 * ⚠️ 使本改动成立的不变量：`ec_motion_plan.c` 的组腿只发**增量**，而规划假定
 *    "程序开始时滑台就在 HOME"。所以**每次上电前必须把滑台推到最里角**；
 *    否则第一段会从错误起点出发 PICK-HOME = (+160.0, +65.0)mm → 顶死堵转
 *    （与上面记录的超程事故同一成因）。
 *
 * ⚠️ 代价：路径变长（角→PICK→落点→角 ≈ 38800 步）。旧巡航 2000Hz 下约 21.7s，
 *    超过 ec_app.c:582 的 15000ms 失活窗口 → DEADLINE_EXPIRED → FAULT_LOCK。
 *    故 ec_board_stm32.c 的巡航频率同步提到 4000Hz（≈13.8s，余量约 1.2s）。
 *
 * ⚠️ 本组取值为**贴边**（正好落在可达域边界 ±950/±975），故
 *    test_motion_plan.c 的严格不等号断言已同步改为非严格 —— 原「必须留余量」
 *    的理由是"方案 A 原点靠人工摆中心建立"，改用硬限位后该理由不再成立。 */
#define EC_MOTION_HOME_X_MM10 (-950)   /* 方案乙：X 负方向最里角 = 上电原点 */
/* 🔴 2026-09-22：HOME 迁到 Y 正端停车位 (+855) 的尝试【已实施、已独立审核、已回退】。
 * 保留记录以免后人重走 —— 结论是【弊大于利】：
 *   ① 它把上电原点从「硬限位基准」（:170 原话"硬限位可重复，不再依赖手摆"）
 *      改成「无参照的记忆位」⇒ 取消唯一的绝对基准，误差源从"可复现的常量"
 *      变成"每次上电独立重采、不可测量"的量。
 *   ② 收益被高估：逐件复算 6 件（现场抓取点 + [DropPoints]）——
 *      4 件变快、**2 件变慢**，单件最坏值 15.08s → 15.51s；6 件合计只省 5.4s。
 *   ③ 一致性代价大：仓内 13 处面向操作员的旧仪式提示 + 3 处机器校验需同步
 *      （run_chain.py:624、10 个 pi_side/sh 脚本、planner.py:437 等），
 *      只改一处等于留下互斥指令。
 *   ④ 触发它的问题（夹爪被判成黑色件）属视觉侧，与 HOME 无关。
 * ⇒ 正确动法（若日后仍要移）是第三条路：HOME 许可到 +975 而命令上限仍留 +925，
 *   以保住"顶住即可复现"；而不是 +855 这种无参照位。 */
#define EC_MOTION_HOME_Y_MM10 (-975)   /* 方案乙：Y 负方向最里角 = 上电原点（硬限位，可重复） */

/* 🔴 2026-09-22 用户裁决：【每件程序的停靠位】= 第二落点（避让位）。
 * 为什么：夹爪常驻 HOME（负端角落）时，相机会把夹爪的黑色判成"黑色圆柱"并派件
 *   （现场实测第 7 件就是误判夹爪的黑色）。PARK 在相机画面之外 ⇒ 拍照时画面里没有夹爪，
 *   误判消失。**用户 2026-09-22 现场确认"夹爪停在第二落点时看不到夹爪"**。
 * ⚠️ 与 HOME 的分工（别混）：HOME = 【上电原点】= 硬限位，不变量不变（见 :145 那段）；
 *   PARK = 【程序起止位】= leg1 的起点、leg3 的终点 ⇒ 每件增量假定"开始时滑台在 PARK"，
 *   靠"每件结束回 PARK"闭环；而【起轮前必须先把滑台从 HOME 送到 PARK】（链侧 p_go8.sh 两行）。
 * 为什么不改 HOME 只改 PARK：HOME 迁到 +Y 端会让上电原点失去"顶住即可复现"的硬基准
 *   （2026-09-22 独立审核判弊大于利、已回退，记录见本文件上方那段）；改 PARK 完全不碰基准、
 *   不碰坐标系、不碰标定、不碰上电仪式。
 * 取值：第二落点 = Pi sorting_config.ini 的 [DropPoints] 2 = (-95.0, 47.5)。
 *   X 与 HOME_X 同值 ⇒ 本改动【只影响 leg1 / leg3 的 Y 腿】，X 腿逐字节不变。
 *   副产品：落点恰为第二落点的那两件（2 号 / 5 号）回程腿长度为 0 ⇒ 不增加时间。 */
#define EC_MOTION_PARK_X_MM10 (-950)   /* = 第二落点 X（与 HOME_X 同值；独立常量便于日后分开调） */
#define EC_MOTION_PARK_Y_MM10 (+475)   /* = 第二落点 Y（+47.5mm） */

/* XY order for the two UNLOADED legs (HOME->PICK and PLACE->HOME).
 * 1 = X then Y, 0 = Y then X for those two legs as well.
 *
 * 🔴 2026-09-21 **用户现场裁决：置 0（三条腿全部「先 Y 后 X」）**。
 *    用户口径原文：「要先 Y 先走，Y 先走到那一行之后，然后再变脉宽，然后再去夹取；
 *    如果是 X 先走，他在变脉宽的过程当中很可能扫到其他物块。」
 *    ⇒ 空爪去取料时也先竖着走到目标那一行、再横着过去。
 *    （本节点此前的分析倾向 X 先，理由是 leg1 的 X 段走在 y=HOME_Y=−97.5、在件区之外；
 *      用户现场目视认为 X 先会碰到，且他人在机器旁 —— **以现场为准**。）
 *
 * ⚠️ 回退：本宏改回 1 重编即可（配合 EC_MOTION_CARRY_LEG_Y_FIRST=1 即回到 2026-09-21 之前
 *    逐字节的行为）。**一处宏、一次重编，不改代码。**
 *
 * 🔴 语义（2026-09-21 收窄）：PICK→PLACE（夹着件那条腿）**不再受本宏控制** ——
 *    它恒为「先 Y 后 X」，由下面的 EC_MOTION_CARRY_LEG_Y_FIRST 单管。
 * Each waypoint emits up to two complete single-axis moves, never a diagonal
 * MOVE_XY command. */
#ifndef EC_MOTION_XY_ORDER_X_FIRST
#define EC_MOTION_XY_ORDER_X_FIRST 0
#endif

/* 带料腿（PICK→PLACE）是否强制「先 Y 后 X」。1 = 是（2026-09-21 用户裁决，默认）。
 *
 * 为什么：夹着件在托盘上方沿 X 横穿会把同排其他件刮飞。先沿 +Y 退出托盘、再在盘外横移
 * ⇒ 带料段在托盘内腔里的**横向扫掠归零**。
 * ⚠️ 前提：**落点 y 必须在托盘内腔之外**。注意件自身还占 ±20mm，所以"中心出盘"不等于
 *    "件出盘" —— 落点 y 至少要高出内腔上界 20mm 才算真的整件出盘。
 *    现测三个落点 y = +47.5 / +47.5 / +87.5，**均满足**（旧落点 +19.0 不满足，这条正是
 *    把落点往外挪的原因）。**固件不认识托盘几何，这条只能在落点配置侧兜。**
 * 🔴 **单点回退开关**：在 EC_MOTION_XY_ORDER_X_FIRST 保持 1 的前提下把它改 0
 *    （或工程宏 -DEC_MOTION_CARRY_LEG_Y_FIRST=0）重编，三条腿全部回到 X 优先
 *    = 2026-09-21 之前的逐字节行为。
 * ⚠️ 实现是 `y_then_x = force_y_first || (EC_MOTION_XY_ORDER_X_FIRST == 0)`，
 *    所以 **ORDER=0 时本宏失效（三条腿都 Y 优先）** —— 那是刻意的"全路径 Y 优先"AB 开关，
 *    不是 bug。**要回退就只动本宏、别动 ORDER。**
 * ⚠️ 不要用 EC_MOTION_XY_ORDER_X_FIRST 来回退 —— 它一翻会把两条空爪腿也变成 Y 优先。 */
#ifndef EC_MOTION_CARRY_LEG_Y_FIRST
#define EC_MOTION_CARRY_LEG_Y_FIRST 1
#endif

/* ── 按类别选张开脉宽（2026-09-21 现场实测；用户裁决本项优先于他此前说的"脉宽定住不要再调"）──
 * 6 类 → **恰好 3 个取值**，键 = class_id（1..6）。
 * 现场标定（docs/交付/2026-09-21/现场脉宽标定记录-2026-09-21.md）：
 *     正方体 class 1/2 = 650µs ｜ 三棱柱 class 3/4 = 750µs ｜ 圆柱 class 5/6 = 800µs
 * 三个值均在**托盘最高点**（−X 侧偏高 2~3mm）实测留有余量，判据是"爪片与件明显有空隙"
 * （刻意不取"刚好不碰"—— 件只要摆偏几毫米就会从"不碰"变成"刮飞"）。
 * ⚠️ 本值同时是 [0]（HOME 处初始张开）与 [7]（落料点释放）两处的开度，而机构是
 *    **单舵机联动**（张开=抬起、闭合=下压）⇒ 它也同时决定这两处的高度。
 * ⚠️ 这三个值必须落在台架白名单里（ec_servo_test.c 的 is_allowed_pulse() 与
 *    ec_diag.c 的命令表，两处必须同步），否则台架没法复现/回退扫描。 */
/* ── 开度时序（2026-09-22 现场裁决，推翻 2026-09-21 方案）───────────────
 * 🔴 **[0] 起点用固定待机开度 625µs，到取料点 [3] 才降到该件类别的开度。**
 * 用户原话：「他要先移动到那个位置之后，它先降到那个脉宽，然后再降一次」。
 *
 * 为什么必须改成固定值：本舵机是**单轴联动**，同一脉宽同时决定升降与开合
 * （ec_axis_driver.h:99-101）；脉宽越小 = 抬起越高 + 张开越大
 * ⇒ 起点写类别值时，起点高度**逐件不同**（650 最高、800 最低），
 *   现场表现为"刚开始的高度不一样、不对"。
 * 625 同时满足：比三类开度都宽（穿行/回程不刮走托盘上其他件）
 *   + 三类里抬起最高（起点高度对所有件统一）。
 *
 * ⇒ [0] 固定 625、[3] 降到类别开度、[7] 落料释放仍用类别开度、
 *   [9] 回程前切回 625（2026-09-21 裁决，避免回程刮件）。
 *
 * ⚠️ 2026-09-21 方案已废弃：当时要求"识别到件就切类别开度、[0] 就用类别值"，
 *    2026-09-22 现场实测发现起点高度不一致问题后推翻。见 ec_motion_plan.c:251-262。 */
#define EC_MOTION_OPEN_US_CUBE     UINT16_C(650)
#define EC_MOTION_OPEN_US_PRISM    UINT16_C(750)
#define EC_MOTION_OPEN_US_CYLINDER UINT16_C(800)

/* class_id → 张开脉宽。0 / 未知 / 非法值一律退回 EC_AXIS_GRIPPER_OPEN_US（默认值），
 * 绝不把 0 或 ≥闭合端的值下发到舵机（fail-closed）。 */
uint16_t ec_motion_plan_open_us_for_class(uint8_t class_id);

/* Build the pick-place program for one item: HOME -> PICK -> Z down (open) ->
 * Z up (close = grab) -> PLACE -> Z down (open = release) -> Z up (close =
 * ready) -> HOME. PICK is the grasp point (per item, from vision); PLACE is
 * the drop point (a fixed box). Each XY waypoint is emitted as a sequential
 * pair of single-axis MOVE steps (X then Y by default); step counts and
 * directions are derived from the mm coordinates.
 *
 * Returns false (and leaves *out untouched) if EITHER waypoint falls outside
 * the workspace/reach intersection - see the boundary note above; the reach
 * domain is ASYMMETRIC since 2026-09-19: X in [-950, +900], Y in [-975, +925]
 * (negative end = EC_MOTION_REACH_LIMIT_*_MM10, HOME sits exactly on it;
 * positive end = EC_MOTION_REACH_FAR_*_MM10, 5.0mm mechanical margin).
 * Both pairs are checked because both are commanded, and X/Y carry no limit
 * switch to catch an overrun. */
/* 2026-09-21 新增：与 ec_motion_plan_build() **同参数，只多一个张开脉宽**。
 * 用于"按类别选张开脉宽"（见上面的 EC_MOTION_OPEN_US_* 与 ec_motion_plan_open_us_for_class）。
 * 之所以用"新入口 + 老入口包装"而不是给老函数加形参：老签名在 tests/test_motion_plan.c 里
 * 有 22 处调用，加形参要把一份有价值的回归测试改成一堆 `, 800` 噪音；包装方案把改动压到 1 行。 */
bool ec_motion_plan_build_with_open(ec_axis_pick_place_t *out,
                                    int16_t pick_x_mm10, int16_t pick_y_mm10,
                                    int16_t place_x_mm10, int16_t place_y_mm10,
                                    uint16_t open_pulse_us);

bool ec_motion_plan_build(ec_axis_pick_place_t *out,
                          int16_t pick_x_mm10, int16_t pick_y_mm10,
                          int16_t place_x_mm10, int16_t place_y_mm10);

/* Interpolated variant (ec_motion_plan_interp.c): same pick-place sequence,
 * but the waypoint moves are EC_AXIS_STEP_XY_INTERP steps with signed
 * target_x_steps/target_y_steps instead of counted MOVE_XY steps.
 * Same pick + place arguments, same dual workspace/reach validation on both
 * pairs, and the same false return as ec_motion_plan_build().
 * [EXPERIMENTAL - 待实测验证]
 *
 * 🔴 2026-09-22：**该实现不参与现行构建** —— Keil 工程 `MDK-ARM/diankongv1.0.uvprojx`
 *   没有收 `App/Src/ec_motion_plan_interp.c`（只收了 `ec_motion_plan.c`），7 个主机
 *   测试目标也都不编它 ⇒ **板子上跑的不是这条路线，改动它不会被任何测试跑到**。
 *   只有显式切到 XY 插补时才生效（`docs/XY插补-快速启动.md:84`）。要改它，请同时改
 *   `ec_motion_plan.c`（串行版是唯一在跑的那份），并单独 gcc -c 验证语法。 */
bool ec_motion_plan_build_interp(ec_axis_pick_place_t *out,
                                 int16_t pick_x_mm10, int16_t pick_y_mm10,
                                 int16_t place_x_mm10, int16_t place_y_mm10);

#endif
