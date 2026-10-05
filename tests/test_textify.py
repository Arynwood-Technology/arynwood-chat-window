from chat_window.textify import chunk_page, parse_html

PAGE = """<!doctype html><html lang="en-US"><head><title> Widgets | Demo </title>
<meta name="description" content="All about widgets."><link rel="canonical" href="https://demo.example/widgets"></head>
<body><header><nav><a href="/">Home</a><a href="/about">About</a></nav></header>
<div id="intro"><h1>Widgets</h1><p>We make <b>blue</b> widgets.</p></div>
<script>var secret = "do not index";</script><style>.x{}</style>
<section><h2 id="pricing">Pricing</h2><p>Small: $4.00/month</p><ul><li>1 GB</li><li>2 cores</li></ul>
<h3>Add-ons</h3><p>Extra disk.</p></section>
<details><summary>Do you ship abroad?</summary><p>Yes, to 30 countries.</p></details>
<form><input name="q"><button>Search</button></form>
<div hidden>Hidden text</div><p aria-hidden="true">Decor</p>
<footer>© Demo Co. Privacy</footer></body></html>"""


def test_body_without_chrome_scripts_or_hidden_text():
    page = parse_html("https://demo.example/widgets", PAGE)
    text = "\n".join(s.text for s in page.sections)
    assert page.title == "Widgets | Demo" and page.lang == "en-us"
    assert page.description == "All about widgets." and page.canonical == "https://demo.example/widgets"
    assert "We make blue widgets." in text
    for absent in ("Home", "do not index", "Search", "Hidden text", "Decor", "© Demo"):
        assert absent not in text


def test_headings_make_sections_with_paths_and_anchors():
    page = parse_html("https://demo.example/widgets", PAGE)
    by_heading = {s.heading: s for s in page.sections}
    assert by_heading["Pricing"].anchor == "pricing"
    assert by_heading["Pricing"].text.splitlines() == ["Small: $4.00/month", "1 GB", "2 cores"]
    assert "Pricing › Add-ons" in by_heading
    assert by_heading["Pricing › Add-ons › Do you ship abroad?"].text == "Yes, to 30 countries."


def test_main_is_preferred_when_present():
    html = "<body><header><h1>Site</h1></header><main><h1>Article</h1><p>Body</p></main><aside><p>Ad</p></aside></body>"
    page = parse_html("https://demo.example/a", html)
    assert [s.text for s in page.sections] == ["Body"]


def test_noindex_and_sloppy_markup():
    page = parse_html("https://demo.example/x", '<meta name="robots" content="NOINDEX, follow"><p>a<p>b</div>c')
    assert page.noindex
    assert page.sections[0].text.split("\n") == ["a", "bc"]   # a stray </div> is ignored, as browsers do


def test_chunks_keep_url_anchor_and_respect_size():
    long = " ".join(f"Sentence number {i} is here." for i in range(200))
    html = f"<h1>T</h1><h2 id='s'>Long</h2><p>{long}</p>"
    chunks = chunk_page(parse_html("https://demo.example/l", html), max_chars=400, overlap=80)
    assert len(chunks) > 5
    assert all(len(c.text) <= 400 + 82 for c in chunks)
    assert all(c.url == "https://demo.example/l#s" and c.heading == "Long" for c in chunks)
    assert chunks[1].text.split("\n")[0] in chunks[0].text      # overlap carries context forward


def test_empty_page_falls_back_to_description():
    chunks = chunk_page(parse_html("https://demo.example/e", '<meta name="description" content="Just this.">'))
    assert [c.text for c in chunks] == ["Just this."]
