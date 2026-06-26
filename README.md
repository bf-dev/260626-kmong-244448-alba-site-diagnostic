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

## 빌드 (Windows exe)
GitHub Actions `windows-latest` + PyInstaller 로 빌드. `.github/workflows/build.yml` 참고.
산출물: `dist/사이트진단도구.exe` (artifact `site-diagnostic-exe`).

## 로컬 검증 완료 (Linux)
- `python3 -m py_compile diagnose.py` OK
- `discover_links()` 라이브 fox 목록에서 상세 idx 126개 추출, top 패턴 `offer_content.asp?idx`
- `save_netscape_cookies()` Netscape 형식 정상
- Selenium 브라우저 경로는 Windows 빌드에서만 실행 검증 가능

## 미해결 (소유자 필요)
- 'windows dev skill' 부재 + 게이트웨이 호스트에 gh/GitHub 인증 없음 -> exe 빌드 불가.
  GitHub repo+token 또는 Windows 러너 또는 해당 skill 위치 중 하나 필요.
