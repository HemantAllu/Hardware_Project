/* Bubble sort of 16 integers (ADD/SUB/compare/load/store, data hazards). */
volatile int data[16] = {42, -7, 19, 0, 88, 3, -100, 55, 12, 12, 7, 1000, -1, 64, 5, 23};
volatile int checksum;

int main(void) {
    for (int i = 0; i < 15; i++)
        for (int j = 0; j < 15 - i; j++)
            if (data[j] > data[j + 1]) {
                int t = data[j];
                data[j] = data[j + 1];
                data[j + 1] = t;
            }
    int s = 0;
    for (int i = 0; i < 16; i++) s += data[i] * (i + 1);   /* position-weighted sum (MUL) */
    checksum = s;
    return 0;
}
