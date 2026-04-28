# 🔍 Nmap — Cheatsheet OSCP

## Scans initiaux (ordre recommandé)

```bash
# 1. Ping sweep du subnet (découverte)
nmap -sn 10.10.10.0/24 -oA scans/ping

# 2. Top ports rapide (orientation)
nmap -sS --top-ports 1000 -T4 10.10.10.X -oA scans/top1k

# 3. Full TCP (de rigueur sur l'OSCP)
nmap -sS -sV -sC -p- -T4 10.10.10.X -oA scans/full_tcp

# 4. UDP top 100 (les services clés : SNMP 161, TFTP 69, NTP 123, DNS 53)
sudo nmap -sU --top-ports 100 -T4 10.10.10.X -oA scans/udp
```

## Modes de scan

| Flag | Signification |
|---|---|
| `-sS` | SYN stealth (root required) |
| `-sT` | TCP connect (pas de root) |
| `-sU` | UDP |
| `-sV` | Version detection |
| `-sC` | Default scripts NSE (`-sC` ≈ `--script=default`) |
| `-A` | OS + version + scripts + traceroute (bruyant) |
| `-O` | OS detection |
| `-Pn` | Skip host discovery (si -sn bloque) |
| `-n` | Pas de DNS |
| `--reason` | Pourquoi un port est dit open/filtered |

## Ports

```bash
-p 80,443         # liste
-p 1-1024         # range
-p-               # tous (1-65535)
--top-ports 100   # N top
-F                # fast (top 100)
```

## NSE scripts utiles

```bash
# SMB
nmap --script=smb-enum-shares,smb-enum-users,smb-os-discovery,smb-vuln-* -p445 10.10.10.X

# HTTP
nmap --script=http-enum,http-headers,http-methods,http-title -p80,443 10.10.10.X

# SSL/TLS
nmap --script=ssl-enum-ciphers,ssl-heartbleed -p443 10.10.10.X

# SSH
nmap --script=ssh2-enum-algos,ssh-hostkey -p22 10.10.10.X

# DNS
nmap --script=dns-zone-transfer --script-args=dns-zone-transfer.domain=EXAMPLE.COM -p53 10.10.10.X

# FTP
nmap --script=ftp-anon,ftp-bounce,ftp-syst -p21 10.10.10.X

# SMTP
nmap --script=smtp-enum-users,smtp-commands,smtp-vuln-* -p25 10.10.10.X

# SNMP
nmap --script=snmp-info,snmp-processes,snmp-win32-services -sU -p161 10.10.10.X

# Kerberos / LDAP
nmap --script=krb5-enum-users --script-args=krb5-enum-users.realm=EXAMPLE.COM,userdb=users.txt -p88 10.10.10.X
nmap --script=ldap-search,ldap-rootdse -p389,636 10.10.10.X
```

## Output

```bash
-oN out.nmap       # Normal
-oX out.xml        # XML (pour nmap-to-* tools)
-oG out.grep       # Grepable
-oA base           # Les 3 à la fois
```

## Parse après coup

```bash
# Ports open en une ligne (depuis -oG)
grep open scans/full_tcp.gnmap

# Tous les IPs ayant le port 445 open
grep -l "445/open" scans/*.gnmap

# Convertir XML en HTML
xsltproc out.xml -o out.html
```

## Workflow OSCP pratique

```bash
# Un dossier par machine
mkdir -p scans && cd scans

# Scan "tous les ports" (TCP), doit tourner pendant l'enum
sudo nmap -sS -p- --min-rate=3000 -T4 10.10.10.X -oA all_tcp &

# Pendant ce temps : scripts sur les ports déjà vus
sudo nmap -sC -sV -p22,80,445 10.10.10.X -oA focused

# UDP rapide
sudo nmap -sU --top-ports 50 10.10.10.X -oA udp
```

## Contournements

```bash
# Firewall / IDS : fragmentation
nmap -f -p80 10.10.10.X

# Source port (souvent DNS laissé passer)
nmap --source-port 53 -p80 10.10.10.X

# Decoy
nmap -D RND:5 10.10.10.X

# Timing (0 paranoid → 5 insane)
nmap -T0 10.10.10.X    # très lent, évite les IDS
nmap -T4 10.10.10.X    # OSCP classique
```

> ⚠ **OSCP** : privilégier des scans stables plutôt que rapides. Un scan
> complet TCP (`-p-`) prend ~15 min avec `--min-rate=3000`. Ne jamais
> sauter le full-port scan — les services intéressants sont rarement
> sur les 1000 premiers ports.
