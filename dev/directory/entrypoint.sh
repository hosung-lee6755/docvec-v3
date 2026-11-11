#!/bin/sh
# 개발·테스트 전용 AD DC를 처음 한 번 프로비저닝하고, 테스트 사용자·그룹·공유 폴더를 심는다.
# 비밀번호는 환경변수 DEV_AD_PASSWORD 하나로 받는다(.env에만 두고 커밋하지 않는다).
set -eu

REALM="${DEV_AD_REALM:-DOCVEC.LOCAL}"
DOMAIN="${DEV_AD_DOMAIN:-DOCVEC}"
PASS="${DEV_AD_PASSWORD:?DEV_AD_PASSWORD is required}"
SHARE_DIR=/srv/docs
MARKER=/var/lib/samba/.seeded

if [ ! -f /var/lib/samba/private/sam.ldb ]; then
    rm -f /etc/samba/smb.conf
    samba-tool domain provision --use-rfc2307 --realm="$REALM" --domain="$DOMAIN" \
        --server-role=dc --dns-backend=SAMBA_INTERNAL --adminpass="$PASS" \
        --option="ldap server require strong auth = allow_sasl_over_tls"
fi

if ! grep -q '^\[docs\]' /etc/samba/smb.conf 2>/dev/null; then
    cat >> /etc/samba/smb.conf <<EOF

[docs]
    path = $SHARE_DIR
    read only = no
EOF
fi
mkdir -p "$SHARE_DIR"

samba -F --debug-stdout &
SAMBA_PID=$!

# LDAP와 SMB가 응답할 때까지 기다린다.
i=0
until smbclient -L localhost -U "Administrator%$PASS" >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -gt 60 ] && echo "samba did not start" && exit 1
    sleep 2
done

if [ ! -f "$MARKER" ]; then
    samba-tool domain passwordsettings set --complexity=off --min-pwd-length=4 --max-pwd-age=0

    for u in svc-docvec alice bob carol dave; do
        samba-tool user create "$u" "$PASS" --mail-address="$u@docvec.local" \
            --given-name="$u" --surname="test" >/dev/null
    done
    samba-tool user disable dave

    samba-tool group add sales --description="영업본부"
    samba-tool group add sales-east --description="영업1팀"
    samba-tool group add research --description="연구소"
    samba-tool group add executives --description="임원"
    samba-tool group add docvec-admins --description="docvec 관리자"
    samba-tool group addmembers sales sales-east       # 중첩 그룹
    samba-tool group addmembers sales-east alice
    samba-tool group addmembers research bob
    samba-tool group addmembers executives carol
    samba-tool group addmembers sales carol
    samba-tool group addmembers docvec-admins carol

    mkdir -p "$SHARE_DIR/public" "$SHARE_DIR/sales" "$SHARE_DIR/research" "$SHARE_DIR/exec" \
             "$SHARE_DIR/personal" "$SHARE_DIR/held"
    echo "전사 공지: 사내 규정은 매년 1월에 갱신한다." > "$SHARE_DIR/public/notice.txt"
    echo "영업 계획: 2027년 상반기 신규 고객 목표는 12곳이다." > "$SHARE_DIR/sales/plan.txt"
    echo "연구 사양: 센서 모듈의 샘플링 주기는 10ms다." > "$SHARE_DIR/research/spec.txt"
    echo "임원 보수: 임원 성과급 기준은 영업이익의 2%다." > "$SHARE_DIR/exec/salary.txt"
    echo "개인 메모: alice의 출장 일정은 3월 둘째 주다." > "$SHARE_DIR/personal/alice.txt"
    echo "거부 항목이 있는 문서: 영업본부 공개, 영업1팀 제외." > "$SHARE_DIR/held/denied.txt"
    echo "매핑 불가 문서: 도메인 밖 SID에만 열려 있다." > "$SHARE_DIR/held/unmapped.txt"

    base="REVISION:1,OWNER:$DOMAIN\\Administrator,GROUP:$DOMAIN\\Domain Admins,ACL:$DOMAIN\\Administrator:ALLOWED/0x0/FULL,ACL:$DOMAIN\\svc-docvec:ALLOWED/0x0/READ"
    setacl() {
        smbcacls "//localhost/docs" "$1" -U "Administrator%$PASS" --set "$base$2"
    }
    setacl public/notice.txt ",ACL:$DOMAIN\\Domain Users:ALLOWED/0x0/READ"
    setacl sales/plan.txt ",ACL:$DOMAIN\\sales:ALLOWED/0x0/READ"
    setacl research/spec.txt ",ACL:$DOMAIN\\research:ALLOWED/0x0/READ"
    setacl exec/salary.txt ",ACL:$DOMAIN\\executives:ALLOWED/0x0/READ"
    setacl personal/alice.txt ",ACL:$DOMAIN\\alice:ALLOWED/0x0/READ"
    setacl held/denied.txt ",ACL:$DOMAIN\\sales:ALLOWED/0x0/READ,ACL:$DOMAIN\\sales-east:DENIED/0x0/READ"
    setacl held/unmapped.txt ",ACL:S-1-5-21-1-2-3-1001:ALLOWED/0x0/READ"

    touch "$MARKER"
    echo "dev directory seeded"
fi

wait "$SAMBA_PID"
