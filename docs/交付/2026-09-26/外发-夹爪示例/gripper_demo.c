/* gripper_demo.c
 *
 * 夹爪取放程序示例（单文件）。
 *
 * 思路：把一次取放拆成若干"步"放进一张表里，由一个简单的状态机逐步执行。
 *       每一步有自己的持续时间，时间到了就切下一步，主循环不阻塞。
 *
 * 端口层用打印模拟，所以在电脑上就能跑；接到真实机构时，
 * 只需替换下面三个 port_ 开头的函数。
 *
 * 舵机脉宽填的是通用示例值，不是实测值，上机前需要自己标定。
 *
 * 编译： gcc -std=c99 -Wall -Wextra gripper_demo.c -o gripper_demo
 * 运行： ./gripper_demo
 */

#include <stdio.h>
#include <time.h>

/* ---------------- 可调参数 ---------------- */

#define SERVO_OPEN_US   1000   /* 张开脉宽，示例值，需自行标定 */
#define SERVO_CLOSE_US  2000   /* 闭合脉宽，示例值，需自行标定 */

#define SERVO_SETTLE_MS  300   /* 发完脉宽后等机构走到位的时间 */
#define MOVE_MS          500   /* 一次滑台移动的耗时 */
#define PAUSE_MS         200   /* 到位后停一下再继续 */

#define PICK_X   10
#define PICK_Y   20
#define DROP_X   80
#define DROP_Y   60

/* ---------------- 端口层 ----------------
 * 接真实硬件时只改这三个函数：一个发脉宽、一个走滑台、一个取时间。
 */

static void port_servo_us(int us)
{
    printf("      舵机脉宽 %d us\n", us);
}

static void port_move_xy(int x, int y)
{
    printf("      滑台移动到 (%d, %d)\n", x, y);
}

static unsigned port_now_ms(void)
{
    return (unsigned)((clock() * 1000) / CLOCKS_PER_SEC);
}

/* ---------------- 动作表 ---------------- */

enum step_kind {
    STEP_MOVE,
    STEP_GRIPPER,
    STEP_PAUSE
};

struct step {
    int kind;
    int x;
    int y;
    int pulse_us;
    int duration_ms;
};

static const struct step program[] = {
    { STEP_GRIPPER, 0,      0,      SERVO_OPEN_US,   SERVO_SETTLE_MS },
    { STEP_MOVE,    PICK_X, PICK_Y, 0,               MOVE_MS         },
    { STEP_PAUSE,   0,      0,      0,               PAUSE_MS        },
    { STEP_GRIPPER, 0,      0,      SERVO_CLOSE_US,  SERVO_SETTLE_MS },
    { STEP_MOVE,    DROP_X, DROP_Y, 0,               MOVE_MS         },
    { STEP_PAUSE,   0,      0,      0,               PAUSE_MS        },
    { STEP_GRIPPER, 0,      0,      SERVO_OPEN_US,   SERVO_SETTLE_MS },
    { STEP_MOVE,    0,      0,      0,               MOVE_MS         }
};

#define PROGRAM_STEPS ((int)(sizeof(program) / sizeof(program[0])))

/* ---------------- 状态机 ---------------- */

static int current_step;
static unsigned step_started_ms;

static void start_step(int index)
{
    const struct step *s = &program[index];

    printf("  [%d/%d] 开始\n", index + 1, PROGRAM_STEPS);

    switch (s->kind) {
    case STEP_MOVE:
        port_move_xy(s->x, s->y);
        break;

    case STEP_GRIPPER:
        port_servo_us(s->pulse_us);
        break;

    default:
        /* 暂停步不驱动任何东西 */
        break;
    }

    step_started_ms = port_now_ms();
}

static void run_program(void)
{
    current_step = 0;
    start_step(current_step);

    while (current_step < PROGRAM_STEPS) {
        const struct step *s = &program[current_step];

        if (port_now_ms() - step_started_ms >= (unsigned)s->duration_ms) {
            current_step++;
            if (current_step < PROGRAM_STEPS) {
                start_step(current_step);
            }
        }
    }
}

int main(void)
{
    printf("=== 夹爪取放示例 ===\n");

    run_program();

    printf("=== 完成 ===\n");
    return 0;
}
