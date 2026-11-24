#!/bin/sh
# 원문 보기에서 원본을 그대로 그리는 데 필요한 LibreOffice 구성 요소를 설치한다(2026-11-23).
#
# - libreoffice-calc, libreoffice-impress: XLSX, PPTX 원본을 PDF로 그린다. writer만 있으면 이 두 형식은
#   추출한 글로 다시 적은 HTML로 내려간다.
# - H2Orestart: 한글(HWP, HWPX) 원본을 LibreOffice가 열 수 있게 하는 확장이다. Java가 필요하다.
#   버전과 sha256을 고정해 받은 파일이 바뀌면 빌드가 멈추게 한다.
set -eu

H2ORESTART_VERSION=0.8.0
H2ORESTART_SHA256=f36c19fa6b7dff1cf34114d926bdc088e6bcfa7fdc93d67eaafd3f572be1d62c
H2ORESTART_URL="https://github.com/ebandal/H2Orestart/releases/download/v${H2ORESTART_VERSION}/H2Orestart.oxt"

apt-get update
apt-get install -y --no-install-recommends \
    libreoffice-calc \
    libreoffice-impress \
    libreoffice-java-common \
    default-jre-headless
rm -rf /var/lib/apt/lists/*

curl -fsSL -o /tmp/H2Orestart.oxt "$H2ORESTART_URL"
echo "${H2ORESTART_SHA256}  /tmp/H2Orestart.oxt" | sha256sum -c -
unopkg add --shared /tmp/H2Orestart.oxt
rm -f /tmp/H2Orestart.oxt
unopkg list --shared | grep -qi "h2orestart"
