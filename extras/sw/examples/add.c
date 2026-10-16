/* add.c : 32-bit ADD and ADDI on the RV32IM core.
 * Includes overflow (0x7FFFFFFF + 1 wraps to 0x80000000) and a sum loop.
 *   make add   (from the project folder or extras/)
 * Inputs are volatile, so the processor really executes the instruction at run time.
 * Every result is compared with the expected value (computed by RISC-V rules);
 * errors = number of wrong results (0 = all correct). */
#include <stdint.h>
#define N 8
volatile uint32_t in_a[N] = {0x00000005u, 0xFFFFFFFDu, 0x7FFFFFFFu, 0xFFFFFFFFu, 0x075BCD15u, 0x80000000u, 0x00000000u, 0xDEADBEEFu};
volatile uint32_t in_b[N] = {0x00000007u, 0x0000000Au, 0x00000001u, 0xFFFFFFFFu, 0x3ADE68B1u, 0x80000000u, 0x12345678u, 0x01234567u};
volatile uint32_t sum[N];
volatile uint32_t plus100[N];
volatile uint32_t total_1_to_100;
volatile uint32_t errors;

static const uint32_t exp_sum[N] = {0x0000000Cu, 0x00000007u, 0x80000000u, 0xFFFFFFFEu, 0x423A35C6u, 0x00000000u, 0x12345678u, 0xDFD10456u};
static const uint32_t exp_plus100[N] = {0x00000069u, 0x00000061u, 0x80000063u, 0x00000063u, 0x075BCD79u, 0x80000064u, 0x00000064u, 0xDEADBF53u};

int main(void) {
    uint32_t bad = 0;
    for (int i = 0; i < N; i++) {
        uint32_t a = in_a[i], b = in_b[i];
        sum[i] = a + b;
        plus100[i] = a + 100u;
        bad += sum[i] != exp_sum[i];
        bad += plus100[i] != exp_plus100[i];
    }
    uint32_t t = 0;
    for (volatile uint32_t k = 1; k <= 100; k++) t += k;
    total_1_to_100 = t;
    bad += total_1_to_100 != 5050u;
    errors = bad;
    return 0;
}
