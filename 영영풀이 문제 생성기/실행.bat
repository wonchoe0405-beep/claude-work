@echo off
cd /d "%~dp0"
start "" "영영풀이_문제생성기_최종.exe"
if errorlevel 1 (
  echo 프로그램을 실행하지 못했습니다.
  echo 영영풀이_문제생성기_최종.exe 가 이 폴더에 있는지 확인하세요.
  pause
)
