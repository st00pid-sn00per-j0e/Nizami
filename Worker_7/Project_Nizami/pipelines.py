# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface

import csv
from itemadapter import ItemAdapter

class ProjectNizamiPipeline:
    
    def open_spider(self, spider):
        # spider.csv_filename is set in spider __init__
        self.file = open(spider.csv_filename, 'w', newline='', encoding='utf-8')
        self.writer = csv.writer(self.file)
        self.writer.writerow(["Company Name", "Phone Number", "Category", "Website URL"])

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        self.writer.writerow([
            adapter.get('name'),
            adapter.get('phone'),
            adapter.get('category'),
            adapter.get('website_domain')
        ])
        return item

    def close_spider(self, spider):
        self.file.close()

