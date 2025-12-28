import re

_SPACE_PATTERN = re.compile(r'\s+')

_allowed_special = re.escape(".!#$%&'*+/=?^_{|}~-")
_USERNAME_PATTERN = re.compile(rf"^[a-zA-Zа-яА-ЯёЁ0-9{_allowed_special}]+$")

_IDN_PATTERN = re.compile(r'^[a-z0-9-]+$', re.IGNORECASE)


def _remove_redundant_whitespaces(text: str) -> str:
    return _SPACE_PATTERN.sub(' ', text).strip()


def _is_valid_username(username: str) -> bool:
    if not username:
        return False
    if username.startswith('.') or username.endswith('.') or ('..' in username):
        return False
    return bool(_USERNAME_PATTERN.match(username))


def _is_valid_domain(domain: str) -> bool:
    if (not domain) or ('.' not in domain) or (len(domain) > 253):
        return False
    if domain.endswith('.'):
        domain = domain[:-1]
    try:
        ascii_domain = domain.encode('idna').decode('ascii').lower()
    except (UnicodeError, ValueError):
        return False
    subdomains = ascii_domain.split('.')
    tld = subdomains[-1]
    if (len(tld) < 2) or tld.isdigit():
        return False
    for subdomain in subdomains:
        if not (1 <= len(subdomain) <= 63):
            return False
        if not _IDN_PATTERN.match(subdomain):
            return False
        if subdomain.startswith('-') or subdomain.endswith('-'):
            return False
    return True


def is_valid_email(email: str) -> bool:
    """ INTERNAL FUNCTION! """
    email = _remove_redundant_whitespaces(email)
    if (len(email) > 254) or ('@' not in email):
        return False
    username, domain = email.rsplit('@', 1)
    if not(_is_valid_username(username)) or not(_is_valid_domain(domain)):
        return False
    return True
