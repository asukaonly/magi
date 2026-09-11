/** Map native connection protocol errors to localized recovery instructions. */
export function connectionErrorKey(code: string): string | null {
  switch (code) {
    case 'invalid_pairing_format': return 'connections.errors.pairingFormat';
    case 'invalid_pairing_grant': return 'connections.errors.pairingRejected';
    case 'invalid_client_credential': return 'connections.errors.deviceCredential';
    case 'client_auth_required': return 'connections.errors.sessionExpired';
    case 'origin_not_allowed': return 'connections.errors.originRejected';
    case 'center_authorization_rejected': return 'connections.errors.authorizationRejected';
    case 'auth_busy': return 'connections.errors.busy';
    default: return null;
  }
}
