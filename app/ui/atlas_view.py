"""The live Pet Soul Atlas map (petsouls.dev) embedded in the app.

* full    - the whole atlas site (Map tab): pan, zoom, pet card, everything.
* compact - only the map canvas (overlay): side panels hidden, map fills the view.

The page loads once; switching pets only changes the URL hash, which the site handles
by focusing that pet's spawns. All views share one browser profile stored in the user
data folder, so the atlas's own settings persist.
"""
from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

from app.atlas import BASE
from app.paths import USER

_PROFILE: Optional[QWebEngineProfile] = None

# Hide everything except the map. Inline styles (not a <style> tag): the site's security
# policy blocks injected stylesheets but allows element styles.
COMPACT_JS = r"""
(function () {
  if (window.__aion2Compact) return; window.__aion2Compact = true;
  const HIDE = ['.topbar', '.world-tabs', '.sidebar', '.site-footer-links', '.pet-panel', '.map-topleft', '.sheet-toggle'];
  let queued = false;
  function apply() {
    queued = false;
    for (const s of HIDE) document.querySelectorAll(s).forEach(e => e.style.setProperty('display', 'none', 'important'));
    const ma = document.querySelector('.map-area');
    if (ma && ma.style.position !== 'fixed') {
      for (const [k, v] of Object.entries({position: 'fixed', inset: '0', width: '100vw', height: '100vh'}))
        ma.style.setProperty(k, v, 'important');
      window.dispatchEvent(new Event('resize'));
    }
  }
  apply();
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(apply); } })
    .observe(document.documentElement, {childList: true, subtree: true});
})();
"""


def profile() -> QWebEngineProfile:
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = QWebEngineProfile("aion2-atlas")
        store = USER / "web"
        store.mkdir(parents=True, exist_ok=True)
        _PROFILE.setPersistentStoragePath(str(store / "storage"))
        _PROFILE.setCachePath(str(store / "cache"))
        _PROFILE.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
    return _PROFILE


class AtlasView(QWebEngineView):
    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self.compact = compact
        page = QWebEnginePage(profile(), self)
        self.setPage(page)
        if compact:
            s = QWebEngineScript()
            s.setName("aion2-compact")
            s.setSourceCode(COMPACT_JS)
            s.setInjectionPoint(QWebEngineScript.DocumentReady)
            s.setWorldId(QWebEngineScript.MainWorld)
            s.setRunsOnSubFrames(False)
            page.scripts().insert(s)
            self.setZoomFactor(0.8)
        self._loaded = False
        self._pending: Optional[str] = None
        self.current_url: Optional[str] = None
        self.loadFinished.connect(self._on_loaded)

    def show_url(self, url: str):
        """Open an atlas pet link, e.g. https://petsouls.dev/#/altgard/1104."""
        if not url or url == self.current_url:
            return
        self.current_url = url
        if self._loaded and url.startswith(BASE):
            frag = url.split("#", 1)[1] if "#" in url else ""
            self.page().runJavaScript(f"location.hash = {json.dumps('#' + frag)};")
        else:
            self._pending = url
            self.setUrl(QUrl(url))

    def _on_loaded(self, ok: bool):
        self._loaded = ok
        if ok and self.compact:
            self.page().runJavaScript(COMPACT_JS)
