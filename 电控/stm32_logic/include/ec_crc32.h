#ifndef EC_CRC32_H
#define EC_CRC32_H

#include <stddef.h>
#include <stdint.h>

uint32_t ec_crc32_iso_hdlc(const uint8_t *data, size_t length);

#endif
