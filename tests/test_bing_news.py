from xml.etree import ElementTree

from stocktracker.sources.bing_news import BingNewsCollector


def test_maps_rss_item_and_unwraps_url() -> None:
    item = ElementTree.fromstring(
        """
        <item>
          <title>某上市公司第一大股东发生变更</title>
          <link>https://www.bing.com/news/apiclick?url=https%3A%2F%2Fexample.com%2Fnews%2F1</link>
          <description><![CDATA[公司公告称，第一大股东发生变更。]]></description>
          <pubDate>Mon, 16 Aug 2026 02:00:00 GMT</pubDate>
        </item>
        """
    )
    document = BingNewsCollector(http=None)._from_item(item)
    assert document.url == "https://example.com/news/1"
    assert document.matched_events == ["largest_shareholder_change"]
    assert document.content_status == "rss_summary"

