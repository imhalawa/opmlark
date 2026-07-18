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

RSS_WITH_DUPLICATES = b'''<rss version="2.0"><channel>
  <item><title>First</title><link>/entry</link></item>
  <item><title>Duplicate</title><link>/entry</link></item>
  <item><title>No link</title></item>
</channel></rss>'''
