#ifndef EC_DEDUP_H
#define EC_DEDUP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t task_id;
    uint32_t frame_seq;
    uint32_t payload_fingerprint;
} ec_dedup_key_t;

typedef enum {
    EC_DEDUP_NEW = 0,
    EC_DEDUP_DUPLICATE,
    EC_DEDUP_CONFLICT,
    EC_DEDUP_FULL,
    EC_DEDUP_INVALID
} ec_dedup_result_t;

typedef struct ec_dedup_entry {
    ec_dedup_key_t key;
    bool occupied;
} ec_dedup_entry_t;

typedef struct {
    ec_dedup_entry_t *entries;
    size_t capacity;
    size_t used;
} ec_dedup_t;

bool ec_dedup_init(ec_dedup_t *cache, ec_dedup_entry_t *storage,
                   size_t capacity);
ec_dedup_result_t ec_dedup_observe(ec_dedup_t *cache, ec_dedup_key_t key);
void ec_dedup_clear_for_verified_new_round(ec_dedup_t *cache);

#endif
