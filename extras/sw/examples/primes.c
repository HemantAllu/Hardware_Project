/* Count primes below 300 by trial division (REM in the inner loop). */
volatile int count;
volatile int last;

int main(void) {
    int c = 0, l = 0;
    for (int n = 2; n < 300; n++) {
        int prime = 1;
        for (int d = 2; d * d <= n; d++)
            if (n % d == 0) { prime = 0; break; }
        if (prime) { c++; l = n; }
    }
    count = c;      /* 62 */
    last = l;       /* 293 */
    return 0;
}
