/* GCD / LCM / modular arithmetic with signed and unsigned DIV and REM. */
volatile int res[12];

static int gcd(int a, int b) { while (b) { int t = a % b; a = b; b = t; } return a; }

int main(void) {
    res[0] = gcd(1071, 462);                 /* 21 */
    res[1] = gcd(270, 192);                  /* 6  */
    res[2] = 1071 / gcd(1071, 462) * 462;    /* lcm = 23562 */
    res[3] = -100 / 7;                       /* -14 : rounds toward zero */
    res[4] = -100 % 7;                       /* -2  : sign of dividend   */
    res[5] = (int)(4000000000u / 7u);        /* unsigned divide */
    res[6] = (int)(4000000000u % 7u);
    volatile int zero = 0;
    res[7] = 5 / zero;                       /* -1 : divide by zero */
    res[8] = 5 % zero;                       /* 5  */
    int s = 0;
    for (int i = 1; i <= 50; i++) s += (i * i) % 17;
    res[9] = s;
    return 0;
}
