OPML = b'''<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0"><body>
  <outline text="System Design">
    <outline text="ByteByteGo" title="ByteByteGo" xmlUrl="https://example.test/feed" htmlUrl="https://example.test" />
  </outline>
</body></opml>'''

RSS = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
  <title>RSS article</title><link>/rss</link>
  <pubDate>Tue, 01 Jul 2025 12:00:00 +0000</pubDate>
</item><item>
  <title>Second RSS article</title><link>/second</link>
  <pubDate>Tue, 01 Jul 2025 13:00:00 +0000</pubDate>
</item></channel></rss>'''

ATOM = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom article</title>
    <link rel="self" href="/self" />
    <link rel="alternate" href="/atom" />
    <updated>2025-07-02T12:00:00Z</updated>
  </entry>
</feed>'''

ATOM_WITH_DEFAULT_ALTERNATE = b'''<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Default alternate</title>
    <link rel="self" href="/self" />
    <link href="/default-alternate" />
  </entry>
</feed>'''

ATOM_WITH_EMPTY_ALTERNATE = b'''<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Fallback alternate</title>
    <link rel="alternate" />
    <link href="/usable-fallback" />
  </entry>
</feed>'''

RSS_WITH_DUPLICATES = b'''<rss version="2.0"><channel>
  <item><title>First</title><link>/entry</link></item>
  <item><title>Duplicate</title><link>/entry</link></item>
  <item><title>No link</title></item>
</channel></rss>'''

RSS_WITH_NEW_ENTRY = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>RSS article</title><link>/rss</link>
    <pubDate>Tue, 01 Jul 2025 12:00:00 +0000</pubDate></item>
  <item><title>Second RSS article</title><link>/second</link>
    <pubDate>Tue, 01 Jul 2025 13:00:00 +0000</pubDate></item>
  <item><title>New article</title><link>/new</link>
    <pubDate>Wed, 02 Jul 2025 12:00:00 +0000</pubDate></item>
</channel></rss>'''

RSS_WITH_NEW_AND_RETRY_ENTRY = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>RSS article</title><link>/rss</link>
    <pubDate>Tue, 01 Jul 2025 12:00:00 +0000</pubDate></item>
  <item><title>Second RSS article</title><link>/second</link>
    <pubDate>Tue, 01 Jul 2025 13:00:00 +0000</pubDate></item>
  <item><title>New article</title><link>/new</link>
    <pubDate>Wed, 02 Jul 2025 12:00:00 +0000</pubDate></item>
  <item><title>Another new article</title><link>/another-new</link>
    <pubDate>Thu, 03 Jul 2025 12:00:00 +0000</pubDate></item>
</channel></rss>'''
