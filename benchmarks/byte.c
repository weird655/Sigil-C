#include <stdint.h>
#include <stdio.h>

int main(void) {
    volatile uint32_t acc = 0;
    for (uint32_t i = 0; i < 100000000u; i++) {
        ((unsigned char *)&acc)[0] ^= 1;
    }
    printf("%u\n", acc);
    return 0;
}
