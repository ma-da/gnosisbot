"""Account-hub application catalog. Add future products here, not in account markup.

Applications share the identity, credit and activity primitives. Each application
owns its own renderer and server APIs. This catalog only advertises launch paths.
"""
APPLICATIONS = (
    {'id':'iching','label':'I Ching Oracle','href':'/quantum-oracle.html',
     'description':'Readings and saved consultations'},
)

def public_apps():
    import os
    apps=[dict(row) for row in APPLICATIONS]
    if os.environ.get('GNOSIS_ENABLE_RUNES')=='1':
        apps.append({'id':'runes','label':'Elder Futhark Oracle','href':'/rune-oracle.html',
                     'description':'Pouch Draw and Circular Sticks readings'})
    return apps
