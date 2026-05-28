cmake_minimum_required(VERSION 3.15)
project(pdfua_remediator_cli CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Set QPDF Paths
set(QPDF_DIR "${CMAKE_CURRENT_SOURCE_DIR}/deps/qpdf-12.3.2-msvc64")
include_directories("${QPDF_DIR}/include")
link_directories("${QPDF_DIR}/lib")

add_executable(pdfua-remediator-cli 
    src/main.cpp
    src/content_tagger.cpp
    src/structure_builder.cpp
)

# Link QPDF libraries
target_link_libraries(pdfua-remediator-cli qpdf)

# Copy QPDF dll to output folder for runtime execution
add_custom_command(TARGET pdfua-remediator-cli POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${QPDF_DIR}/bin/qpdf30.dll"
        $<TARGET_FILE_DIR:pdfua-remediator-cli>
)
