#include "ec_dedup.h"
#include "test_support.h"

void test_dedup(void)
{
    ec_dedup_entry_t storage[2];
    ec_dedup_t cache;
    const ec_dedup_key_t first = {1U, 10U, 100U};
    const ec_dedup_key_t second = {2U, 20U, 200U};
    const ec_dedup_key_t third = {3U, 30U, 300U};
    const ec_dedup_key_t conflict = {1U, 10U, 101U};

    TEST_CASE_BEGIN("C-DEDUP-005");
    EXPECT_FALSE(ec_dedup_init(NULL, storage, 2U));
    EXPECT_FALSE(ec_dedup_init(&cache, NULL, 2U));
    EXPECT_FALSE(ec_dedup_init(&cache, storage, 0U));

    TEST_CASE_BEGIN("C-DEDUP-001");
    EXPECT_TRUE(ec_dedup_init(&cache, storage, 2U));
    EXPECT_EQ_U32(EC_DEDUP_NEW, ec_dedup_observe(&cache, first));
    EXPECT_EQ_U32(EC_DEDUP_NEW, ec_dedup_observe(&cache, second));
    EXPECT_EQ_U32(2U, cache.used);

    TEST_CASE_BEGIN("C-DEDUP-002");
    EXPECT_EQ_U32(EC_DEDUP_DUPLICATE, ec_dedup_observe(&cache, first));
    EXPECT_EQ_U32(2U, cache.used);

    TEST_CASE_BEGIN("C-DEDUP-003");
    EXPECT_EQ_U32(EC_DEDUP_CONFLICT, ec_dedup_observe(&cache, conflict));
    EXPECT_EQ_U32(2U, cache.used);
    EXPECT_EQ_U32(EC_DEDUP_DUPLICATE, ec_dedup_observe(&cache, first));

    TEST_CASE_BEGIN("C-DEDUP-004");
    EXPECT_EQ_U32(EC_DEDUP_FULL, ec_dedup_observe(&cache, third));
    EXPECT_EQ_U32(2U, cache.used);
    EXPECT_EQ_U32(EC_DEDUP_DUPLICATE, ec_dedup_observe(&cache, first));
    EXPECT_EQ_U32(EC_DEDUP_DUPLICATE, ec_dedup_observe(&cache, second));

    TEST_CASE_BEGIN("C-DEDUP-006");
    ec_dedup_clear_for_verified_new_round(&cache);
    EXPECT_EQ_U32(0U, cache.used);
    EXPECT_EQ_U32(EC_DEDUP_NEW, ec_dedup_observe(&cache, first));

    TEST_CASE_BEGIN("C-DEDUP-007");
    {
        ec_dedup_entry_t single_storage[1];
        ec_dedup_t single_cache;
        EXPECT_TRUE(ec_dedup_init(&single_cache, single_storage, 1U));
        EXPECT_EQ_U32(EC_DEDUP_NEW, ec_dedup_observe(&single_cache, first));
        EXPECT_EQ_U32(1U, single_cache.used);
        EXPECT_EQ_U32(EC_DEDUP_FULL, ec_dedup_observe(&single_cache, third));
        EXPECT_EQ_U32(1U, single_cache.used);
        EXPECT_EQ_U32(EC_DEDUP_DUPLICATE,
                      ec_dedup_observe(&single_cache, first));
        EXPECT_EQ_U32(1U, single_cache.used);
    }

    TEST_CASE_BEGIN("C-DEDUP-008");
    {
        ec_dedup_entry_t large_storage[255];
        ec_dedup_t large_cache;
        size_t index;
        EXPECT_TRUE(ec_dedup_init(&large_cache, large_storage, 255U));
        EXPECT_EQ_U32(EC_DEDUP_NEW, ec_dedup_observe(&large_cache, first));
        for (index = 1U; index < 255U; ++index) {
            const ec_dedup_key_t key = {(uint32_t)(index + 1U), 10U, 100U};
            EXPECT_EQ_U32(EC_DEDUP_NEW, ec_dedup_observe(&large_cache, key));
        }
        EXPECT_EQ_U32(255U, large_cache.used);
        EXPECT_EQ_U32(EC_DEDUP_FULL,
                      ec_dedup_observe(&large_cache, third));
        EXPECT_EQ_U32(EC_DEDUP_DUPLICATE,
                      ec_dedup_observe(&large_cache, first));
        ec_dedup_clear_for_verified_new_round(&large_cache);
        EXPECT_EQ_U32(0U, large_cache.used);
        EXPECT_EQ_U32(EC_DEDUP_NEW, ec_dedup_observe(&large_cache, first));
    }
}
