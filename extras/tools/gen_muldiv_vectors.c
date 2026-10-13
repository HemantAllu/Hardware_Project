// gen_muldiv_vectors.c : independent RV32M reference (host C, 128-bit arithmetic) for tb_muldiv_vec.v
//   gcc -O2 -o gen_muldiv_vectors gen_muldiv_vectors.c && ./gen_muldiv_vectors vectors.txt [seed] [n_random]
// Line: "<funct3> <a hex> <b hex> <expected hex>".  RISC-V corner cases from the unprivileged spec, ch. 'M':
//   x/0 = -1 (DIV/DIVU), x%0 = x (REM/REMU), INT_MIN/-1 = INT_MIN, INT_MIN%-1 = 0.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
static uint32_t ref(int f3, uint32_t a, uint32_t b) {
    int32_t sa = (int32_t)a, sb = (int32_t)b;
    switch (f3) {
    case 0: return (uint32_t)((__int128)sa * sb);
    case 1: return (uint32_t)(((__int128)sa * sb) >> 32);
    case 2: return (uint32_t)(((__int128)sa * (__int128)(uint64_t)b) >> 32);
    case 3: return (uint32_t)(((unsigned __int128)a * b) >> 32);
    case 4: if (b == 0) return 0xFFFFFFFFu; if (sa == INT32_MIN && sb == -1) return (uint32_t)INT32_MIN; return (uint32_t)(sa / sb);
    case 5: if (b == 0) return 0xFFFFFFFFu; return a / b;
    case 6: if (b == 0) return a; if (sa == INT32_MIN && sb == -1) return 0; return (uint32_t)(sa % sb);
    default: if (b == 0) return a; return a % b;
    }
}
int main(int argc, char **argv) {
    FILE *f = fopen(argc > 1 ? argv[1] : "vectors.txt", "w");
    uint64_t s = argc > 2 ? strtoull(argv[2], 0, 10) : 1;
    int nr = argc > 3 ? atoi(argv[3]) : 20000;
    static const uint32_t E[] = {0, 1, 2, 3, 0xFFFFFFFFu, 0xFFFFFFFEu, 0x7FFFFFFFu, 0x80000000u, 0x80000001u, 0x0000FFFFu,
                                 0xFFFF0000u, 0x00010000u, 0x55555555u, 0xAAAAAAAAu, 0x7FFFFFFEu, 0x40000000u, 0xC0000000u,
                                 10, 0xFFFFFFF6u, 1000000007u, 0x12345678u, 0xDEADBEEFu};
    int ne = sizeof E / sizeof E[0], n = 0;
    for (int f3 = 0; f3 < 8; f3++)
        for (int i = 0; i < ne; i++)
            for (int j = 0; j < ne; j++) { fprintf(f, "%d %08x %08x %08x\n", f3, E[i], E[j], ref(f3, E[i], E[j])); n++; }
    for (int k = 0; k < nr; k++) {
        s = s * 6364136223846793005ULL + 1442695040888963407ULL;
        uint32_t a = (uint32_t)(s >> 32);
        s = s * 6364136223846793005ULL + 1442695040888963407ULL;
        uint32_t b = (uint32_t)(s >> 32);
        int sh = (int)((s >> 8) & 31);                       // vary operand magnitude
        if (k & 1) b >>= sh;
        if (k & 2) a >>= (int)((s >> 16) & 31);
        for (int f3 = 0; f3 < 8; f3++) { fprintf(f, "%d %08x %08x %08x\n", f3, a, b, ref(f3, a, b)); n++; }
    }
    fclose(f);
    printf("wrote %d vectors\n", n);
    return 0;
}
