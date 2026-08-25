cmake_minimum_required(VERSION 3.16)
project(ec_firmware_host_tests C)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
add_executable(ec_firmware_host_tests
    test_main.c test_inputs.c test_step_test.c test_servo_test.c test_group_test.c test_barrier_test.c test_diag.c test_safety_adapter.c test_app.c test_protocol.c
    ../App/Src/ec_inputs.c ../App/Src/ec_step_test.c ../App/Src/ec_servo_test.c ../App/Src/ec_group_test.c ../App/Src/ec_barrier_test.c ../App/Src/ec_diag.c
    ../App/Src/ec_safety_adapter.c ../App/Src/ec_app.c
    ../../../stm32_logic/src/ec_state_machine.c ../../../stm32_logic/src/ec_dedup.c ../../../stm32_logic/src/ec_crc32.c ../../../stm32_logic/src/ec_protocol.c)
target_include_directories(ec_firmware_host_tests PRIVATE ../App/Inc ../../../stm32_logic/include)
target_compile_definitions(ec_firmware_host_tests PRIVATE
    EC_DIAGNOSTIC_BUILD=1 EC_MOTION_TEST_BUILD=1 EC_SERVO_TEST_BUILD=1 EC_GROUP_TEST_BUILD=1 EC_BARRIER_TEST_BUILD=1)
if(MSVC)
  target_compile_options(ec_firmware_host_tests PRIVATE /W4 /WX /utf-8)
else()
  target_compile_options(ec_firmware_host_tests PRIVATE -Wall -Wextra -Werror -pedantic)
endif()
enable_testing()
add_test(NAME ec_firmware_host_tests COMMAND ec_firmware_host_tests)

add_executable(ec_diag_disabled_tests
    test_diag_disabled.c ../App/Src/ec_diag.c)
target_include_directories(ec_diag_disabled_tests PRIVATE
    ../App/Inc ../../../stm32_logic/include)
target_compile_definitions(ec_diag_disabled_tests PRIVATE
    EC_DIAGNOSTIC_BUILD=1 EC_MOTION_TEST_BUILD=1 EC_SERVO_TEST_BUILD=1
    EC_GROUP_TEST_BUILD=0)
if(MSVC)
  target_compile_options(ec_diag_disabled_tests PRIVATE /W4 /WX /utf-8)
else()
  target_compile_options(ec_diag_disabled_tests PRIVATE
      -Wall -Wextra -Werror -pedantic)
endif()
add_test(NAME ec_diag_disabled_tests COMMAND ec_diag_disabled_tests)

add_executable(ec_axis_driver_tests
    test_axis_driver.c
    ../App/Src/ec_axis_driver.c)
target_include_directories(ec_axis_driver_tests PRIVATE
    ../App/Inc ../../../stm32_logic/include)
if(MSVC)
  target_compile_options(ec_axis_driver_tests PRIVATE /W4 /WX /utf-8)
else()
  target_compile_options(ec_axis_driver_tests PRIVATE
      -Wall -Wextra -Werror -pedantic)
endif()
add_test(NAME ec_axis_driver_tests COMMAND ec_axis_driver_tests)
