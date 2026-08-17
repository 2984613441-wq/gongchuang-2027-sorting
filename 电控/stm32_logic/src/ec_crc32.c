#include "ec_crc32.h"

uint32_t ec_crc32_iso_hdlc(const uint8_t *data, size_t length)
{
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    size_t index;

    for (index = 0U; index < length; ++index) {
        unsigned int bit;

        crc ^= data[index];
        for (bit = 0U; bit < 8U; ++bit) {
            const uint32_t mask = UINT32_C(0) - (crc & UINT32_C(1));
            crc = (crc >> 1U) ^ (UINT32_C(0xEDB88320) & mask);
        }
    }

    return crc ^ UINT32_C(0xFFFFFFFF);
}
