# 알바 사이트 구조 진단 도구 (order 7435652 / WCompany / pid 680774)

고객 PC에서 실행하는 **진단용 exe**. 고객이 자기 PC에서 본인 명의로 비회원 본인인증을 1회 직접 완료하면,
도구가 여우알바/퀸알바의 목록·상세 HTML 구조와 세션 쿠키를 자동 수집해
바탕화면 `진단폴더 이거 보내주세요.zip` 으로 저장한다. 고객이 그 zip을 보내주면 우리가 파서를 완성한다.

> 우리(판매자)가 고객 본인인증을 대신 수행하거나 고객 세션을 우리 인프라에 보관하지 않는다.
> 캡차/본인인증은 고객 PC, 고객 세션에서만 이뤄진다. (Kmong 규정상 우리가 직접 검증 불가)

## 산출물 구조
```
진단폴더 이거 보내주세요/
  _읽어주세요.txt
  foxalba/   cookies.txt cookies.json list_*.html detail_*.html structure_report.txt
  queenalba/ cookies.txt cookies.json list_*.html detail_*.html structure_report.txt
```

## 형태
**tkinter GUI (콘솔 없음)**. 고객은 [시작하기] → 브라우저에서 본인인증 →
[인증 완료 - 다음] 버튼만 누르면 됨. 진행상황은 창 안의 로그에 표시되고
끝나면 결과 폴더가 자동으로 열린다. `DIAG_AUTO=1` 이면 GUI 없이 헤드리스 일괄(검증용).

진단 범위: 목록은 전체 페이지 순회, 상세(하위)는 **사이트당 샘플 기본 80건**
(`DIAG_MAX_DETAIL`, 0=전수). foxalba 등록건이 3천건+ 이라 전수 저장 시 zip 이 수십MB·1시간+ 가 되어
크몽 회신이 어려움 → 진단은 샘플로 구조만 확보(수MB·수분), 전수 추출은 최종 프로그램이 담당.

## 빌드 (Windows exe)
GitHub Actions `windows-latest` + PyInstaller `--onefile --windowed` 로 빌드.
CI에서 (a) 실제 exe 헤드리스 실행→zip 생성 스모크, (b) GUI 창 구성(tkinter 번들) 자기검증
두 단계를 모두 통과해야 릴리스됨. `.github/workflows/build.yml` 참고.
산출물: GitHub Release `latest` 의 exe (한글 asset명이 `default.exe`로 치환됨 → `사이트진단도구.exe`로 리네임).

## 빌드 + 실행검증 완료 (Windows, 2026-06-26)
GitHub Actions `windows-latest` 에서 빌드 후 **같은 러너에서 exe 를 실제 실행**하는 스모크 단계로 검증.
- 산출물: 진짜 Windows `PE32+ console x86-64` exe (~24.7MB)
- 스모크 결과: exe 실행 → Chrome 구동 → foxalba 진입 → 쿠키 2개 저장 →
  목록 자동순회로 고유 상세링크 137개 발견 → 상세/목록 HTML 저장 →
  바탕화면 `진단폴더 이거 보내주세요.zip` 생성까지 전부 성공.
- exe 가 직접 캡처한 스크린샷에 foxalba 비회원 핸드폰인증 게이트 확인.

수정한 실제 버그:
- 영문 Windows(cp1252)에서 한글 print 시 `UnicodeEncodeError` 크래시 → stdout/stderr UTF-8 강제.
- onefile 에 selenium 서브모듈 미번들(`No module named selenium.webdriver.chrome.webdriver`)
  → `--collect-all selenium` + trio 스택.

## 전달
Actions 아티팩트 저장 쿼터가 가득 차서 **GitHub Release** 로 전달:
`gh release download latest` (asset: exe, `windows-runtime-verification.zip`).
GitHub 가 한글 asset 이름을 `default.exe` 로 치환하므로, 고객 전달 시 `사이트진단도구.exe` 로 리네임.
