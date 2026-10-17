/* Fibonacci: iterative table + recursive version (calls, returns, stack). */
volatile int table[20];
volatile int rec15;

static int fib_rec(int n) { return n < 2 ? n : fib_rec(n - 1) + fib_rec(n - 2); }

int main(void) {
    int a = 0, b = 1;
    for (int i = 0; i < 20; i++) { table[i] = a; int t = a + b; a = b; b = t; }
    rec15 = fib_rec(15);
    return 0;
}
