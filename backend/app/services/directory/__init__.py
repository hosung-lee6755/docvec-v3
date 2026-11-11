"""사내 디렉터리(LDAP/AD) 연동(v3 마일스톤 3)."""
from app.core.config import settings
from app.services.directory.ldap_client import DirectoryClient, LdapConfig, LdapDirectoryClient


def get_directory_client() -> DirectoryClient | None:
    """설정으로 AD 클라이언트를 만든다. LDAP 로그인이 꺼져 있으면 None."""
    if not settings.ldap_enabled:
        return None
    return LdapDirectoryClient(LdapConfig(
        url=settings.ldap_url,
        bind_dn=settings.ldap_bind_dn,
        bind_password=settings.ldap_bind_password,
        base_dn=settings.ldap_base_dn,
        group_base_dn=settings.ldap_group_base_dn,
        start_tls=settings.ldap_start_tls,
        tls_verify=settings.ldap_tls_verify,
        ca_cert_file=settings.ldap_ca_cert_file,
        allow_insecure=settings.ldap_allow_insecure,
    ))
