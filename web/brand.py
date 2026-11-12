"""FastFinder's shared vector identity; no image download or external dependency."""

# A compact F monogram with a forward/play cut: readable even in a 32px header.
BRAND_MARKUP = '''<span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M10 11.5h18l-2.3 4H14.5l-1.1 3.4h9.8l-2.3 4h-8.7l-2 5.7H6.1L10 11.5Z" fill="white"/><path d="m25.1 19.1 6.5 4-9 5.7 2.5-9.7Z" fill="white" opacity=".92"/></svg></span><span class="brand-word">Fast<span>Finder</span></span>'''

BRAND_CSS = '''
.brand-mark{width:36px;height:36px;flex:0 0 36px;display:inline-grid;place-items:center;border-radius:11px;background:linear-gradient(145deg,#f23d49 0%,#d8091b 58%,#a80617 100%);box-shadow:inset 0 1px 1px rgba(255,255,255,.26),0 4px 10px rgba(157,5,22,.24)}
.brand-mark svg{width:34px;height:34px;display:block}
.brand-word{color:var(--text,var(--txt,#fff));font-family:'DM Sans',sans-serif;font-size:20px;font-weight:900;letter-spacing:-.8px;line-height:1;white-space:nowrap;text-transform:none}
.brand-word>span{color:#e72132}
.sb-logo .brand-mark{width:33px;height:33px;flex-basis:33px;border-radius:10px}
.sb-logo .brand-mark svg{width:31px;height:31px}
.sb-logo .brand-word{font-size:18px}
@media(max-width:480px){.brand-mark{width:33px;height:33px;flex-basis:33px;border-radius:10px}.brand-mark svg{width:31px;height:31px}.brand-word{font-size:18px}}
'''
