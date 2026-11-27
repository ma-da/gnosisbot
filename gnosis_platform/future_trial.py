"""Authenticated Future admission policy, with legacy manual trials retained for recovery."""
import os
SERVICES=('iching.quantum_future','runes.pouch.quantum_future','runes.sticks.quantum_future')
def allowed(user, service):
    from .future_auto_policy import production_enabled
    return (service in SERVICES and bool(user) and
            (production_enabled() or (os.getenv('GNOSIS_ENABLE_QUANTUM_FUTURE')!='YES' and bool(user.get('is_admin')) and
              os.getenv('GNOSIS_ALLOW_CONTROLLED_ADMIN_TRIAL')=='YES' and
              os.getenv('GNOSIS_ENABLE_IBM_ADMIN_TRIAL')=='YES' and
              os.getenv('GNOSIS_ENABLE_READING_COMPLETION_EVENTS')=='YES')) and
            (service.startswith('iching.') or os.getenv('GNOSIS_ENABLE_RUNES')=='1'))
