import scrapy
from scrapy_playwright.page import PageMethod
import random
from urllib.parse import urlparse
from datetime import datetime
from Project_Nizami.items import ProjectNizamiItem

class NizamiGoogleScraperSpider(scrapy.Spider):
    name = "Nizami_Google_Scraper"

    def __init__(self, search=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search = search or "Contractors in Karachi, Sindh, Pakistan"
        parts = [x.strip() for x in self.search.split(",")]
        city = parts[0].replace(" ", "_") if len(parts) > 0 else "UnknownCity"
        state = parts[1].replace(" ", "_") if len(parts) > 1 else "UnknownState"
        country = parts[2].replace(" ", "_") if len(parts) > 2 else "UnknownCountry"
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.csv_filename = f"{city}_{state}_{country}_{timestamp}.csv"

    def start_requests(self):
        yield scrapy.Request(
            url="https://www.google.com/maps",
            meta={
                "playwright": True,
                "playwright_page_methods": {
                    "search_box": PageMethod("wait_for_selector", "#ucc-1"),
                    "type_search": PageMethod("type", "#ucc-1", self.search, delay=120),
                    "wait_after_type": PageMethod("wait_for_timeout", 5000),
                    "results_button_wait": PageMethod(
                        "wait_for_selector",
                        (
                            "body > div:nth-child(5) > div.lbMcOd.eZfyae.xcUKcd.y2Sqzf > "
                            "div.UL7Qtf > div.Owrmqf.t090lc > div.AJQtp.Hk4XGb > div.hzegWb "
                            "> div > div.xoLGzf.nhb85d.Hk4XGb.tzDryd.FkJ4Sc.OAaR7b.A6Eb0 > "
                            "div.pzfvzf > button > span"
                        ),
                    ),
                    "results_button_click": PageMethod(
                        "click",
                        (
                            "body > div:nth-child(5) > div.lbMcOd.eZfyae.xcUKcd.y2Sqzf > "
                            "div.UL7Qtf > div.Owrmqf.t090lc > div.AJQtp.Hk4XGb > div.hzegWb "
                            "> div > div.xoLGzf.nhb85d.Hk4XGb.tzDryd.FkJ4Sc.OAaR7b.A6Eb0 > "
                            "div.pzfvzf > button > span"
                        ),
                    ),
                    "wait_after_click": PageMethod("wait_for_timeout", 10000),
                    "scroll_results": PageMethod(self.scroll_results_feed),
                    "extract_cards": PageMethod(self.extract_card_data),
                },
            },
            callback=self.parse,
        )

    async def scroll_results_feed(self, page):
        await page.wait_for_selector('[role="feed"]')
        await page.evaluate('document.querySelector(\'[role="feed"]\').focus()')
        previous_count = 0
        while True:
            for _ in range(5):
                await page.keyboard.press("PageDown")
                await page.wait_for_timeout(300)
            await page.wait_for_timeout(2500)
            current_count = await page.evaluate('''
                () => document.querySelectorAll('a.hfpxzc, a[href*="/place/"]').length
            ''')
            self.logger.info("Loaded cards: %s", current_count)
            if current_count == previous_count:
                self.logger.info("No new results. Stopping.")
                break
            previous_count = current_count

    async def extract_card_data(self, page):
        return await page.evaluate('''
            () => {
                const cards = document.querySelectorAll('div[role="article"]');
                const results = [];
                const seenNames = new Set();
                
                for (const card of cards) {
                    // Name
                    let name = null;
                    const nameEl = card.querySelector('div.qBF1Pd.fontHeadlineSmall');
                    if (nameEl) name = nameEl.innerText.trim();
                    if (!name) {
                        const altName = card.querySelector('div.fontHeadlineSmall');
                        if (altName) name = altName.innerText.trim();
                    }
                    if (!name) continue;
                    
                    // Skip duplicates
                    if (seenNames.has(name)) continue;
                    seenNames.add(name);
                    
                    // Phone
                    let phone = null;
                    const phoneEl = card.querySelector('span.UsdlK');
                    if (phoneEl) phone = phoneEl.innerText.trim();
                    
                    // Category
                    let category = null;
                    const catEl = card.querySelector('div.W4Efsd div.W4Efsd > span > span');
                    if (catEl) category = catEl.innerText.trim();
                    if (!category) {
                        const catAlt = card.querySelector('div.W4Efsd span:first-child');
                        if (catAlt) category = catAlt.innerText.trim();
                    }
                    
                    // Website URL
                    let domain = null;
                    const webEl = card.querySelector('a[data-value="Website"]');
                    if (webEl) {
                        const candidates = [
                            webEl.getAttribute('href'),
                            webEl.href,
                        ].filter(Boolean);

                        for (const candidate of candidates) {
                            try {
                                const url = new URL(candidate, window.location.origin);
                                const isGoogleHost = /(^|\\.)google\\./i.test(url.hostname);

                                if (!isGoogleHost) {
                                    domain = url.toString();
                                    break;
                                }

                                const wrappedTarget =
                                    url.searchParams.get('q') ||
                                    url.searchParams.get('url') ||
                                    url.searchParams.get('adurl');

                                if (!wrappedTarget) {
                                    continue;
                                }

                                const targetUrl = new URL(wrappedTarget);
                                if (!/(^|\\.)google\\./i.test(targetUrl.hostname)) {
                                    domain = targetUrl.toString();
                                    break;
                                }
                            } catch(e) {}
                        }
                    }
                    
                    results.push({ name, phone, category, website_domain: domain });
                }
                return results;
            }
        ''')

    def parse(self, response):
        page_methods = response.meta.get("playwright_page_methods", {})
        extract_cards = page_methods.get("extract_cards")
        card_data = extract_cards.result if extract_cards and extract_cards.result else []
        self.logger.info(f"Extracted {len(card_data)} unique business cards")
        for item_data in card_data:
            yield ProjectNizamiItem(
                name=item_data['name'],
                phone=item_data['phone'],
                category=item_data['category'],
                website_domain=item_data['website_domain']
            )
            self.logger.info(f"Saved: {item_data['name']}")
        yield {
            "search": self.search,
            "title": response.css("title::text").get(),
            "url": response.url,
            "results_loaded": len(card_data),
            "results": card_data,
            "csv_file": self.csv_filename,
        }
