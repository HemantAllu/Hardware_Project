/* sub.c : 32-bit SUB on the RV32IM core (subtraction).
 * Includes underflow (0 - 1 = 0xFFFFFFFF = -1) and 0x80000000 - 1.
 *   make sub   (from the project folder or extras/)
 * Inputs are volatile, so the processor really executes the instruction at run time.
 * Every result is compared with the expected value (computed by RISC-V rules);
 * errors = number of wrong results (0 = all correct). */
#include <stdint.h>
#define N 8
volatile uint32_t in_a[N] = {0x00000005u, 0xFFFFFFFDu, 0x7FFFFFFFu, 0xFFFFFFFFu, 0x075BCD15u, 0x80000000u, 0x00000000u, 0xDEADBEEFu};
volatile uint32_t in_b[N] = {0x00000007u, 0x0000000Au, 0x00000001u, 0xFFFFFFFFu, 0x3ADE68B1u, 0x80000000u, 0x12345678u, 0x01234567u};
volatile uint32_t diff[N];
volatile uint32_t neg[N];
volatile uint32_t minus1[N];
volatile uint32_t errors;

static const uint32_t exp_diff[N] = {0xFFFFFFFEu, 0xFFFFFFF3u, 0x7FFFFFFEu, 0x00000000u, 0xCC7D6464u, 0x00000000u, 0xEDCBA988u, 0xDD8A7988u};
static const uint32_t exp_neg[N] = {0xFFFFFFFBu, 0x00000003u, 0x80000001u, 0x00000001u, 0xF8A432EBu, 0x80000000u, 0x00000000u, 0x21524111u};
static const uint32_t exp_minus1[N] = {0x00000004u, 0xFFFFFFFCu, 0x7FFFFFFEu, 0xFFFFFFFEu, 0x075BCD14u, 0x7FFFFFFFu, 0xFFFFFFFFu, 0xDEADBEEEu};

int main(void) {
    uint32_t bad = 0;
    for (int i = 0; i < N; i++) {
        uint32_t a = in_a[i], b = in_b[i];
        diff[i] = a - b;
        neg[i] = 0u - a;
        minus1[i] = a - 1u;
        bad += diff[i] != exp_diff[i];
        bad += neg[i] != exp_neg[i];
        bad += minus1[i] != exp_minus1[i];
    }
    errors = bad;
    return 0;
}
