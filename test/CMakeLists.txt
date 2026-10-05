# Lipi host tests: the engine, every provider's shaper tests and the
# descriptor consistency checks. Standalone:
#   cmake -S test -B build && cmake --build build -j && ctest --test-dir build
# A host that already has GoogleTest can add_subdirectory() this file.
cmake_minimum_required(VERSION 3.16)
project(lipi_tests CXX)

if(NOT DEFINED CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 20)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)
  set(CMAKE_CXX_EXTENSIONS OFF)
endif()
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

if(NOT TARGET gtest)
  include(FetchContent)
  FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.17.0
  )
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)
endif()

set(LIPI_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/..")

add_executable(LipiTest
  ScriptTablesTest.cpp
  ${LIPI_ROOT}/providers/bengali/test/BengaliShaperTest.cpp
  ${LIPI_ROOT}/providers/devanagari/test/DevanagariShaperTest.cpp
  ${LIPI_ROOT}/engine/Lipi.cpp
)
target_include_directories(LipiTest PRIVATE ${LIPI_ROOT}/engine ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_options(LipiTest PRIVATE -Wall -Wextra)
target_link_libraries(LipiTest PRIVATE GTest::gtest_main)
# A host may compile the engine with the sanitizers on (CrossInk's scalable-font
# test target does); the engine must build and pass under them too:
#   cmake -S test -B build-asan -DLIPI_SANITIZE=ON
option(LIPI_SANITIZE "Build the tests with -fsanitize=address,undefined" OFF)
if(LIPI_SANITIZE)
  target_compile_options(LipiTest PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(LipiTest PRIVATE -fsanitize=address,undefined)
endif()

enable_testing()
include(GoogleTest)
gtest_discover_tests(LipiTest)
