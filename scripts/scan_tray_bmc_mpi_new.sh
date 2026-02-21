#!/usr/bin/env bash
# If someone runs "sh script.sh", force bash:
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

set -euo pipefail

LEASES_FILE="${LEASES_FILE:-/var/lib/dhcp/dhcpd.leases}"
STATE_DIR="${SCAN_STATE_DIR:-/root/TIN/scan_state}"
mkdir -p "$STATE_DIR"
CACHE_FILE="$STATE_DIR/cache.tsv"
BLACKLIST_FILE="$STATE_DIR/blacklist.txt"
FAILURES_FILE="$STATE_DIR/failures.tsv"

# Only scan these hostnames (edit if needed)
ALLOW_HOSTS_REGEX="${ALLOW_HOSTS_REGEX:-bmc}"
EXCLUDE_HOSTS_REGEX="${EXCLUDE_HOSTS_REGEX:-dpu-bmc}"

PING_TIMEOUT="${PING_TIMEOUT:-1}"
LOGIN_TIMEOUT="${LOGIN_TIMEOUT:-5}"
FRU_TIMEOUT="${FRU_TIMEOUT:-25}"
CACHE_TTL="${CACHE_TTL:-900}"
PARALLEL="${PARALLEL:-8}"
BLACKLIST_FAIL_THRESHOLD="${BLACKLIST_FAIL_THRESHOLD:-5}"

BMC_USER="${BMC_USER:-root}"
BMC_PASS="${BMC_PASS:-0penBmc}"
IPMI_IF="${IPMI_IF:-lanplus}"
IPMI_CIPHER="${IPMI_CIPHER:-17}"
IPMI_RETRY="${IPMI_RETRY:-1}"
IPMI_RETRANS="${IPMI_RETRANS:-1}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

leases_raw="$tmp_dir/leases_raw.tsv"
leases_best="$tmp_dir/leases_best.tsv"
alive="$tmp_dir/alive.tsv"
to_scan="$tmp_dir/to_scan.tsv"
out="$tmp_dir/out.tsv"
worker_out="$tmp_dir/worker_out"
new_failures="$tmp_dir/new_failures.tsv"
new_cache="$tmp_dir/new_cache.tsv"

touch "$BLACKLIST_FILE" "$FAILURES_FILE" "$CACHE_FILE"
: > "$new_cache"
: > "$new_failures"

########################################
# Lightweight login test (0penBmc)
########################################
ipmi_login_test() {
  local ip="$1"
  if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    timeout "$LOGIN_TIMEOUT" sudo ipmitool -I "$IPMI_IF" -C "$IPMI_CIPHER" -U "$BMC_USER" -P "$BMC_PASS" -H "$ip" -R "$IPMI_RETRY" -N "$IPMI_RETRANS" chassis status >/dev/null 2>&1
  else
    timeout "$LOGIN_TIMEOUT" ipmitool -I "$IPMI_IF" -C "$IPMI_CIPHER" -U "$BMC_USER" -P "$BMC_PASS" -H "$ip" -R "$IPMI_RETRY" -N "$IPMI_RETRANS" chassis status >/dev/null 2>&1
  fi
}

########################################
# IPMI FRU print
########################################
ipmi_fru_print() {
  local ip="$1"
  if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    sudo ipmitool -I "$IPMI_IF" -C "$IPMI_CIPHER" -U "$BMC_USER" -P "$BMC_PASS" -H "$ip" -R "$IPMI_RETRY" -N "$IPMI_RETRANS" fru print
  else
    ipmitool -I "$IPMI_IF" -C "$IPMI_CIPHER" -U "$BMC_USER" -P "$BMC_PASS" -H "$ip" -R "$IPMI_RETRY" -N "$IPMI_RETRANS" fru print
  fi
}

########################################
# Parse FRU output: SN = Chassis Serial, PN = Chassis Part Number
########################################
parse_fru() {
  awk '
  function trim(s){ sub(/^[ \t]+/,"",s); sub(/[ \t]+$/,"",s); return s }
  function extract_after_label(line, label){
    if(match(line, label "[ \t]*:[ \t]*")){
      return trim(substr(line, RSTART+RLENGTH))
    }
    return ""
  }
  BEGIN{ section=""; bmc=""; smm=""; sn=""; pn="" }
  /^FRU Device Description[ \t]*:/{
    section=$0; sub(/^.*FRU Device Description[ \t]*:[ \t]*/,"",section); sub(/[ \t]*\(.*/,"",section); section=trim(section); next
  }
  /Chassis Serial[ \t]*:/{
    if(sn=="" && section!="BMC_FRU" && section!="SMM_FRU") sn=extract_after_label($0, "Chassis Serial")
    next
  }
  /Chassis Part Number[ \t]*:/{
    if(pn=="" && section!="BMC_FRU" && section!="SMM_FRU") pn=extract_after_label($0, "Chassis Part Number")
    next
  }
  /Board Extra[ \t]*:[ \t]*MAC:[ \t]*/{
    mac=$0; sub(/^.*Board Extra[ \t]*:[ \t]*MAC:[ \t]*/,"",mac); mac=trim(mac)
    mac_clean=mac; gsub(/[^0-9A-Fa-f]/,"",mac_clean)
    is_mac=(length(mac_clean)==12)
    if(section=="BMC_FRU" && bmc=="" && is_mac) bmc=toupper(mac)
    if(section=="SMM_FRU" && smm=="" && is_mac) smm=toupper(mac)
    next
  }
  END{
    if(bmc=="") bmc="NA"
    if(smm=="") smm="NA"
    if(sn=="") sn="NA"
    if(pn=="") pn="NA"
    print bmc "\t" smm "\t" sn "\t" pn
  }
  '
}

########################################
# Parse leases -> mac ip host cltt
########################################
awk -v re="$ALLOW_HOSTS_REGEX" -v ex="$EXCLUDE_HOSTS_REGEX" '
function strip(s){ gsub(/[";]+/,"",s); return s }
function keydate(d,t){ gsub(/\//,"",d); gsub(/:/,"",t); return d t }
$1=="lease" { ip=$2 }
$1=="binding" && $2=="state" && $3=="active;" { active=1 }
$1=="hardware" && $2=="ethernet" { mac=strip($3) }
$1=="client-hostname" { host=strip($2) }
$1=="cltt" { cltt_date=$3; cltt_time=$4; gsub(/;/,"",cltt_time) }
$1=="}"{
  if(active && host ~ re && host !~ ex && mac!="" && ip!="" && cltt_date!="" && cltt_time!=""){
    print mac "\t" ip "\t" host "\t" keydate(cltt_date, cltt_time)
  }
  ip=""; mac=""; host=""; active=0; cltt_date=""; cltt_time=""
}
' "$LEASES_FILE" | sort -V > "$leases_raw"

########################################
# Dedup: keep latest by MAC, then by IP
########################################
awk 'BEGIN{FS=OFS="\t"}{mac=$1;ts=$4;if(!(mac in b)||ts>b[mac]){b[mac]=ts;l[mac]=$0}}END{for(m in l)print l[m]}' "$leases_raw" \
| awk 'BEGIN{FS=OFS="\t"}{ip=$2;ts=$4;if(!(ip in b)||ts>b[ip]){b[ip]=ts;l[ip]=$0}}END{for(i in l)print l[i]}' | sort -V > "$leases_best"

########################################
# Ping + filter blacklist -> to_scan
########################################
now_ts=$(date +%s)
while IFS=$'\t' read -r mac ip host ts; do
  grep -qFx "$ip" "$BLACKLIST_FILE" 2>/dev/null && continue
  if ! ping -c1 -W"$PING_TIMEOUT" "$ip" >/dev/null 2>&1; then continue; fi
  echo -e "$mac\t$ip\t$host" >> "$to_scan"
done < "$leases_best"

########################################
# One worker: login test -> fru print (moi lan scan deu chay ipmitool, khong cache)
########################################
run_one() {
  local mac="$1" ip="$2" host="$3"
  local errfile="$tmp_dir/err_${ip//./_}.txt"
  local bmc_mac="" smm_mac="" chassis_sn="" chassis_pn="" status="FAIL" fru_err=""

  # 1. Login test
  if ! ipmi_login_test "$ip"; then
    echo "FAIL\t$ip" >> "$new_failures"
    echo -e "$ip\tNA\tNA\tNA\tNA\tFAIL\tLogin failed (0penBmc)"
    return
  fi

  # 2. Kiem tra cache: day du SN/PN va chua het han 15 phut
  local cached=""
  if [[ -f "$CACHE_FILE" ]]; then
    cached=$(awk -v ip="$ip" -v now="$now_ts" -v ttl="$CACHE_TTL" -F'\t' '
      $1==ip && NF>=6 && ($2+0)>0 && (now-($2+0))<=ttl && $4!="" && $4!="NA" && $5!="" && $5!="NA" { print $0; exit }
    ' "$CACHE_FILE")
  fi
  if [[ -n "$cached" ]]; then
    read -r bmc_mac smm_mac chassis_sn chassis_pn <<< "$(echo "$cached" | cut -f3,4,5,6)"
    [[ -z "$bmc_mac" ]] && bmc_mac="NA"
    [[ -z "$smm_mac" ]] && smm_mac="NA"
    [[ -z "$chassis_sn" ]] && chassis_sn="NA"
    [[ -z "$chassis_pn" ]] && chassis_pn="NA"
    echo -e "$ip\t$bmc_mac\t$smm_mac\t$chassis_sn\t$chassis_pn\tOK\t"
    return
  fi

  # 3. FRU print
  local fru_out ipmi_cmd
  ipmi_cmd="ipmitool -I $IPMI_IF -C $IPMI_CIPHER -U $BMC_USER -P $BMC_PASS -H $ip -R $IPMI_RETRY -N $IPMI_RETRANS fru print"
  if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    fru_out="$(timeout "$FRU_TIMEOUT" sudo $ipmi_cmd 2> "$errfile")" || true
  else
    fru_out="$(timeout "$FRU_TIMEOUT" $ipmi_cmd 2> "$errfile")" || true
  fi
  if [[ -z "$fru_out" || "$fru_out" != *"FRU Device Description"* ]]; then
    echo "FAIL\t$ip" >> "$new_failures"
    fru_err="$(tail -n1 "$errfile" 2>/dev/null | tr -d '\r' | cut -c1-220)"
    echo -e "$ip\tNA\tNA\tNA\tNA\tFAIL\t${fru_err:-ipmitool fru failed}"
    return
  fi

  read -r bmc_mac smm_mac chassis_sn chassis_pn < <(printf "%s\n" "$fru_out" | parse_fru)
  [[ -z "$bmc_mac" ]] && bmc_mac="NA"
  [[ -z "$smm_mac" ]] && smm_mac="NA"
  [[ -z "$chassis_sn" ]] && chassis_sn="NA"
  [[ -z "$chassis_pn" ]] && chassis_pn="NA"
  status="OK"
  # Luu cache: IP, timestamp, bmc_mac, smm_mac, chassis_sn, chassis_pn (chi khi co SN va PN)
  if [[ "$chassis_sn" != "NA" && "$chassis_pn" != "NA" ]]; then
    echo -e "$ip\t$now_ts\t$bmc_mac\t$smm_mac\t$chassis_sn\t$chassis_pn" >> "$new_cache"
  fi
  echo -e "$ip\t$bmc_mac\t$smm_mac\t$chassis_sn\t$chassis_pn\t$status\t"
}

export -f run_one parse_fru ipmi_login_test ipmi_fru_print
export tmp_dir FAILURES_FILE new_failures new_cache CACHE_FILE CACHE_TTL now_ts
export LOGIN_TIMEOUT FRU_TIMEOUT
export BMC_USER BMC_PASS IPMI_IF IPMI_CIPHER IPMI_RETRY IPMI_RETRANS

command -v ipmitool >/dev/null 2>&1 || { echo "ERROR: ipmitool not found"; exit 2; }

echo -e "SN\tPN\tBMC_IP\tBMC_MAC\tSYS_IP\tSYS_MAC\tFRU_STATUS\tFRU_ERR" > "$out"

if [[ -s "$to_scan" ]]; then
  cat "$to_scan" | xargs -P "$PARALLEL" -I{} bash -c '
    IFS=$'"'"'\t'"'"' read -r mac ip host <<< "{}"
    run_one "$mac" "$ip" "$host"
  ' >> "$out"
fi

########################################
# Update failures (merge with existing, bump count, blacklist at 5)
########################################
while IFS=$'\t' read -r _ fail_ip; do
  [[ -z "$fail_ip" ]] && continue
  curr=$(awk -v ip="$fail_ip" -F'\t' '$1==ip{print $2+1;exit}END{print 1}' "$FAILURES_FILE" 2>/dev/null || echo "1")
  # Update failures file: remove old line for this IP, add new
  grep -v "^${fail_ip}\t" "$FAILURES_FILE" 2>/dev/null > "${FAILURES_FILE}.tmp" || true
  echo -e "${fail_ip}\t${curr}" >> "${FAILURES_FILE}.tmp"
  mv "${FAILURES_FILE}.tmp" "$FAILURES_FILE"
  if [[ "$curr" -ge "$BLACKLIST_FAIL_THRESHOLD" ]]; then
    grep -qFx "$fail_ip" "$BLACKLIST_FILE" 2>/dev/null || echo "$fail_ip" >> "$BLACKLIST_FILE"
    # Remove from failures
    grep -v "^${fail_ip}\t" "$FAILURES_FILE" > "${FAILURES_FILE}.tmp" 2>/dev/null || true
    mv "${FAILURES_FILE}.tmp" "$FAILURES_FILE"
  fi
done < "$new_failures" 2>/dev/null

########################################
# Merge new cache vao cache file (cap nhat timestamp)
########################################
if [[ -s "$new_cache" ]]; then
  while IFS=$'\t' read -r cip cts cbmc csmm cchassis cpn; do
    grep -v "^${cip}\t" "$CACHE_FILE" 2>/dev/null > "${CACHE_FILE}.tmp" || true
    echo -e "${cip}\t${cts}\t${cbmc}\t${csmm}\t${cchassis}\t${cpn:-}" >> "${CACHE_FILE}.tmp"
    mv "${CACHE_FILE}.tmp" "$CACHE_FILE"
  done < "$new_cache"
fi

# Reset failures for IPs that succeeded (login OK or FRU OK)
awk -F'\t' 'NR>1 && $6=="OK" {print $1}' "$out" | while read -r ok_ip; do
  grep -v "^${ok_ip}\t" "$FAILURES_FILE" > "${FAILURES_FILE}.tmp" 2>/dev/null || true
  mv "${FAILURES_FILE}.tmp" "$FAILURES_FILE"
done

########################################
# ARP lookup: SMM_FRU_MAC -> SMM_IP
########################################
arp_map="$tmp_dir/arp_map.tsv"
awk 'NR>1 && $3=="0x2" { gsub(/:/,"",$4); mac=tolower($4); if(length(mac)==12) print mac "\t" $1 }' /proc/net/arp 2>/dev/null | sort -u > "$arp_map"

# Output order: SN, PN, BMC_IP, BMC_MAC, SYS_IP (SMM_IP), SYS_MAC (SMM_FRU_MAC), FRU_STATUS, FRU_ERR
out2="$tmp_dir/out2.tsv"
awk -v arpfile="$arp_map" -F"\t" '
BEGIN{ while((getline < arpfile) > 0) arp[$1]=$2 }
NR==1{ print; next }
{
  ip=($1=="")?"NA":$1; bmc=($2=="")?"NA":$2; smm=($3=="")?"NA":$3
  chassis=($4=="")?"NA":$4; pn=($5=="")?"NA":$5; status=($6=="")?"NA":$6; err=($7=="")?"NA":$7
  smm_ip="NA"
  if(smm!=""&&smm!="NA"){ smm_norm=smm; gsub(/[^0-9A-Fa-f]/,"",smm_norm); smm_norm=tolower(smm_norm); if(length(smm_norm)==12 && smm_norm in arp) smm_ip=arp[smm_norm] }
  print chassis "\t" pn "\t" ip "\t" bmc "\t" smm_ip "\t" smm "\t" status "\t" err
}
' "$out" > "$out2"
mv "$out2" "$out"

if [[ "${OUTPUT_RAW:-0}" == "1" ]]; then cat "$out"; else column -t -s $'\t' "$out"; fi
