#!/usr/bin/env python3
"""Record the short looping clips on docs/help.html as animated WebP.

    .venv/bin/python tools/help_clips.py            # all clips
    .venv/bin/python tools/help_clips.py places     # just one

Serves docs/ locally, drives the explorer with Playwright (a drawn cursor shows where the "user" points),
captures a frame per step and writes docs/help/<name>.webp. Needs Pillow (`uv pip install pillow`).
Re-run after UI changes so the help page matches the app.
"""
import functools
import http.server
import io
import pathlib
import sys
import threading

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "help"
PORT = 8099
VIEW = {"width": 1200, "height": 720}
SCALE = 0.75  # output width 900px

CURSOR_JS = """
(() => {
  const c = document.createElement('div');
  c.id = 'demo-cursor';
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 14 L10.5 20.5 L13 19.4 L10 13 L16 13 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, {position: 'fixed', left: '0', top: '0', zIndex: 2147483647, pointerEvents: 'none',
                          transform: 'translate(-100px,-100px)'});
  const ring = document.createElement('div');
  Object.assign(ring.style, {position: 'fixed', width: '28px', height: '28px', borderRadius: '50%', zIndex: 2147483646,
    border: '2px solid #6fa8ec', pointerEvents: 'none', opacity: '0', left: '0', top: '0'});
  document.body.append(c, ring);
  addEventListener('mousemove', e => { c.style.transform = `translate(${e.clientX - 3}px, ${e.clientY - 2}px)`; }, true);
  addEventListener('mousedown', e => { ring.style.transform = `translate(${e.clientX - 14}px, ${e.clientY - 14}px)`; ring.style.opacity = '1'; }, true);
  addEventListener('mouseup', () => setTimeout(() => { ring.style.opacity = '0'; }, 250), true);
})();
"""


class Clip:
    def __init__(self, page):
        self.page = page
        self.frames = []
        self.pos = (VIEW["width"] / 2, VIEW["height"] / 2)

    def snap(self, ms=70):
        png = self.page.screenshot(type="png")
        im = Image.open(io.BytesIO(png)).convert("RGB")
        im = im.resize((int(im.width * SCALE), int(im.height * SCALE)), Image.LANCZOS)
        self.frames.append((im, ms))

    def hold(self, ms):
        self.snap(ms)

    def move(self, x, y, steps=10):
        x0, y0 = self.pos
        for i in range(1, steps + 1):
            self.page.mouse.move(x0 + (x - x0) * i / steps, y0 + (y - y0) * i / steps)
            self.snap(45)
        self.pos = (x, y)

    def to(self, locator, steps=10, dx=0.5, dy=0.5):
        box = locator.bounding_box()
        self.move(box["x"] + box["width"] * dx, box["y"] + box["height"] * dy, steps)

    def click(self, locator=None, steps=10, settle=500):
        if locator is not None:
            self.to(locator, steps)
        self.page.mouse.down()
        self.snap(90)
        self.page.mouse.up()
        self.page.wait_for_timeout(settle)
        self.snap(400)

    def type(self, text):
        for ch in text:
            self.page.keyboard.type(ch)
            self.page.wait_for_timeout(60)
            self.snap(110)

    def drag(self, x0, y, x1, steps=18):
        self.move(x0, y)
        self.page.mouse.down()
        self.snap(150)
        for i in range(1, steps + 1):
            self.page.mouse.move(x0 + (x1 - x0) * i / steps, y)
            self.snap(55)
        self.page.mouse.up()
        self.pos = (x1, y)
        self.page.wait_for_timeout(400)
        self.snap(400)

    def save(self, name):
        OUT.mkdir(exist_ok=True)
        imgs = [f[0] for f in self.frames]
        durs = [f[1] for f in self.frames]
        durs[-1] = max(durs[-1], 1800)  # rest on the result before looping
        path = OUT / f"{name}.webp"
        imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=durs, loop=0, quality=72, method=5)
        print(f"{name}: {len(imgs)} frames, {sum(durs) / 1000:.1f}s, {path.stat().st_size / 1024:.0f}KB")


def open_app(page, hash_=""):
    page.goto(f"http://localhost:{PORT}/{hash_}")
    page.wait_for_selector("#loading", state="hidden", timeout=90000)
    page.wait_for_timeout(600)
    page.evaluate(CURSOR_JS)


def chart_x(page, income):
    """Screen x of an income on the chart's log axis (domain $1,000 to $2.5M)."""
    return page.evaluate("""(v) => {
      const s = document.getElementById('chart-svg').getBoundingClientRect();
      const ticks = [...document.querySelectorAll('#chart-svg .tick')].map(t => ({t: t.textContent, x: t.getBoundingClientRect().x + t.getBoundingClientRect().width / 2}));
      const a = ticks.find(t => t.t === '$10k'), b = ticks.find(t => t.t === '$1M');
      if (!a || !b) return s.x + s.width / 2;
      return a.x + (Math.log10(v) - 4) / 2 * (b.x - a.x);
    }""", income)


# ---- the clips ---------------------------------------------------------------------------------------------

def clip_chart(c):
    p = c.page
    open_app(p)
    c.hold(900)
    svg = p.locator("#chart-svg").bounding_box()
    y = svg["y"] + svg["height"] * 0.45
    for income in (45000, 120000, 400000):
        c.move(chart_x(p, income), y, 12)
        dot = p.evaluate("""([x, y]) => {
          const els = document.elementsFromPoint(x, y).filter(e => e.tagName === 'circle');
          return els.length > 0;
        }""", [chart_x(p, income), y])
        if not dot:
            # nudge until the pointer sits on a dot, so the tooltip shows
            for dy in (6, -6, 12, -12, 18, -18):
                if p.evaluate("([x, y]) => document.elementsFromPoint(x, y).some(e => e.tagName === 'circle')", [chart_x(p, income), y + dy]):
                    c.move(chart_x(p, income), y + dy, 3)
                    break
        p.wait_for_timeout(250)
        c.hold(1300)
    c.click(p.locator(".cm-btn[data-mode='age_bucket']"), steps=14, settle=700)
    c.hold(1200)


def clip_filters(c):
    p = c.page
    open_app(p)
    c.hold(700)
    c.click(p.locator(".tab-btn[data-tab='work']"))
    c.click(p.locator('#f-work_status .f-btn[data-val="5"]'), settle=700)
    c.to(p.locator("#stats-panel"), steps=12)
    c.hold(1200)
    c.click(p.locator(".tab-btn[data-tab='demo']"))
    c.click(p.locator('#f-age_bucket .f-btn[data-val="7"]'), settle=700)  # 65+
    c.to(p.locator("#active-chips"), steps=12)
    c.hold(1300)
    c.click(p.locator("#active-chips .chip").first, settle=700)
    c.hold(1000)


def clip_places(c):
    p = c.page
    open_app(p)
    c.hold(600)
    c.click(p.locator(".tab-btn[data-tab='geo']"))
    c.click(p.locator("#place-search"), settle=200)
    c.type("medford")
    c.hold(700)
    c.click(p.locator(".place-item", has_text="Malden & Medford").first, settle=1500)
    c.to(p.locator("#place-context"), steps=14)
    c.hold(2200)
    c.click(p.locator("#place-current button", has_text="Massachusetts"), settle=900)
    c.hold(1500)


def clip_range(c):
    p = c.page
    open_app(p)
    c.hold(600)
    c.click(p.locator("#btn-brush"))
    svg = p.locator("#chart-svg").bounding_box()
    c.drag(chart_x(p, 100000), svg["y"] + svg["height"] * 0.55, chart_x(p, 250000))
    c.to(p.locator("#stats-range"), steps=14)
    c.hold(2000)


def clip_views(c):
    p = c.page
    open_app(p, "#states=6")
    c.hold(700)
    c.click(p.locator(".view-btn[data-view='bars']"), settle=700)
    c.hold(900)
    c.click(p.locator(".view-btn[data-view='pct']"), settle=700)
    c.hold(900)
    c.click(p.locator(".view-btn[data-view='dots']"), settle=700)
    c.click(p.locator("#btn-showall"), settle=800)
    c.hold(1200)
    c.click(p.locator("#btn-static"), settle=800)
    c.hold(900)


def clip_surveys(c):
    p = c.page
    open_app(p, "#passive_source=1")
    c.hold(700)
    c.to(p.locator("#other-src"), steps=14)
    c.hold(1800)
    c.to(p.locator("#source-switch button[data-src='cps']"), steps=16)
    p.mouse.down(); c.snap(90); p.mouse.up()
    for _ in range(40):  # the page reloads with the other survey
        p.wait_for_timeout(150)
        try:
            c.snap(150)
            if p.locator("#loading").is_hidden():
                break
        except Exception:  # noqa: BLE001  (mid-navigation)
            pass
    p.wait_for_selector("#loading", state="hidden", timeout=90000)
    p.wait_for_timeout(600)
    p.evaluate(CURSOR_JS)
    p.mouse.move(*c.pos)
    c.to(p.locator("#other-src"), steps=10)
    c.hold(2000)


def clip_pin(c):
    p = c.page
    open_app(p, "#metro_area=14460")
    c.hold(600)
    # a dot near the middle whose centre isn't covered by another dot, so a real click lands on it
    x, y, age = p.evaluate("""() => {
      const s = document.getElementById('chart-svg').getBoundingClientRect();
      const cs = [...document.querySelectorAll('#chart-svg circle')].map(c => ({c, b: c.getBoundingClientRect()}))
        .filter(({c, b}) => b.width >= 8 && document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2) === c)
        .sort((a, b) => Math.abs(a.b.x - s.x - s.width * 0.55) + Math.abs(a.b.y - s.y - s.height * 0.45)
                      - Math.abs(b.b.x - s.x - s.width * 0.55) - Math.abs(b.b.y - s.y - s.height * 0.45));
      const {c, b} = cs[0];
      return [b.x + b.width / 2, b.y + b.height / 2, currentCols().age_bucket[c.__data__.i]];
    }""")
    c.move(x, y, 14)
    p.wait_for_timeout(250)
    c.hold(700)
    c.click(settle=500)
    c.to(p.locator("#stats-household"), steps=14, dy=0.3)
    c.hold(1800)
    c.click(p.locator(".tab-btn[data-tab='demo']"))
    other = 0 if age != 0 else 7
    c.click(p.locator(f'#f-age_bucket .f-btn[data-val="{other}"]'), settle=700)
    c.to(p.locator("#pin-card .pin-status"), steps=12)
    c.hold(1500)
    c.move(x, y, 14)
    c.hold(1000)
    c.click(p.locator(f'#f-age_bucket .f-btn[data-val="{other}"]'), steps=14, settle=300)
    c.click(p.locator(f'#f-age_bucket .f-btn[data-val="{age}"]'), steps=8, settle=700)
    c.to(p.locator("#pin-card .pin-status"), steps=12)
    c.hold(1500)


CLIPS = {"chart": clip_chart, "pin": clip_pin, "filters": clip_filters, "places": clip_places, "range": clip_range,
         "views": clip_views, "surveys": clip_surveys}


def main():
    names = sys.argv[1:] or list(CLIPS)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DOCS))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("localhost", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name in names:
            page = browser.new_page(viewport=VIEW, device_scale_factor=1)
            clip = Clip(page)
            CLIPS[name](clip)
            clip.save(name)
            page.close()
        browser.close()
    srv.shutdown()


if __name__ == "__main__":
    main()
