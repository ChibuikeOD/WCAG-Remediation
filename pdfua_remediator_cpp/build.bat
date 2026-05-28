@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\Common7\Tools\VsDevCmd.bat"
cmake -B build
cmake --build build --config Release
