@echo off
rem 개발 폴더의 소스로 exe를 다시 만든다. Python과 PyInstaller, PyMuPDF가 설치된 PC에서 실행한다.
cd /d "%~dp0개발"
python 영영풀이_문제생성기.py --self-test
if errorlevel 1 (
  echo 자체 테스트가 실패해 빌드를 멈췄습니다.
  pause
  exit /b 1
)
python -m PyInstaller --noconfirm 영영풀이_문제생성기.spec
if errorlevel 1 (
  echo 빌드에 실패했습니다. pip install pyinstaller pymupdf 로 설치했는지 확인하세요.
  pause
  exit /b 1
)
copy /y "dist\영영풀이_문제생성기_최종.exe" "..\영영풀이_문제생성기_최종.exe"
echo 완료: 새 영영풀이_문제생성기_최종.exe 가 만들어졌습니다.
pause
