"""One lightweight FastFinder identity for all web and mini-app headers."""

BRAND_MARKUP = '''<span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3.8 11.2h5M2.8 15.2h4.7M4.4 19.2h4.1" stroke="white" stroke-width="2.2" stroke-linecap="round" opacity=".78"/><circle cx="17.4" cy="14.7" r="7.1" stroke="white" stroke-width="2.7"/><path d="m22.7 20 4.4 4.5" stroke="white" stroke-width="2.9" stroke-linecap="round"/><path d="m18.3 10.1-3 4.7h2.8l-1.6 4.2 4-5.5h-2.9l1.3-3.4Z" fill="white"/></svg></span><span class="brand-word">Fast<span>Finder</span></span>'''

BRAND_CSS = '''
.brand-mark{width:34px;height:34px;flex:0 0 34px;display:inline-grid;place-items:center;border-radius:10px;background:linear-gradient(145deg,#ff5058 0%,#e50914 50%,#a80816 100%);box-shadow:0 5px 14px rgba(229,9,20,.27),inset 0 1px 0 rgba(255,255,255,.22)}
.brand-mark svg{width:25px;height:25px;display:block}
.brand-word{color:var(--text,var(--txt,#fff));font-family:'DM Sans',sans-serif;font-size:20px;font-weight:900;letter-spacing:-.7px;line-height:1;white-space:nowrap;text-transform:none}
.brand-word>span{color:#ee303c}
.sb-logo .brand-mark{width:31px;height:31px;flex-basis:31px;border-radius:9px}
.sb-logo .brand-mark svg{width:23px;height:23px}
.sb-logo .brand-word{font-size:18px}
@media(max-width:480px){.brand-mark{width:31px;height:31px;flex-basis:31px;border-radius:9px}.brand-mark svg{width:23px;height:23px}.brand-word{font-size:18px}}
'''
