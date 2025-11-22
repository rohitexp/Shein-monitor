import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Browser, Page

from notify import send_telegram_message

load_dotenv()

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"


@dataclass
class SizeInfo:
    label: str
    in_stock: Optional[bool]  # None if unknown
    qty: Optional[int]        # None if unknown


@dataclass
class ProductInfo:
    id: str
    url: str
    title: str
    price: Optional[str]
    sizes: List[SizeInfo]

    def key(self) -> str:
        return self.id or self.url


def read_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def read_state() -> Dict[str, dict]:
    if not STATE_PATH.exists():
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(state: Dict[str, dict]) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(STATE_PATH)


async def ensure_scroll(page: Page, steps: int, pause_ms: int):
    for _ in range(max(1, steps)):
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(max(200, pause_ms))


async def extract_listing_products(page: Page, max_products: int) -> List[Tuple[str, str]]:
    # Return list of (url, title)
    items: List[Tuple[str, str]] = []

    # Try common Shein product card anchors
    # Strategy: querySelectorAll for links that look like product links
    anchors = await page.query_selector_all("a[href*='/p/'], a[href*='/product/'], a[href*='/detail/']")
    seen = set()
    for a in anchors:
        href = await a.get_attribute("href")
        if not href:
            continue
        # Normalize absolute URL
        if href.startswith("/"):
            href = f"https://www.sheinindia.in{href}"
        title = (await a.get_attribute("title")) or (await a.inner_text() or "").strip()
        # Filter obvious non-product links
        if not re.search(r"/(p|product|detail)/", href):
            continue
        # Avoid dupes
        key = href.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        items.append((href, title))
        if len(items) >= max_products:
            break

    return items


async def parse_product_id_from_url(url: str) -> str:
    # Try to extract numeric ID like .../p/1234567.html or /product-name-p-1234567.html
    m = re.search(r"/(?:p|product|detail)/([\w-]*?(\d+))", url)
    if m:
        # Use numeric if exists
        num = m.group(2)
        if num:
            return num
        return m.group(1)
    # Fallback: last path segment
    try:
        return url.rstrip("/").rsplit("/", 1)[-1]
    except Exception:
        return url


async def extract_sizes_from_json(text: str) -> List[SizeInfo]:
    sizes: List[SizeInfo] = []
    # Look for JSON blobs that contain size/sku information.
    # Heuristics for fields: "sku", "size", "inStock", "stock", "inventory"
    candidates = re.findall(r"\{[^\n]*?(?:sku|size|inStock|stock|inventory)[^\n]*?\}", text, flags=re.IGNORECASE)
    for c in candidates:
        # Try to extract size label and stock/inStock
        label_m = re.search(r"\"(?:size|sizeName|size_label|sizeDesc)\"\s*:\s*\"([^\"]+)\"", c, flags=re.IGNORECASE)
        stock_m = re.search(r"\"(?:stock|inventory|qty)\"\s*:\s*(\d+)", c, flags=re.IGNORECASE)
        instock_m = re.search(r"\"(?:inStock|available)\"\s*:\s*(true|false)", c, flags=re.IGNORECASE)
        if label_m:
            label = label_m.group(1).strip()
            qty = int(stock_m.group(1)) if stock_m else None
            in_stock = None
            if instock_m:
                in_stock = True if instock_m.group(1).lower() == "true" else False
            elif qty is not None:
                in_stock = qty > 0
            sizes.append(SizeInfo(label=label, in_stock=in_stock, qty=qty))
    # Deduplicate by label
    dedup: Dict[str, SizeInfo] = {}
    for s in sizes:
        if s.label not in dedup:
            dedup[s.label] = s
    return list(dedup.values())


async def extract_product_detail(page: Page, url: str) -> ProductInfo:
    await page.goto(url, wait_until="load")
    await page.wait_for_load_state("networkidle")

    # Title
    title = ""
    title_el = await page.query_selector("h1, h1[itemprop='name'], [data-testid='product-title']")
    if title_el:
        try:
            title = (await title_el.inner_text()).strip()
        except Exception:
            pass
    if not title:
        title = (await page.title()) or ""

    # Price
    price = None
    price_el = await page.query_selector("[data-testid='price'], .original, .sale, [itemprop='price'], .product-intro__price")
    if price_el:
        try:
            price = (await price_el.inner_text()).strip()
        except Exception:
            pass

    # Sizes via DOM buttons
    sizes: List[SizeInfo] = []
    size_btns = await page.query_selector_all("[data-testid*='size'], .product-intro__size .item, button[aria-label*='Size'], .product-intro__size .size")
    for b in size_btns:
        label = (await b.inner_text() or "").strip()
        if not label:
            continue
        disabled_attr = await b.get_attribute("disabled")
        aria_disabled = await b.get_attribute("aria-disabled")
        classes = (await b.get_attribute("class") or "").lower()
        is_disabled = bool(disabled_attr) or (aria_disabled == "true") or ("disabled" in classes)
        sizes.append(SizeInfo(label=label, in_stock=(not is_disabled), qty=None))

    # If sizes still empty, try to parse JSON scripts
    if not sizes:
        scripts = await page.query_selector_all("script")
        for s in scripts:
            try:
                txt = await s.inner_text()
            except Exception:
                continue
            if any(k in txt for k in ["sku", "inStock", "inventory", "stock", "size"]):
                parsed = await extract_sizes_from_json(txt)
                if parsed:
                    sizes = parsed
                    break

    # Get product id
    pid = await parse_product_id_from_url(url)

    return ProductInfo(id=pid, url=url, title=title, price=price, sizes=sizes)


def diff_products(old: Dict[str, dict], new: ProductInfo, notify_on: dict) -> Optional[str]:
    key = new.id or new.url
    prev = old.get(key)

    def sizes_to_map(sizes: List[SizeInfo]) -> Dict[str, Dict[str, Optional[int]]]:
        return {s.label: {"in_stock": s.in_stock, "qty": s.qty} for s in sizes}

    if not prev:
        if notify_on.get("new_product", True):
            sizes_str = ", ".join([f"{s.label}:{'✅' if (s.in_stock or s.qty and s.qty>0) else '❌'}" for s in new.sizes]) or "N/A"
            return (
                f"🆕 नया प्रोडक्ट आया\n"
                f"शीर्षक: {new.title}\n"
                f"कीमत: {new.price or 'N/A'}\n"
                f"साइज: {sizes_str}\n"
                f"लिंक: {new.url}"
            )
        return None

    # Compare sizes
    old_sizes = prev.get("sizes", {})
    new_sizes = sizes_to_map(new.sizes)

    changes = []
    # New sizes
    for label in new_sizes:
        if label not in old_sizes:
            if notify_on.get("size_change", True):
                changes.append(f"नया साइज: {label}")
    # Restock / out of stock changes
    for label, meta in new_sizes.items():
        if label in old_sizes:
            old_meta = old_sizes[label]
            old_in = old_meta.get("in_stock")
            new_in = meta.get("in_stock")
            old_qty = old_meta.get("qty")
            new_qty = meta.get("qty")

            # Restock
            if notify_on.get("restock", True):
                became_in = (old_in is False and new_in is True) or (old_qty and old_qty == 0 and (new_qty or 0) > 0)
                if became_in:
                    changes.append(f"री-स्टॉक: {label}")
            # Out of stock
            went_out = (old_in is True and new_in is False) or ((old_qty or 0) > 0 and (new_qty or 0) == 0)
            if went_out and notify_on.get("size_change", True):
                changes.append(f"आउट ऑफ स्टॉक: {label}")

    if changes:
        return (
            f"🔔 स्टॉक अपडेट\n"
            f"प्रोडक्ट: {new.title}\n"
            f"परिवर्तन: {', '.join(changes)}\n"
            f"कीमत: {new.price or 'N/A'}\n"
            f"लिंक: {new.url}"
        )

    return None


async def monitor_once(browser: Browser, config: dict, state: Dict[str, dict]) -> Dict[str, dict]:
    context = await browser.new_context()
    page = await context.new_page()

    notify_on = config.get("notify_on", {})
    scroll_steps = int(config.get("scroll_steps", 5))
    scroll_pause_ms = int(config.get("scroll_pause_ms", 800))
    max_products = int(config.get("max_products", 50))

    for url in config.get("urls", []):
        try:
            print(f"[monitor] Visiting listing: {url}")
            await page.goto(url, wait_until="load")
            await page.wait_for_load_state("networkidle")
            await ensure_scroll(page, scroll_steps, scroll_pause_ms)

            list_items = await extract_listing_products(page, max_products)
            print(f"[monitor] Found {len(list_items)} items on listing")

            # Listing count transition alert (0 -> >= threshold)
            if config.get("notify_on", {}).get("listing_from_zero", False):
                listing_key = "_listing"
                prev_listing = state.get(listing_key, {})
                try:
                    prev_count = int(prev_listing.get(url, 0))
                except Exception:
                    prev_count = 0
                try:
                    threshold = int(config.get("listing_threshold_min", 1))
                except Exception:
                    threshold = 1
                new_count = len(list_items)
                if prev_count == 0 and new_count >= threshold:
                    send_telegram_message(
                        f"🛒 श्रेणी अपडेट\n"
                        f"URL: {url}\n"
                        f"उत्पाद मिले: {new_count} (पहले 0)\n"
                        f"अब प्रोडक्ट उपलब्ध हैं."
                    )
                # Always update stored count
                prev_listing[url] = new_count
                state[listing_key] = prev_listing

            # Open a new page for product details to avoid losing listing scroll
            detail_page = await context.new_page()

            for purl, ptitle in list_items:
                try:
                    info = await extract_product_detail(detail_page, purl)
                    # If title missing, fall back to listing
                    if not info.title:
                        info.title = ptitle

                    # Prepare diff
                    message = diff_products(state, info, notify_on)
                    if message:
                        print(f"[notify] {info.id}: change detected -> sending Telegram")
                        send_telegram_message(message)

                    # Update state
                    state[info.key()] = {
                        "url": info.url,
                        "title": info.title,
                        "price": info.price,
                        "sizes": {s.label: {"in_stock": s.in_stock, "qty": s.qty} for s in info.sizes},
                    }
                except Exception as e:
                    print(f"[monitor] Error on product {purl}: {e}")

            await detail_page.close()
        except Exception as e:
            print(f"[monitor] Error on listing {url}: {e}")

    await context.close()
    return state


async def main():
    config = read_config()
    state = read_state()

    headless = bool(config.get("headless", True))

    timeout_ms = int(config.get("request_timeout_ms", 45000))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            while True:
                try:
                    new_state = await monitor_once(browser, config, state)
                    write_state(new_state)
                except Exception as e:
                    print(f"[monitor] Monitor iteration error: {e}")

                poll_minutes = int(config.get("poll_minutes", 5))
                sleep_ms = max(10_000, poll_minutes * 60 * 1000)
                await asyncio.sleep(sleep_ms / 1000)
        finally:
            await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[monitor] Stopped by user")
