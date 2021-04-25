cmake_minimum_required(VERSION 3.6)
project(jbig2enc CXX)
set(Version "0.29")

include_directories(${CMAKE_CURRENT_SOURCE_DIR})
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/libjbig)

set(CMAKE_C_FLAGS_DEBUG    "-O2 -Ob0")


########################################
# jbig2enc library
########################################

if (WIN32)
  set(CMAKE_DEBUG_POSTFIX "d")
  set(LIBS ${LIBS} Ws2_32)
  if (MSVC)
    add_definitions(-D_CRT_SECURE_NO_WARNINGS)
	set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -D_CONSOLE -DNDEBUG -D_CONSOLE -D_SCL_SECURE_NO_WARNINGS")
  endif()
else()
  set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -O2 -DNDEBUG")
  set(CMAKE_CXX_FLAGS_DEBUG   "${CMAKE_CXX_FLAGS_DEBUG} -Wall -DDEBUG -pedantic -Og -g -noalign")
endif()

# TODO
# find_package (Leptonica REQUIRED )
include_directories("f:/win64_llvm/include")
link_directories("f:/win64_llvm/lib")
set(LIBS ${LIBS} leptonica-1.81.0)

# AM_CXXFLAGS = -Wall
# AM_LDFLAGS = -Wl,-E
# if ENABLE_RPATH
# AM_LDFLAGS += -Wl,-rpath -Wl,$(libdir)
# endif 
set(libjbig2enc_src
  "${CMAKE_CURRENT_SOURCE_DIR}/src/jbig2enc.cc"
  "${CMAKE_CURRENT_SOURCE_DIR}/src/jbig2arith.cc"
  "${CMAKE_CURRENT_SOURCE_DIR}/src/jbig2sym.cc"
  "${CMAKE_CURRENT_SOURCE_DIR}/src/jbig2comparator.cc"
)
add_definitions(-DVERSION="${Version}")
add_library(libjbig2enc ${libjbig2enc_src})


install(TARGETS libjbig2enc RUNTIME DESTINATION bin LIBRARY DESTINATION lib ARCHIVE DESTINATION lib)
install(FILES
  "${CMAKE_CURRENT_SOURCE_DIR}/src/jbig2enc.h"
  DESTINATION include/)
install(FILES
  "${CMAKE_CURRENT_SOURCE_DIR}/jbig2pdf.py"
  DESTINATION bin/)


########################################
# Programs
########################################

# jbig2_LDFLAGS = -static
add_executable (jbig2 "${CMAKE_CURRENT_SOURCE_DIR}/src/jbig2.cc")
set_target_properties(jbig2 PROPERTIES DEBUG_POSTFIX ${CMAKE_DEBUG_POSTFIX})
target_link_libraries (jbig2 PRIVATE ${LIBS} libjbig2enc$<$<CONFIG:Debug>:d>)
install(TARGETS jbig2 RUNTIME DESTINATION bin LIBRARY DESTINATION lib ARCHIVE DESTINATION lib)