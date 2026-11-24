from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from app.api.routes import router
from app.api.system import router as system_router
from gnosis_platform.auth_api import router as accounts_router
from gnosis_platform.consultations_api import router as consultations_router
from gnosis_platform.ibm_admin_trial_api import router as ibm_admin_trial_router
from gnosis_platform.account_hub_api import router as account_hub_router
import os

ROOT=Path(__file__).resolve().parent
app=FastAPI(title='gnosis.bot',version='0.10.0-alpha.1',description='Gnosis research alpha: I Ching and Elder Futhark')
app.include_router(router)
app.include_router(system_router)
# Public native contact API: disabled until explicitly activated.
from gnosis_platform.site_contact_api import router as site_contact_router
app.include_router(site_contact_router)
if os.environ.get('GNOSIS_ENABLE_ACCOUNTS_API') == '1':
    app.include_router(accounts_router)
    app.include_router(consultations_router)
    app.include_router(ibm_admin_trial_router)
    app.include_router(account_hub_router)
    # Staging-only authenticated purchase UI contract; no live payment processing.
    from gnosis_platform.commerce_stage_api import router as commerce_preview_router
    app.include_router(commerce_preview_router)
    # Gnosis admin dashboard: authorization checked per request.
    from gnosis_platform.admin_api import router as gnosis_admin_router
    app.include_router(gnosis_admin_router)
    # Administrator-only contact messages and manual Resend tools.
    from gnosis_platform.admin_contacts_api import router as admin_contacts_router
    app.include_router(admin_contacts_router)
    # Administrator-only encrypted media/outreach CRM.
    from gnosis_platform.admin_media_api import router as admin_media_router
    app.include_router(admin_media_router)
    from gnosis_platform.admin_credits_api import router as credits_admin_router, claims as credits_claims_router
    app.include_router(credits_admin_router)
    app.include_router(credits_claims_router)
    # Authenticated, origin-protected Financials administration.
    from gnosis_platform.admin_financials_api import router as financials_admin_router
    app.include_router(financials_admin_router)
    # Optional, authenticated editorial workspace. No corpus or DB writes.
    from gnosis_platform.interpretation_editor_api import router as interpretation_editor_router
    app.include_router(interpretation_editor_router)

app.mount('/assets',StaticFiles(directory=ROOT/'static'),name='assets')

@app.get('/',include_in_schema=False)
async def home():
    return FileResponse(ROOT/'static'/'index.html')



# Public site policies: content is static, with no account or database access.
# AI Policy: a public static page; modal fetches the same HTML article.
@app.get('/ai-policy.html', include_in_schema=False)
async def gnosis_ai_policy_page():
    return FileResponse(ROOT / 'static' / 'ai-policy.html')

@app.get('/terms.html', include_in_schema=False)
async def gnosis_terms_page():
    return FileResponse(ROOT / 'static' / 'terms.html')

@app.get('/privacy.html', include_in_schema=False)
async def gnosis_privacy_page():
    return FileResponse(ROOT / 'static' / 'privacy.html')

@app.get('/quantum-oracle.html', include_in_schema=False)
async def quantum_oracle():
    return FileResponse(ROOT / 'static' / 'quantum-oracle.html')

@app.get('/quantum-orcle.html', include_in_schema=False)
async def typo_redirect():
    return RedirectResponse(url='/quantum-oracle.html', status_code=308)


@app.get('/account.html', include_in_schema=False)
async def account_page():
    return FileResponse(ROOT / 'static' / 'account.html')

@app.get('/qci-reading.html', include_in_schema=False)
async def qci_reading_page():
    return FileResponse(ROOT / 'static' / 'qci-reading.html')


# M3C reading history: same opt-in gate as accounts.
if os.environ.get('GNOSIS_ENABLE_ACCOUNTS_API') == '1':
    from gnosis_platform.history_api import router as reading_history_router
    app.include_router(reading_history_router)

@app.get('/reading-history.html', include_in_schema=False)
async def reading_history_page():
    return RedirectResponse(url='/account.html?view=activity',status_code=302)


# M3D public research observatory: aggregate-only, never expose personal readings.
from gnosis_platform.research_dashboard import router as research_dashboard_router
app.include_router(research_dashboard_router)
from gnosis_platform.classic_research_api import router as classic_research_router
app.include_router(classic_research_router)

@app.get('/research', include_in_schema=False)
@app.get('/research.html', include_in_schema=False)
async def research_dashboard_page():
    return FileResponse(ROOT / 'static' / 'research.html')

@app.get('/ibm-trial-pending.html', include_in_schema=False)
async def ibm_trial_pending_page(request: Request):
    cid=request.query_params.get('id','')
    suffix=('&reading='+cid if len(cid)==32 and all(c in '0123456789abcdef' for c in cid) else '')
    return RedirectResponse(url='/account.html?view=activity'+suffix,status_code=302)

# GNOSIS M5A: public, read-only rune demonstration page.
@app.get("/rune-oracle.html", include_in_schema=False)
async def gnosis_m5a_rune_page():
    from pathlib import Path
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).resolve().parent / "static" / "rune-oracle.html")

# GNOSIS M5A RUNE DEMO — synthetic fixtures only.
import os as _m5a_os
if _m5a_os.environ.get('GNOSIS_ENABLE_RUNE_DEMO') == '1':
    from gnosis_platform.rune_demo_api import router as _m5a_rune_router
    app.include_router(_m5a_rune_router)

# I Ching corpus — scoped presentation boundary
from app.services.corpus import CorpusPresentation as _CorpusPresentation
app.add_middleware(_CorpusPresentation)
