/* div.c : RV32M divide: DIV, DIVU, REM, REMU.
 * RISC-V rules: x / 0 = -1 (all ones), x % 0 = x, INT_MIN / -1 = INT_MIN, INT_MIN % -1 = 0,
 * quotient rounds toward zero, remainder has the sign of the dividend.
 * (In C, x / 0 and INT_MIN / -1 are undefined; the inputs are volatile, so the compiler
 * just emits the instruction and we see what the hardware does.)
 *   make div   (from the project folder or extras/)
 * Inputs are volatile, so the processor really executes the instruction at run time.
 * Every result is compared with the expected value (computed by RISC-V rules);
 * errors = number of wrong results (0 = all correct). */
#include <stdint.h>
#define N 8
/* cases: 100/7, -100/7, INT_MIN/-1, 7/0, -7/2, 4e9/7 (unsigned vs signed), 0/5, 0xDEADBEEF/-256 */
volatile uint32_t in_a[N] = {0x00000064u, 0xFFFFFF9Cu, 0x80000000u, 0x00000007u, 0xFFFFFFF9u, 0xEE6B2800u, 0x00000000u, 0xDEADBEEFu};
volatile uint32_t in_b[N] = {0x00000007u, 0x00000007u, 0xFFFFFFFFu, 0x00000000u, 0x00000002u, 0x00000007u, 0x00000005u, 0xFFFFFF00u};
volatile uint32_t q_s[N];
volatile uint32_t r_s[N];
volatile uint32_t q_u[N];
volatile uint32_t r_u[N];
volatile uint32_t errors;

static const uint32_t exp_q_s[N] = {0x0000000Eu, 0xFFFFFFF2u, 0x80000000u, 0xFFFFFFFFu, 0xFFFFFFFDu, 0xFD7D05B7u, 0x00000000u, 0x00215241u};
static const uint32_t exp_r_s[N] = {0x00000002u, 0xFFFFFFFEu, 0x00000000u, 0x00000007u, 0xFFFFFFFFu, 0xFFFFFFFFu, 0x00000000u, 0xFFFFFFEFu};
static const uint32_t exp_q_u[N] = {0x0000000Eu, 0x24924916u, 0x00000000u, 0xFFFFFFFFu, 0x7FFFFFFCu, 0x220F4EDBu, 0x00000000u, 0x00000000u};
static const uint32_t exp_r_u[N] = {0x00000002u, 0x00000002u, 0x80000000u, 0x00000007u, 0x00000001u, 0x00000003u, 0x00000000u, 0xDEADBEEFu};

int main(void) {
    uint32_t bad = 0;
    for (int i = 0; i < N; i++) {
        uint32_t a = in_a[i], b = in_b[i];
        q_s[i] = (uint32_t)((int32_t)a / (int32_t)b);
        r_s[i] = (uint32_t)((int32_t)a % (int32_t)b);
        q_u[i] = a / b;
        r_u[i] = a % b;
        bad += q_s[i] != exp_q_s[i];
        bad += r_s[i] != exp_r_s[i];
        bad += q_u[i] != exp_q_u[i];
        bad += r_u[i] != exp_r_u[i];
    }
    errors = bad;
    return 0;
}
