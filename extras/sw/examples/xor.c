/* xor.c : XOR / XORI on the RV32IM core.
 * Also swaps two values with three XORs and computes a parity bit.
 *   make xor   (from the project folder or extras/)
 * Inputs are volatile, so the processor really executes the instruction at run time.
 * Every result is compared with the expected value (computed by RISC-V rules);
 * errors = number of wrong results (0 = all correct). */
#include <stdint.h>
#define N 8
volatile uint32_t in_a[N] = {0x00000005u, 0xFFFFFFFDu, 0x7FFFFFFFu, 0xFFFFFFFFu, 0x075BCD15u, 0x80000000u, 0x00000000u, 0xDEADBEEFu};
volatile uint32_t in_b[N] = {0x00000007u, 0x0000000Au, 0x00000001u, 0xFFFFFFFFu, 0x3ADE68B1u, 0x80000000u, 0x12345678u, 0x01234567u};
volatile uint32_t x[N];
volatile uint32_t x_ff[N];
volatile uint32_t not_a[N];
volatile uint32_t swap_a, swap_b, parity;
volatile uint32_t errors;

static const uint32_t exp_x[N] = {0x00000002u, 0xFFFFFFF7u, 0x7FFFFFFEu, 0x00000000u, 0x3D85A5A4u, 0x00000000u, 0x12345678u, 0xDF8EFB88u};
static const uint32_t exp_x_ff[N] = {0x000000FAu, 0xFFFFFF02u, 0x7FFFFF00u, 0xFFFFFF00u, 0x075BCDEAu, 0x800000FFu, 0x000000FFu, 0xDEADBE10u};
static const uint32_t exp_not_a[N] = {0xFFFFFFFAu, 0x00000002u, 0x80000000u, 0x00000000u, 0xF8A432EAu, 0x7FFFFFFFu, 0xFFFFFFFFu, 0x21524110u};

int main(void) {
    uint32_t bad = 0;
    for (int i = 0; i < N; i++) {
        uint32_t a = in_a[i], b = in_b[i];
        x[i] = a ^ b;
        x_ff[i] = a ^ 0xFFu;
        not_a[i] = ~a;
        bad += x[i] != exp_x[i];
        bad += x_ff[i] != exp_x_ff[i];
        bad += not_a[i] != exp_not_a[i];
    }
    uint32_t p = in_a[7], q = in_b[7];        /* swap without a temporary */
    p ^= q; q ^= p; p ^= q;
    swap_a = p; swap_b = q;
    uint32_t v = in_a[7], par = 0;            /* parity of 0xDEADBEEF (24 ones -> 0) */
    while (v) { par ^= v & 1u; v >>= 1; }
    parity = par;
    bad += swap_a != in_b[7]; bad += swap_b != in_a[7]; bad += parity != 0u;
    errors = bad;
    return 0;
}
