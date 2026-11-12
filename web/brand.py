"""The original Fast Finder identity, shared by every web surface."""

BRAND_MARKUP = '''<span class="brand-mark" aria-hidden="true">F</span><span class="brand-word">FAST FINDER</span>'''

# The original red F badge and uppercase wordmark, kept in one place so the
# dashboard, sidebar, landing, watch page and mini app cannot drift apart.
BRAND_CSS = '''
.brand-mark{display:inline-block;flex:0 0 auto;background:var(--accent,var(--ac,var(--red,#e50914)));color:#fff;padding:2px 7px;border-radius:3px;font-size:1em;font-weight:900;line-height:1;letter-spacing:normal}
.brand-word{color:inherit;font:inherit;letter-spacing:inherit;line-height:1;white-space:nowrap}
.sb-logo .brand-mark{font-size:18px}
@media(max-width:400px){.topbar .logo{font-size:15px;letter-spacing:.5px}}
'''
