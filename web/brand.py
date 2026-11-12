"""The original Fast Finder identity, shared by every web surface."""

BRAND_MARKUP = '''<span class="brand-mark" aria-hidden="true">F</span><span class="brand-word">FAST FINDER</span>'''

# The original red F badge and uppercase wordmark, kept in one place so the
# dashboard, sidebar, landing, watch page and mini app cannot drift apart.
BRAND_CSS = """
.brand-mark{display:inline-block;flex:0 0 auto;background:var(--accent,var(--ac,var(--red,#e50914)));color:#fff;padding:2px 7px;border-radius:3px;font-size:18px;font-weight:900;line-height:1}
.brand-word{color:inherit;font:inherit;letter-spacing:inherit;white-space:nowrap}
.guest-brand{font-size:24px!important}
.guest-brand .brand-mark{font-size:24px}
.sb-logo .brand-mark{font-size:18px}
.tb .brand-mark{font-size:16px;line-height:1.4}
.landing-brand .brand-mark{font-size:24px;padding:2px 8px}
.watch-brand .brand-mark{font-size:24px}
@media(max-width:768px){.watch-brand .brand-mark{font-size:20px;padding:2px 6px}}
@media(max-width:600px){.landing-brand .brand-mark{font-size:18px}}
@media(max-width:400px){
  .topbar{gap:6px;padding:0 10px}
  .topbar .theme-btn{padding:6px 7px;white-space:nowrap}
  .landing-brand + .header-actions{gap:5px}
  .landing-brand + .header-actions .theme-btn,.landing-brand + .header-actions .admin-btn{padding:6px}
}
"""
