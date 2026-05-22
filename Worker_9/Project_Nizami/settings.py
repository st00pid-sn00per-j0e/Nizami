# Scrapy settings for Project_Nizami project

BOT_NAME = "Project_Nizami"

SPIDER_MODULES = ["Project_Nizami.spiders"]
NEWSPIDER_MODULE = "Project_Nizami.spiders"

# Obey robots.txt rules
ROBOTSTXT_OBEY = False
TELNETCONSOLE_PORT = None
USER_AGENT = None



# Download handlers for Playwright
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright_stealth.handler.ScrapyPlaywrightStealthDownloadHandler",
    "https": "scrapy_playwright_stealth.handler.ScrapyPlaywrightStealthDownloadHandler",
}



TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

PLAYWRIGHT_BROWSER_TYPE = "chromium"


PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": False,
    "slow_mo": 200,
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--no-sandbox",
    ]
}

# Limit concurrency because Playwright uses a real browser
CONCURRENT_REQUESTS = 1

# Enable your CSV pipeline
ITEM_PIPELINES = {
    'Project_Nizami.pipelines.ProjectNizamiPipeline': 300,
}

# Optional: export encoding
FEED_EXPORT_ENCODING = "utf-8"