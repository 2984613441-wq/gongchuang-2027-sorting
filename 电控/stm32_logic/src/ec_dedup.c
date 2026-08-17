#include "ec_dedup.h"

bool ec_dedup_init(ec_dedup_t *cache, ec_dedup_entry_t *storage,
                   size_t capacity)
{
    size_t index;

    if ((cache == NULL) || (storage == NULL) || (capacity == 0U)) {
        return false;
    }

    cache->entries = storage;
    cache->capacity = capacity;
    cache->used = 0U;
    for (index = 0U; index < capacity; ++index) {
        storage[index].occupied = false;
    }
    return true;
}

ec_dedup_result_t ec_dedup_observe(ec_dedup_t *cache, ec_dedup_key_t key)
{
    size_t index;

    if ((cache == NULL) || (cache->entries == NULL) ||
        (cache->capacity == 0U) || (cache->used > cache->capacity)) {
        return EC_DEDUP_INVALID;
    }

    for (index = 0U; index < cache->capacity; ++index) {
        const ec_dedup_entry_t *entry = &cache->entries[index];

        if (entry->occupied && (entry->key.task_id == key.task_id) &&
            (entry->key.frame_seq == key.frame_seq)) {
            return (entry->key.payload_fingerprint == key.payload_fingerprint)
                       ? EC_DEDUP_DUPLICATE
                       : EC_DEDUP_CONFLICT;
        }
    }

    if (cache->used == cache->capacity) {
        return EC_DEDUP_FULL;
    }

    for (index = 0U; index < cache->capacity; ++index) {
        if (!cache->entries[index].occupied) {
            cache->entries[index].key = key;
            cache->entries[index].occupied = true;
            ++cache->used;
            return EC_DEDUP_NEW;
        }
    }

    return EC_DEDUP_INVALID;
}

void ec_dedup_clear_for_verified_new_round(ec_dedup_t *cache)
{
    size_t index;

    if ((cache == NULL) || (cache->entries == NULL)) {
        return;
    }

    for (index = 0U; index < cache->capacity; ++index) {
        cache->entries[index].occupied = false;
    }
    cache->used = 0U;
}
