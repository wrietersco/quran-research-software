"""
Scrape lexicon.quranic-research.net into SQLite.

Requires: selenium, webdriver-manager, Chrome.
"""

from __future__ import annotations

import argparse
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from ..config import get_db_path
from ..db.connection import connect
from ..db.repositories import (
    insert_lexicon_entry,
    replace_entries_for_root,
    upsert_lexicon_root,
    upsert_scraper_state,
)
from ..normalize.arabic import canonical_heading, normalize_arabic


def scrape_to_sqlite(
    *,
    start_url: str,
    db_path=None,
    headless: bool = True,
    skip_existing_roots: bool = True,
) -> None:
    path = db_path or get_db_path()
    conn = connect(path)

    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--lang=ar")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )
    try:
        driver.get(start_url)
        while True:
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article.root"))
                )

                root_word_el = driver.find_element(
                    By.CSS_SELECTOR, "article.root > h2.root .ar"
                )
                root_word = root_word_el.text
                rw_norm = normalize_arabic(root_word)

                existing = conn.execute(
                    "SELECT id FROM lexicon_roots WHERE root_word_normalized = ?",
                    (rw_norm,),
                ).fetchone()

                if existing and skip_existing_roots:
                    next_btn = driver.find_element(By.CLASS_NAME, "next")
                    next_btn.click()
                    time.sleep(0.3)
                    continue

                root_id = upsert_lexicon_root(
                    conn,
                    root_word,
                    rw_norm,
                    source_ref=start_url,
                )
                if existing:
                    replace_entries_for_root(conn, root_id)

                sections = driver.find_elements(By.CSS_SELECTOR, ".entry.main")
                seq = 0
                for section in sections:
                    section.click()
                    visible_child = section.find_elements(By.CSS_SELECTOR, ".visible")
                    if not visible_child:
                        continue
                    main_entry_el = WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "h3.entry"))
                    )
                    main_entry_text = main_entry_el.text
                    entry_definition = section.text.replace(main_entry_text, "").strip()
                    seq += 1
                    heading_norm = canonical_heading(seq, main_entry_text)
                    insert_lexicon_entry(
                        conn,
                        root_id,
                        seq,
                        main_entry_text,
                        heading_norm,
                        entry_definition,
                    )

                conn.commit()
                upsert_scraper_state(conn, rw_norm, driver.current_url)
                conn.commit()
                print(f"Saved root: {root_word} ({seq} entries)")

                next_button = driver.find_element(By.CLASS_NAME, "next")
                next_button.click()
                time.sleep(0.4)

            except Exception as e:
                print(f"Stopped or error: {e}")
                conn.commit()
                break
    finally:
        driver.quit()
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Scrape Quranic Research lexicon into SQLite")
    p.add_argument(
        "--url",
        default="https://lexicon.quranic-research.net/data/01_A/000_A.html",
        help="Starting page URL",
    )
    p.add_argument("--db", type=str, default=None, help="SQLite DB path override")
    p.add_argument("--no-headless", action="store_true", help="Show browser window")
    p.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-import roots already present (replaces entries for that root)",
    )
    args = p.parse_args()
    scrape_to_sqlite(
        start_url=args.url,
        db_path=args.db,
        headless=not args.no_headless,
        skip_existing_roots=not args.no_skip_existing,
    )


if __name__ == "__main__":
    main()
