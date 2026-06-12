"""DDG html-POST recovery parsing (the keyless rescue when lite GET is blocked).

Live failure: lite.duckduckgo.com served its bot-challenge (HTTP 202) and the
whole chain collapsed to Wikipedia, which cannot answer news queries — the
user got "DuckDuckGo threw up an artificial barrier" for 'last news about
gold'. The html.duckduckgo.com/html POST endpoint sits in a different
anomaly pool and kept returning clean results in live probes; these tests
pin its parser.
"""

from jarvis.tools.builtin.web_search import parse_ddg_html_results


_RESULTS_PAGE = """
<html><body>
<div class="result">
  <a class="result__a" href="https://www.reuters.com/markets/gold/">Gold News | Today's Latest Stories | Reuters</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.kitco.com%2F&amp;rut=abc">Live Gold Prices | Kitco</a>
</div>
<div class="result">
  <a class="result__a" href="https://www.investing.com/commodities/gold-news">Gold News - Investing.com</a>
</div>
<a class="nav-link" href="/settings">Settings</a>
</body></html>
"""

_CHALLENGE_PAGE = '<html><body><div class="anomaly-modal">bots…</div></body></html>'


class TestParseDdgHtmlResults:
    def test_extracts_titles_and_direct_urls(self):
        pairs = parse_ddg_html_results(_RESULTS_PAGE)
        assert pairs[0] == ("Gold News | Today's Latest Stories | Reuters",
                            "https://www.reuters.com/markets/gold/")
        assert len(pairs) == 3

    def test_decodes_uddg_redirects(self):
        pairs = parse_ddg_html_results(_RESULTS_PAGE)
        assert pairs[1] == ("Live Gold Prices | Kitco", "https://www.kitco.com/")

    def test_challenge_page_yields_nothing(self):
        assert parse_ddg_html_results(_CHALLENGE_PAGE) == []

    def test_garbage_yields_nothing(self):
        assert parse_ddg_html_results("") == []
        assert parse_ddg_html_results("<html><body>nothing here</body></html>") == []

    def test_caps_at_five(self):
        many = "".join(
            f'<a class="result__a" href="https://example.com/{i}">Result number {i} title</a>'
            for i in range(9)
        )
        assert len(parse_ddg_html_results(f"<html><body>{many}</body></html>")) == 5


_MOJEEK_PAGE = """
<html><body>
<ul class="results-standard">
 <li><h2><a class="title" href="https://goldsilver.com/industry-news/">Gold and Silver Industry News - GoldSilver</a></h2></li>
 <li><h2><a class="title" href="https://www.newsday.com/business/gold-prices">Gold prices topped $4,300 this week</a></h2></li>
</ul>
<a class="title" href="/about">About Mojeek</a>
</body></html>
"""


class TestParseMojeekResults:
    def test_extracts_absolute_links_only(self):
        from jarvis.tools.builtin.web_search import parse_mojeek_results
        pairs = parse_mojeek_results(_MOJEEK_PAGE)
        assert pairs == [
            ("Gold and Silver Industry News - GoldSilver", "https://goldsilver.com/industry-news/"),
            ("Gold prices topped $4,300 this week", "https://www.newsday.com/business/gold-prices"),
        ]

    def test_garbage_yields_nothing(self):
        from jarvis.tools.builtin.web_search import parse_mojeek_results
        assert parse_mojeek_results("") == []
        assert parse_mojeek_results("<html><body>x</body></html>") == []
