# -*- coding: utf-8 -*-
"""
여우알바 / 퀸알바 사이트 구조 자동 진단 도구 (고객 PC 실행용)
--------------------------------------------------------
실행하시면:
  1) 각 사이트가 브라우저 창으로 열립니다.
  2) 화면 안내대로 '비회원 본인인증'을 1회 직접 완료해 주세요.
     (인증은 고객님 본인 명의로, 고객님 PC에서만 진행됩니다.)
  3) 인증이 끝나면 콘솔 창에서 Enter 를 누르세요.
  4) 도구가 목록의 모든 페이지를 자동으로 넘기며 '모든 하위(상세) 페이지'와
     세션 쿠키를 빠짐없이 저장합니다.
  5) 바탕화면에 "진단폴더 이거 보내주세요.zip" 으로 저장됩니다.
  6) 그 zip 파일 하나만 보내주시면 나머지는 저희가 진행합니다.

환경변수(검증/자동화용, 일반 고객은 신경쓰지 않으셔도 됩니다):
  DIAG_AUTO=1      인증 대기 input() 생략 (헤드리스 자동 실행)
  DIAG_HEADLESS=1  브라우저 창 없이 실행
  DIAG_SITES=foxalba,queenalba   대상 사이트 제한
  DIAG_MAX_DETAIL=0  사이트별 상세 저장 개수 제한(0=무제한, 모든 하위페이지)
  DIAG_MAX_PAGES=300 목록 페이지 자동탐색 상한(안전장치)
"""

import os
import re
import sys
import json
import time
import shutil
import zipfile
import datetime

DESKTOP_FOLDER_NAME = "진단폴더 이거 보내주세요"

# 콘솔 코드페이지가 한글을 못 받는 환경(영문 Windows cp1252 등)에서도
# 한글 출력이 깨지거나 죽지 않도록 표준 출력 인코딩을 UTF-8 로 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def envint(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


AUTO = os.environ.get("DIAG_AUTO") == "1"
HEADLESS = os.environ.get("DIAG_HEADLESS") == "1"
MAX_DETAIL = envint("DIAG_MAX_DETAIL", 0)        # 0 = 무제한 (모든 하위페이지)
MAX_PAGES = envint("DIAG_MAX_PAGES", 300)
ONLY_SITES = [s for s in os.environ.get("DIAG_SITES", "").split(",") if s]

# ---- 사이트 정의 -----------------------------------------------------------
SITES = {
    "foxalba": {
        "label": "여우알바 (foxalba.com)",
        "entry": "https://www.foxalba.com/",
        # {pg} 자리에 페이지 번호. 1페이지부터 새 항목이 없을 때까지 자동 순회.
        "list_tpl": "https://www.foxalba.com/offer/offer_jobpart.asp?page={pg}&orderby01=o_orderday&orderby02=20&orderby03=desc",
        "detail_regex": r"offer_content\.asp\?idx=([0-9]+)",
        "detail_tpl": "https://www.foxalba.com/offer/offer_content.asp?idx={id}",
    },
    "queenalba": {
        "label": "퀸알바 (queenalba.net)",
        "entry": "https://queenalba.net/adult_index.php",
        "list_tpl": "https://queenalba.net/main/list.php?page={pg}",
        # 인증 후에야 상세 링크가 노출되므로 일반 패턴으로 자동 탐색 (href 그대로 사용)
        "detail_regex": r"(?:view|content|read|detail)[a-z_]*\.php\?[^\"'<> ]*?(?:idx|no|num|wr_id|seq|uid|id)=[0-9]+",
        "detail_tpl": None,
    },
}


def log(msg):
    print(msg, flush=True)


def desktop_dir():
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Desktop"),
                 os.path.join(home, "OneDrive", "Desktop"),
                 os.path.join(home, "바탕 화면")):
        if os.path.isdir(cand):
            return cand
    return home


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(options=opts)  # Selenium Manager 가 드라이버 자동 설치


def wait_for_user(label):
    if AUTO:
        log(f">>> [{label}] DIAG_AUTO: 인증 대기 생략")
        return
    input(f"\n>>> [{label}] 인증을 완료하셨으면 Enter 를 눌러주세요... ")


def snap(driver, path):
    """화면 캡처(진단/검증용). 실패해도 무시."""
    try:
        driver.save_screenshot(path)
    except Exception as e:
        log(f"  (스크린샷 실패: {e})")


def save_netscape_cookies(cookies, path):
    lines = ["# Netscape HTTP Cookie File", "# saved by diagnose tool", ""]
    for c in cookies:
        domain = c.get("domain", "")
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path_ = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expiry = int(c.get("expiry", 0)) or 2147483647
        lines.append("\t".join([domain, flag, path_, secure, str(expiry),
                                 c.get("name", ""), c.get("value", "")]))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def discover_links(html):
    hrefs = re.findall(r"href=[\"']([^\"'<> ]+)[\"']", html, re.I)
    id_links = [h for h in hrefs if re.search(r"(idx|no|num|wr_id|seq|uid|id)=[0-9]+", h, re.I)]
    patterns = {}
    for h in id_links:
        base = re.sub(r"=[0-9]+", "=N", h.split("//")[-1].split("?")[0])
        keys = ",".join(sorted(set(re.findall(r"([a-z_]+)=[0-9]+", h, re.I))))
        k = base + "?" + keys
        patterns[k] = patterns.get(k, 0) + 1
    return hrefs, id_links, patterns


def crawl_lists(driver, conf, site_dir, report):
    """1페이지부터 새 상세링크가 안 나올 때까지 자동 순회하며 모든 목록 HTML 저장."""
    all_ids, all_hrefs = [], []
    seen_ids = set()
    empty_streak = 0
    for pg in range(1, MAX_PAGES + 1):
        url = conf["list_tpl"].format(pg=pg)
        try:
            driver.get(url)
            time.sleep(1.2)
            html = driver.page_source
        except Exception as e:
            report.append(f"list page {pg} ERROR {e}")
            break
        with open(os.path.join(site_dir, f"list_{pg:03d}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        hrefs, id_links, patterns = discover_links(html)
        page_ids = re.findall(conf["detail_regex"], html, re.I)
        new = [x for x in page_ids if x not in seen_ids]
        for x in page_ids:
            seen_ids.add(x)
        all_ids += new
        all_hrefs += id_links
        report.append(f"  목록 {pg:03d}: size={len(html)} 상세링크={len(id_links)} 신규={len(new)}")
        if not page_ids and not id_links:
            empty_streak += 1
            if empty_streak >= 2:
                report.append(f"  -> {pg}페이지에서 신규 없음, 목록 순회 종료")
                break
        else:
            empty_streak = 0
        if not new and pg > 1:
            # 새 ID가 더 안 나오면 끝까지 본 것으로 간주(여우알바: 페이지 끝에서 반복)
            report.append(f"  -> {pg}페이지부터 신규 ID 없음, 목록 순회 종료")
            break
    # 패턴 요약(마지막 페이지 기준 + 전체)
    return list(dict.fromkeys(all_ids)), list(dict.fromkeys(all_hrefs))


def crawl_details(driver, conf, site_dir, ids, hrefs, report):
    saved = 0
    limit = MAX_DETAIL if MAX_DETAIL > 0 else 10 ** 9
    if conf.get("detail_tpl"):
        targets = [conf["detail_tpl"].format(id=i) for i in ids]
    else:
        base = conf["entry"].rsplit("/", 1)[0]
        targets = [h if h.startswith("http") else base + "/" + h.lstrip("/") for h in hrefs]
    total = min(len(targets), limit)
    report.append(f"  상세 대상 {len(targets)}개 중 {total}개 저장 예정 (MAX_DETAIL={MAX_DETAIL})")
    for n, url in enumerate(targets):
        if saved >= limit:
            break
        try:
            driver.get(url)
            time.sleep(0.8)
            html = driver.page_source
        except Exception as e:
            report.append(f"  detail {url} ERROR {e}")
            continue
        idm = re.search(r"=([0-9]+)$|=([0-9]+)(?:&|$)", url)
        tag = (idm.group(1) or idm.group(2)) if idm else str(n + 1)
        with open(os.path.join(site_dir, f"detail_{tag}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        saved += 1
        if saved % 25 == 0:
            log(f"    ...상세 {saved}/{total} 저장")
    report.append(f"  상세(하위) 페이지 저장: {saved}개")
    return saved


def process_site(driver, key, conf, out_root):
    site_dir = os.path.join(out_root, key)
    os.makedirs(site_dir, exist_ok=True)
    report = [f"# {conf['label']}", f"entry: {conf['entry']}", ""]

    log("\n" + "=" * 60)
    log(f"[{conf['label']}] 브라우저를 엽니다. 화면에서 비회원 본인인증을 완료해 주세요.")
    log("=" * 60)
    driver.get(conf["entry"])
    time.sleep(1.5)
    snap(driver, os.path.join(site_dir, "_화면_01_진입.png"))
    wait_for_user(conf["label"])
    snap(driver, os.path.join(site_dir, "_화면_02_인증후.png"))

    cookies = driver.get_cookies()
    save_netscape_cookies(cookies, os.path.join(site_dir, "cookies.txt"))
    with open(os.path.join(site_dir, "cookies.json"), "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    report.append(f"cookies: {len(cookies)}개 저장")
    log(f"  - 쿠키 {len(cookies)}개 저장")

    report.append("\n## 목록 자동 순회")
    ids, hrefs = crawl_lists(driver, conf, site_dir, report)
    report.append(f"\n고유 상세 ID(또는 링크): {len(ids) or len(hrefs)}개")
    log(f"  - 목록 순회 완료: 고유 상세 {len(ids) or len(hrefs)}개")

    report.append("\n## 하위(상세) 페이지 저장")
    saved = crawl_details(driver, conf, site_dir, ids, hrefs, report)
    log(f"  - 하위 페이지 {saved}개 저장")

    with open(os.path.join(site_dir, "structure_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    return saved


def main():
    log(__doc__)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    desk = desktop_dir()
    out_root = os.path.join(desk, DESKTOP_FOLDER_NAME)
    if os.path.isdir(out_root):
        shutil.rmtree(out_root, ignore_errors=True)
    os.makedirs(out_root, exist_ok=True)
    with open(os.path.join(out_root, "_읽어주세요.txt"), "w", encoding="utf-8") as f:
        f.write("이 zip 을 그대로 보내주시면 됩니다.\n"
                "각 사이트 폴더: 모든 목록(list_*.html), 모든 하위페이지(detail_*.html),"
                " 구조 리포트(structure_report.txt), 세션 쿠키(cookies.txt/json)\n"
                f"생성: {stamp}\n")

    try:
        driver = make_driver()
    except Exception as e:
        log(f"\n[오류] 크롬을 열 수 없습니다. 크롬 설치를 확인해 주세요.\n상세: {e}")
        if not AUTO:
            input("Enter 로 종료...")
        return 1

    total = 0
    try:
        for key, conf in SITES.items():
            if ONLY_SITES and key not in ONLY_SITES:
                continue
            try:
                total += process_site(driver, key, conf, out_root)
            except Exception as e:
                log(f"[{key}] 처리 오류: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    zip_path = os.path.join(desk, DESKTOP_FOLDER_NAME + ".zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(out_root):
            for fn in files:
                full = os.path.join(root, fn)
                zf.write(full, os.path.relpath(full, os.path.dirname(out_root)))

    log("\n" + "=" * 60)
    log(f"완료. 바탕화면의 다음 파일을 보내주세요:\n  {zip_path}")
    log(f"총 저장 하위페이지: {total}개")
    log("=" * 60)
    if not AUTO:
        input("Enter 로 종료...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
