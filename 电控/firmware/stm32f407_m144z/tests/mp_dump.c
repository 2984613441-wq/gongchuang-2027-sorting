/* 把 ec_motion_plan 真正生成的步骤逐步打印出来（主机侧，纯逻辑，不碰硬件）。
 *
 * 用途：现场说"到了落点、放完料之后它继续朝 +Y 往前走，不回 HOME"。
 * 计划层看着是对的（回归测试断言了最后一腿是反向），所以把**固件实际生成的
 * 每一步**打印出来，逐条核对 轴/步数/方向。
 *
 * 编译（与 tests/CMakeLists.txt 的 ec_motion_plan_tests 同一套 flag）：
 *   gcc -std=c11 -Wall -Wextra -Werror -pedantic -I../App/Inc \
 *       -I../../../stm32_logic/include mp_dump.c ../App/Src/ec_motion_plan.c \
 *       ../App/Src/ec_axis_driver.c -o mp_dump.exe
 */
#include "ec_motion_plan.h"
#include "ec_axis_driver.h"
#include "ec_inputs.h"
#include "ec_servo_test.h"
#include <stdio.h>

/* 与 test_motion_plan.c 相同的端口替身（仅供链接）。 */
bool ec_step_port_set_direction(ec_axis_t a, ec_direction_t d) { (void)a; (void)d; return true; }
bool ec_step_port_enable_axis(ec_axis_t a) { (void)a; return true; }
bool ec_step_port_start_counted(ec_axis_t a, uint32_t f, uint32_t s) { (void)a; (void)f; (void)s; return true; }
bool ec_step_port_enable_xy(void) { return true; }
bool ec_step_port_start_counted_xy(uint32_t xs, uint32_t xf, uint32_t ys, uint32_t yf)
{ (void)xs; (void)xf; (void)ys; (void)yf; return true; }
void ec_step_port_stop_all(void) { }
void ec_step_port_disable_all(void) { }
uint32_t ec_step_port_now_ms(void) { return 0U; }
uint32_t ec_step_port_counted_remaining(void) { return 0U; }
uint32_t ec_step_port_counted_target(void) { return 0U; }
bool ec_step_port_take_counted_completion(ec_axis_t *c) { if (c) *c = EC_AXIS_NONE; return false; }
bool ec_step_port_take_counted_abort(void) { return false; }
bool ec_servo_port_start_z(uint16_t p) { (void)p; return true; }
void ec_servo_port_stop_z(void) { }
bool ec_servo_port_start(uint16_t p) { (void)p; return true; }
void ec_servo_port_stop(void) { }

static const char *dir_name(ec_direction_t d)
{
    if (d == EC_DIRECTION_0) return "DIR0";
    if (d == EC_DIRECTION_1) return "DIR1";
    return "?";
}

/* 一个 case：把该件的 (pick, place) 逐步打印。 */
static void dump(const char *tag, int16_t px, int16_t py, int16_t qx, int16_t qy,
                 uint16_t open_us)
{
    ec_axis_pick_place_t p;
    printf("\n=== %s ===\n", tag);
    printf("HOME=(%d,%d)  PICK=(%d,%d)  PLACE=(%d,%d)  open=%uus\n",
           EC_MOTION_HOME_X_MM10, EC_MOTION_HOME_Y_MM10, px, py, qx, qy, open_us);
    printf("POSITIVE_X_DIR=%s  POSITIVE_Y_DIR=%s  XY_ORDER_X_FIRST=%d\n",
           dir_name(EC_MOTION_POSITIVE_X_DIR), dir_name(EC_MOTION_POSITIVE_Y_DIR),
           (int)EC_MOTION_XY_ORDER_X_FIRST);

    if (!ec_motion_plan_build_with_open(&p, px, py, qx, qy, open_us)) {
        printf("!! build 失败（越界或超步数）\n");
        return;
    }
    /* 找出实际用了几步：第一个全零槽之前都是有效步。 */
    size_t used = 0;
    for (size_t i = 0; i < EC_AXIS_PICK_PLACE_STEP_COUNT; ++i) {
        const ec_axis_step_t *s = &p.step[i];
        bool empty = (s->kind == EC_AXIS_STEP_MOVE) && (s->axis == EC_AXIS_NONE) &&
                     (s->steps == 0U) && (s->y_steps == 0U) &&
                     (s->servo_pulse_us == 0U);
        if (!empty) used = i + 1U;
    }
    for (size_t i = 0; i < used; ++i) {
        const ec_axis_step_t *s = &p.step[i];
        printf("  [%2u] ", (unsigned)i);
        if (s->kind == EC_AXIS_STEP_Z_SERVO || s->kind == EC_AXIS_STEP_GRIPPER) {
            printf("Z_SERVO   pulse=%u us\n", (unsigned)s->servo_pulse_us);
        } else if (s->kind == EC_AXIS_STEP_WAIT) {
            printf("WAIT      %u ms\n", (unsigned)s->servo_pulse_us);
        } else if (s->kind == EC_AXIS_STEP_MOVE) {
            printf("MOVE      axis=%s  steps=%-6lu dir=%s\n",
                   (s->axis == EC_AXIS_X) ? "X" : "Y",
                   (unsigned long)s->steps, dir_name(s->direction));
        } else {
            printf("kind=%d (其它)\n", (int)s->kind);
        }
    }
    printf("  共 %u 步（容量 %u）\n", (unsigned)used,
           (unsigned)EC_AXIS_PICK_PLACE_STEP_COUNT);
}

int main(void)
{
    /* 今晚 20:12 实测那一件：class_id=5 黑圆柱 */
    dump("今晚实测第1件（黑圆柱, 货格5, 落点(-950,475)）",
         -327, -587, -950, 475, 800U);
    /* 20:12 第3件：青正方体，自己的落点 (-430, 875) */
    dump("今晚实测第3件（青正方体, 货格1, 落点(-430,875)）",
         -266, -370, -430, 875, 650U);
    /* 一个"取料点在 +X 侧"的对照例：看 X 腿方向 */
    dump("对照：PICK 在 +X 侧 / PLACE 在中部",
         600, -400, 450, 475, 750U);
    return 0;
}
