# 개발·테스트 전용 Samba AD DC. 운영에서는 고객사 AD에 붙는다.
# 외부 커뮤니티 이미지 대신 Debian 공식 패키지로 직접 만든다(공급망 신뢰 범위를 줄이기 위해서다).
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        samba samba-ad-provision samba-ad-dc samba-dsdb-modules samba-vfs-modules winbind krb5-user smbclient ldb-tools \
        attr acl ca-certificates procps \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/samba/smb.conf

COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 389 636 445
ENTRYPOINT ["/entrypoint.sh"]
