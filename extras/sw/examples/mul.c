/* mul.c : RV32M multiply: MUL, MULH, MULHU, MULHSU.
 * The high-word results come from 64-bit products (signed x signed, unsigned x unsigned,
 * signed x unsigned); also 10! with a loop.
 *   make mul   (from the project folder or extras/)
 * Inputs are volatile, so the processor really executes the instruction at run time.
 * Every result is compared with the expected value (computed by RISC-V rules);
 * errors = number of wrong results (0 = all correct). */
#include <stdint.h>
#define N 8
volatile uint32_t in_a[N] = {0x00000005u, 0xFFFFFFFDu, 0x7FFFFFFFu, 0xFFFFFFFFu, 0x075BCD15u, 0x80000000u, 0x00000000u, 0xDEADBEEFu};
volatile uint32_t in_b[N] = {0x00000007u, 0x0000000Au, 0x00000001u, 0xFFFFFFFFu, 0x3ADE68B1u, 0x80000000u, 0x12345678u, 0x01234567u};
volatile uint32_t lo[N];
volatile uint32_t hi_ss[N];
volatile uint32_t hi_uu[N];
volatile uint32_t hi_su[N];
volatile uint32_t fact10;
volatile uint32_t errors;

static const uint32_t exp_lo[N] = {0x00000023u, 0xFFFFFFE2u, 0x7FFFFFFFu, 0x00000001u, 0xFBFF5385u, 0x00000000u, 0x00000000u, 0x760B3D29u};
static const uint32_t exp_hi_ss[N] = {0x00000000u, 0xFFFFFFFFu, 0x00000000u, 0x00000000u, 0x01B13114u, 0x40000000u, 0x00000000u, 0xFFDA1677u};
static const uint32_t exp_hi_uu[N] = {0x00000000u, 0x00000009u, 0x00000000u, 0xFFFFFFFEu, 0x01B13114u, 0x40000000u, 0x00000000u, 0x00FD5BDEu};
static const uint32_t exp_hi_su[N] = {0x00000000u, 0xFFFFFFFFu, 0x00000000u, 0xFFFFFFFFu, 0x01B13114u, 0xC0000000u, 0x00000000u, 0xFFDA1677u};

int main(void) {
    uint32_t bad = 0;
    for (int i = 0; i < N; i++) {
        uint32_t a = in_a[i], b = in_b[i];
        lo[i] = a * b;
        hi_ss[i] = (uint32_t)(((int64_t)(int32_t)a * (int64_t)(int32_t)b) >> 32);
        hi_uu[i] = (uint32_t)(((uint64_t)a * (uint64_t)b) >> 32);
        hi_su[i] = (uint32_t)(((int64_t)(int32_t)a * (int64_t)(uint64_t)b) >> 32);
        bad += lo[i] != exp_lo[i];
        bad += hi_ss[i] != exp_hi_ss[i];
        bad += hi_uu[i] != exp_hi_uu[i];
        bad += hi_su[i] != exp_hi_su[i];
    }
    uint32_t f = 1;
    for (volatile uint32_t k = 2; k <= 10; k++) f *= k;
    fact10 = f;
    bad += fact10 != 3628800u;
    errors = bad;
    return 0;
}
