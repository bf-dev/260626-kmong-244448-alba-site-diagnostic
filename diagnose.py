# -*- coding: utf-8 -*-
"""
여우알바 / 퀸알바 사이트 구조 진단 도구 (고객 PC 실행용)
--------------------------------------------------------
실행하시면:
  1) 각 사이트가 브라우저 창으로 열립니다.
  2) 화면 안내대로 '비회원 본인인증'을 1회 직접 완료해 주세요.
     (인증은 고객님 본인 명의로, 고객님 PC에서만 진행됩니다.)
  3) 인증이 끝나면 콘솔 창에서 Enter 를 누르세요.
  4) 도구가 자동으로 사이트 구조(목록/상세 페이지)와 쿠키를 수집해
     바탕화면에 "진단폴더 이거 보내주세요.zip" 으로 저장합니다.
  5) 그 zip 파일 하나만 보내주시면, 나머지는 저희가 진행합니다.

저장 항목: 목록/상세 HTML, 발견된 링크 구조 리포트, 세션 쿠키(cookies.txt / cookies.json)
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

# ---- 사이트 정의 (목록 -> 상세 패턴) -------------------------------------
SITES = {
    "foxalba": {
        "label": "여우알바 (foxalba.com)",
        "encoding": "euc-kr",
        "entry": "https://www.foxalba.com/",
        "lists": [
            "https://www.foxalba.com/offer/offer_jobpart.asp?page=1&orderby01=o_orderday&orderby02=20&orderby03=desc",
            "https://www.foxalba.com/offer/offer_jobpart.asp?page=2&orderby01=o_orderday&orderby02=20&orderby03=desc",
        ],
        # 목록 HTML 에서 상세 링크(idx) 자동 추출
        "detail_regex": r"offer_content\.asp\?idx=([0-9]+)",
        "detail_url": "https://www.foxalba.com/offer/offer_content.asp?idx={id}",
    },
    "queenalba": {
        "label": "퀸알바 (queenalba.net)",
        "encoding": "utf-8",
        "entry": "https://queenalba.net/adult_index.php",
        "lists": [
            "https://queenalba.net/main/list.php",
            "https://queenalba.net/main/list.php?page=2",
        ],
        # 상세 링크 패턴은 인증 후에야 노출되므로 일반 패턴으로 자동 탐색
        "detail_regex": r"(?:view|content|read|detail)[a-z_]*\.php\?[^\"'<> ]*?(?:idx|no|num|wr_id|seq|uid)=([0-9]+)",
        "detail_url": None,  # 목록에서 추출한 href 를 그대로 사용
    },
}

MAX_DETAIL_SAMPLES = 5  # 사이트별 상세 페이지 저장 개수 (구조 파악용 샘플)


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
    """가능하면 Selenium(Chrome), 없으면 안내."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    # Selenium Manager 가 드라이버 자동 설치
    return webdriver.Chrome(options=opts)


def save_netscape_cookies(cookies, path):
    """Selenium 쿠키 -> Netscape cookies.txt (서버 재현용)."""
    lines = ["# Netscape HTTP Cookie File", "# saved by diagnose tool", ""]
    for c in cookies:
        domain = c.get("domain", "")
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path_ = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expiry = int(c.get("expiry", 0)) or 2147483647
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append("\t".join([domain, flag, path_, secure, str(expiry), name, value]))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def discover_links(html):
    """목록 HTML 에서 모든 href 와 숫자 ID 링크 패턴을 자동 추출."""
    hrefs = re.findall(r"href=[\"']([^\"'<> ]+)[\"']", html, re.I)
    id_links = [h for h in hrefs if re.search(r"(idx|no|num|wr_id|seq|uid|id)=[0-9]+", h, re.I)]
    # 패턴별 카운트 (경로?파라미터키 기준)
    patterns = {}
    for h in id_links:
        key = re.sub(r"=[0-9]+", "=N", h.split("//")[-1].split("?")[0]) + "?" + \
              ",".join(sorted(set(re.findall(r"([a-z_]+)=[0-9]+", h, re.I))))
        patterns[key] = patterns.get(key, 0) + 1
    return hrefs, id_links, patterns


def process_site(driver, key, conf, out_root):
    site_dir = os.path.join(out_root, key)
    os.makedirs(site_dir, exist_ok=True)
    report = [f"# {conf['label']}", f"entry: {conf['entry']}", ""]

    log("")
    log("=" * 60)
    log(f"[{conf['label']}] 브라우저를 엽니다.")
    log("화면에서 '비회원 본인인증'을 직접 완료해 주세요.")
    log("=" * 60)
    driver.get(conf["entry"])
    input(f"\n>>> [{conf['label']}] 인증을 완료하셨으면 Enter 를 눌러주세요... ")

    # 1) 쿠키 저장
    cookies = driver.get_cookies()
    save_netscape_cookies(cookies, os.path.join(site_dir, "cookies.txt"))
    with open(os.path.join(site_dir, "cookies.json"), "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    report.append(f"cookies: {len(cookies)} 개 저장")
    log(f"  - 쿠키 {len(cookies)}개 저장 완료")

    # 2) 목록 페이지 저장 + 링크 구조 자동 탐색
    detail_ids, detail_hrefs = [], []
    for i, lurl in enumerate(conf["lists"], 1):
        try:
            driver.get(lurl)
            time.sleep(2)
            html = driver.page_source
        except Exception as e:
            report.append(f"list {lurl} ERROR {e}")
            continue
        fn = os.path.join(site_dir, f"list_{i}.html")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(html)
        hrefs, id_links, patterns = discover_links(html)
        report.append("")
        report.append(f"## 목록 {i}: {lurl}")
        report.append(f"   size={len(html)}  href={len(hrefs)}  id_links={len(id_links)}")
        report.append("   발견된 상세 링크 패턴:")
        for p, n in sorted(patterns.items(), key=lambda x: -x[1]):
            report.append(f"     - {p}  (x{n})")
        # 사이트 지정 정규식으로 상세 ID 추출
        ids = re.findall(conf["detail_regex"], html, re.I)
        detail_ids += ids
        detail_hrefs += id_links
        log(f"  - 목록{i} 저장 (상세링크 {len(id_links)}개)")

    # 3) 상세 페이지 샘플 저장
    seen = set()
    saved = 0
    if conf.get("detail_url"):
        for did in detail_ids:
            if did in seen:
                continue
            seen.add(did)
            try:
                driver.get(conf["detail_url"].format(id=did))
                time.sleep(1.5)
                html = driver.page_source
            except Exception as e:
                report.append(f"detail {did} ERROR {e}")
                continue
            with open(os.path.join(site_dir, f"detail_{did}.html"), "w", encoding="utf-8") as f:
                f.write(html)
            saved += 1
            if saved >= MAX_DETAIL_SAMPLES:
                break
    else:
        for href in detail_hrefs:
            if href in seen:
                continue
            seen.add(href)
            url = href if href.startswith("http") else conf["entry"].rsplit("/", 1)[0] + "/" + href.lstrip("/")
            try:
                driver.get(url)
                time.sleep(1.5)
                html = driver.page_source
            except Exception as e:
                report.append(f"detail {url} ERROR {e}")
                continue
            with open(os.path.join(site_dir, f"detail_{saved+1}.html"), "w", encoding="utf-8") as f:
                f.write(html)
            saved += 1
            if saved >= MAX_DETAIL_SAMPLES:
                break

    report.append("")
    report.append(f"상세 샘플 저장: {saved} 개")
    log(f"  - 상세 샘플 {saved}개 저장 완료")

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
        f.write("이 폴더(zip)를 그대로 보내주시면 됩니다.\n"
                "각 사이트 폴더 안에 목록/상세 HTML, 구조 리포트, 세션 쿠키가 들어 있습니다.\n"
                f"생성 시각: {stamp}\n")

    try:
        driver = make_driver()
    except Exception as e:
        log("\n[오류] 크롬 브라우저를 열 수 없습니다. 크롬이 설치되어 있는지 확인해 주세요.")
        log(f"상세: {e}")
        input("Enter 를 눌러 종료합니다...")
        return

    try:
        total = 0
        for key, conf in SITES.items():
            try:
                total += process_site(driver, key, conf, out_root)
            except Exception as e:
                log(f"[{key}] 처리 중 오류: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # zip 압축
    zip_path = os.path.join(desk, DESKTOP_FOLDER_NAME + ".zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(out_root):
            for fn in files:
                full = os.path.join(root, fn)
                zf.write(full, os.path.relpath(full, os.path.dirname(out_root)))

    log("")
    log("=" * 60)
    log(f"완료되었습니다. 바탕화면의 다음 파일을 보내주세요:")
    log(f"  {zip_path}")
    log("=" * 60)
    input("Enter 를 눌러 종료합니다...")


if __name__ == "__main__":
    main()
