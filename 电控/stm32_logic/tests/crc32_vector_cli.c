#include "ec_crc32.h"

#include <inttypes.h>
#include <stdio.h>

int main(void)
{
    static const uint8_t vector[] = {0x01U, 0x02U, 0x03U, 0x04U, 0x05U};
    const uint32_t crc = ec_crc32_iso_hdlc(vector, sizeof(vector));

    (void)printf("%08" PRIX32 "\n", crc);
    return 0;
}
