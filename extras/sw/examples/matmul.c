/* 4x4 integer matrix multiply (MUL-heavy) + trace. */
volatile int A[4][4] = {{1,2,3,4},{5,6,7,8},{9,10,11,12},{13,14,15,16}};
volatile int B[4][4] = {{1,0,2,0},{0,1,0,2},{3,0,1,0},{0,4,0,1}};
volatile int C[4][4];
volatile int trace;

int main(void) {
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) {
            int s = 0;
            for (int k = 0; k < 4; k++) s += A[i][k] * B[k][j];
            C[i][j] = s;
        }
    int t = 0;
    for (int i = 0; i < 4; i++) t += C[i][i];
    trace = t;
    return 0;
}
