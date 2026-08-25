cmake_minimum_required(VERSION 3.20)
project(ec_stm32_logic LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

if(MSVC)
  add_compile_options(/W4 /WX)
else()
  add_compile_options(-Wall -Wextra -Wpedantic -Werror)
endif()

enable_testing()

add_library(ec_stm32_logic STATIC
    src/ec_crc32.c
    src/ec_dedup.c
    src/ec_state_machine.c
    src/ec_protocol.c
    src/ec_protocol_gateway.c
)
target_include_directories(ec_stm32_logic PUBLIC include)

add_executable(ec_logic_tests
    tests/test_main.c
    tests/test_crc32.c
    tests/test_dedup.c
    tests/test_state_machine.c
    tests/test_protocol.c
    tests/test_protocol_gateway.c
)
target_include_directories(ec_logic_tests PRIVATE tests)
target_link_libraries(ec_logic_tests PRIVATE ec_stm32_logic)

add_test(NAME ec_logic_tests COMMAND ec_logic_tests)

add_executable(crc32_vector_cli
    tests/crc32_vector_cli.c
)
target_link_libraries(crc32_vector_cli PRIVATE ec_stm32_logic)
